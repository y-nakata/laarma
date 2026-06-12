"""
AARM Policy Engine — R3 式(3) の π を完全実装（提案/上書きモデル）

PolicyEngine.evaluate() は常に terminal な AuthorizationResult を返す。
IntentAlignment はその内部協力者（外部から注入される）。

設計方針: docs/design/policy-engine-modify.md §6 参照。

  - decision == DENY  → terminal（IntentAlignment 不要。常に安全側）
  - それ以外（ALLOW / MODIFY / DEFER / STEP_UP、またはルールなし → 暗黙 ALLOW）
      → 「提案」として IntentAlignment に確認する
      → IA が ALLOW → 提案確定
      → IA が ALLOW 以外 → IA の判断で上書き（proposed_decision に元の提案を記録）
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Callable

from .environment import EnvironmentContext
from .models import Action, AuthorizationResult, Decision, SessionContext
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .intent_alignment import IntentAlignment


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
        intent_alignment: "IntentAlignment | None" = None,
    ) -> None:
        self._policy   = policy or DEFAULT_POLICY
        self._registry = transform_registry or {}
        self._ia       = intent_alignment
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
        context_summary: dict,
        environment: EnvironmentContext | None = None,
    ) -> AuthorizationResult:
        """
        式(3)の π として (a, C, E) を評価し、常に terminal な AuthorizationResult を返す。

        DENY は即 terminal。それ以外は「提案」として IntentAlignment に確認する。
        IntentAlignment が ALLOW → 提案確定。ALLOW 以外 → 上書き。
        """
        p = self._policy

        # 0. privilege_scope チェック — DENY は常に terminal（安全側）
        if action.identity and action.identity.privilege_scope:
            if action.tool_name not in action.identity.privilege_scope:
                return AuthorizationResult(
                    decision=Decision.DENY,
                    reason=f"'{action.tool_name}' は privilege_scope 外のツールです。",
                    action=action,
                    decision_source="privilege_scope",
                )

        # 1. 絶対禁止ツールの判定 — DENY は常に terminal
        if action.tool_name in p.denied_tools:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"'{action.tool_name}' はポリシーにより絶対禁止です。",
                action=action,
                decision_source="denied_tools",
            )

        # 2. 設定ファイルから差し込まれたルールを評価
        rule_result = self._evaluate_rules(action, environment)
        if rule_result is not None and rule_result.decision == Decision.DENY:
            return rule_result  # DENY は terminal

        # 3. 必須パラメータのチェック — 構文エラーは意図整合性問題でないため terminal
        missing = [k for k in p.required_params.get(action.tool_name, []) if k not in action.parameters]
        if missing:
            return AuthorizationResult(
                decision=Decision.DEFER,
                reason=f"'{action.tool_name}' に必須パラメータが足りません: {missing}",
                action=action,
                decision_source="policy_engine",
            )

        # 4. 最大アクション数の制限 — DENY は terminal
        action_count = sum(1 for e in context.action_history if e.get("type") != "tool_output")
        if action_count >= p.max_actions:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"アクション数上限 ({p.max_actions}) に達しました。",
                action=action,
                decision_source="policy_engine",
            )

        # 5. 提案/上書きモデル: rule_result（DENY 以外）または暗黙 ALLOW を「提案」として IA に確認
        proposal = rule_result or AuthorizationResult(
            decision=Decision.ALLOW,
            reason="ポリシー通過。",
            action=action,
            decision_source="policy_engine",
        )
        return self._confirm_with_ia(proposal, action, context_summary, environment)

    def _confirm_with_ia(
        self,
        proposal: AuthorizationResult,
        original_action: Action,
        context_summary: dict,
        environment: EnvironmentContext | None,
    ) -> AuthorizationResult:
        """
        提案を IntentAlignment に確認する。
        IA が ALLOW → 提案確定。ALLOW 以外 → IA の判断で上書き（proposed_decision を記録）。
        IA が注入されていない（スタブなし）場合は提案をそのまま確定。
        """
        if self._ia is None:
            return proposal

        # MODIFY の場合は変換後のアクション a' を IA に渡す
        if proposal.decision == Decision.MODIFY and proposal.modified_params:
            eval_action = Action(
                tool_name=original_action.tool_name,
                parameters=proposal.modified_params,
                identity=original_action.identity,
                action_id=original_action.action_id,
                timestamp=original_action.timestamp,
            )
        else:
            eval_action = original_action

        ia_result = self._ia.evaluate(eval_action, context_summary, environment)

        if ia_result.decision == Decision.ALLOW:
            return proposal  # 提案確定

        # IA が上書き — policy_rule_id（発火ルール）を保持しつつ、proposed_decision を記録
        from dataclasses import replace
        return replace(
            ia_result,
            policy_rule_id=proposal.policy_rule_id,
            proposed_decision=proposal.decision.value,
        )

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
                    policy_rule_id=rule.id,
                    decision_source="policy_engine",
                )

            try:
                reason = rule.reason.format(**action.parameters)
            except (KeyError, ValueError):
                reason = rule.reason
            return AuthorizationResult(
                decision=decision,
                reason=reason,
                action=action,
                policy_rule_id=rule.id,
                decision_source="policy_engine",
            )

        return None
