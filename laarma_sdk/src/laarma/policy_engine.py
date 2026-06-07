"""
AARM Policy Engine — R3 (静的ルール層)
None を返した場合は Intent Alignment へ。None == ALLOW ではない。

Policy Engine は「何があっても絶対にアウト」なものだけを弾く
最小の静的ゲートとして振る舞います。

責務:
  - DENY: 絶対禁止ツールのブロック
  - DEFER: 必須パラメータ不足の一時保留
  - DENY: アクション数上限の制御
  - YAML 差し込みルールの評価 (DENY / DEFER / MODIFY)

【設計注記: PolicyEngine の MODIFY について】
AARM 仕様では MODIFY は (a, C, E) タプルを評価する動的判断である。
PolicyEngine が MODIFY を返す場合（例: 危険な書き込みパスの basename 変換）は
AARM 仕様外の実用的妥協である。
ドメイン固有の決定論的変換ルールは IntentAlignment に混入させず
PolicyEngine で完結させることで層の責務を明確化している。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

from .environment import EnvironmentContext
from .models import Action, AuthorizationResult, Decision, SessionContext


def _match_conditions(
    conditions: dict,
    action: Action,
    environment: EnvironmentContext | None,
) -> bool:
    """全条件が一致した場合に True を返す。any_of（OR）/ none_of（NOT）をサポート。"""
    # any_of: リスト内のいずれか1つが一致すれば通過（OR 演算）
    if "any_of" in conditions:
        if not any(_match_conditions(c, action, environment) for c in conditions["any_of"]):
            return False

    # none_of: リスト内のすべてが不一致なら通過（NOT 演算）
    if "none_of" in conditions:
        if any(_match_conditions(c, action, environment) for c in conditions["none_of"]):
            return False

    if "tool" in conditions and action.tool_name != conditions["tool"]:
        return False

    if "environment_type" in conditions:
        if not environment or environment.environment != conditions["environment_type"]:
            return False

    if conditions.get("not_in_maintenance_window"):
        if not environment or environment.in_maintenance_window():
            return False

    for param, pattern in conditions.get("param_matches", {}).items():
        value = str(action.parameters.get(param, ""))
        if not re.search(pattern, value):
            return False

    return True


@dataclass
class StaticRule:
    """
    YAML から差し込まれる静的ルールの1エントリ。
    conditions が全て一致したとき decision を返す。
    """
    id:               str
    decision:         str
    reason:           str
    conditions:       dict       = field(default_factory=dict)
    modify_transform: dict | None = None  # {"param_name": "transform_name"} — MODIFY 時のみ


@dataclass
class Policy:
    """
    PolicyEngine に渡すポリシー設定。
    load_policy() で YAML/JSON ファイルから生成する。
    """
    denied_tools:                   set[str]             = field(default_factory=set)
    required_params:                dict[str, list[str]] = field(default_factory=dict)
    max_actions:                    int                  = 50
    rules:                          list[StaticRule]     = field(default_factory=list)
    # IntentAlignment へ橋渡しする評価パラメータ（Policy に同居させることで一元管理）
    confidence_defer_threshold:     float                = 0.4
    scope_expansion_deny_threshold: float                = 0.4
    # データ分類キーワード（省略時は context_accumulator.py のデフォルト値を使う）
    pii_keywords:          frozenset[str] | None = None
    confidential_keywords: frozenset[str] | None = None
    sensitive_tools:       frozenset[str] | None = None
    destructive_tools:     frozenset[str] | None = None


DEFAULT_POLICY = Policy(
    denied_tools={"drop_database", "delete_all_records", "exfiltrate_data", "disable_logging"},
    required_params={
        "write_file":  ["path", "content"],
        "delete_file": ["path"],
        "send_email":  ["to", "subject", "body"],
    },
)


class PolicyEngine:
    def __init__(
        self,
        policy: Policy | None = None,
        transform_registry: dict[str, Callable[[str], str]] | None = None,
    ) -> None:
        self._policy   = policy or DEFAULT_POLICY
        self._registry = transform_registry or {}
        # フェイルファスト: rules が参照する変換名がレジストリに存在するか検証
        for rule in self._policy.rules:
            if rule.modify_transform:
                for transform_name in rule.modify_transform.values():
                    if transform_name not in self._registry:
                        raise ValueError(
                            f"ルール '{rule.id}' が参照する変換名 '{transform_name}' が "
                            f"transform_registry に存在しません。"
                        )

    def evaluate(
        self,
        action: Action,
        context: SessionContext,
        environment: EnvironmentContext | None = None,
    ) -> AuthorizationResult | None:
        p = self._policy

        # 1. 絶対禁止ツールの判定（Policy Engine 本来の責務）
        if action.tool_name in p.denied_tools:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"'{action.tool_name}' はポリシーにより絶対禁止です。",
                action=action,
            )

        # 2. 設定ファイルから差し込まれたルールを評価
        rule_result = self._evaluate_rules(action, environment)
        if rule_result is not None:
            return rule_result

        # 3. 必須パラメータのチェック（Policy Engine 本来の責務）
        missing = [k for k in p.required_params.get(action.tool_name, []) if k not in action.parameters]
        if missing:
            return AuthorizationResult(
                decision=Decision.DEFER,
                reason=f"'{action.tool_name}' に必須パラメータが足りません: {missing}",
                action=action,
            )

        # 4. 最大アクション数の制限（Policy Engine 本来の責務）
        action_count = sum(1 for e in context.action_history if e.get("type") != "tool_output")
        if action_count >= p.max_actions:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"アクション数上限 ({p.max_actions}) に達しました。",
                action=action,
            )

        return None  # 動的評価層（Intent Alignment）へ委譲

    def _evaluate_rules(
        self,
        action: Action,
        environment: EnvironmentContext | None,
    ) -> AuthorizationResult | None:
        for rule in self._policy.rules:
            if not _match_conditions(rule.conditions, action, environment):
                continue

            decision = Decision(rule.decision)

            if decision == Decision.MODIFY and rule.modify_transform:
                modified_params = dict(action.parameters)
                for param, transform_name in rule.modify_transform.items():
                    transform = self._registry.get(transform_name)
                    if transform and param in modified_params:
                        modified_params[param] = transform(str(modified_params[param]))
                try:
                    reason = rule.reason.format(**action.parameters)
                except (KeyError, ValueError):
                    reason = rule.reason
                return AuthorizationResult(
                    decision=Decision.MODIFY,
                    reason=reason,
                    action=action,
                    modified_params=modified_params,
                )

            try:
                reason = rule.reason.format(**action.parameters)
            except (KeyError, ValueError):
                reason = rule.reason
            return AuthorizationResult(decision=decision, reason=reason, action=action)

        return None
