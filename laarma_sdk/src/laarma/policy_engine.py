"""
AARM Policy Engine — R3 式(3) の π を評価する priority 解決エンジン

PolicyEngine.evaluate() は常に terminal な AuthorizationResult を返す単一の関数である
（式3: π:(a,C)→{ALLOW,DENY,MODIFY,STEP_UP,DEFER}）。

設計方針: docs/design/decision-layer-policy-engine.md 参照。

  - `rules` に対する評価は1パスのみ（収束ループは持たない）。
    全マッチするルールを収集し、最高 priority のグループで decision を決める。
    同一 priority グループ内で decision が割れている（または MODIFY が複数マッチした）場合は
    R3(b) の同一 priority 競合として terminal DEFER にする。
  - MODIFY は変換を1回だけ適用して terminal（変換後に再ループしない。変換後に別ルールが
    マッチするならルール集合が矛盾しており、それは同一 priority 競合の枠組みでは捉えられない
    設定ミスである——δ 参照ルールを MODIFY より高 priority に置くことで意図整合性を担保する
    設計は Phase B の対象）。
  - denied_tools / privilege_scope は `rules` の priority システムの外側にある独立した
    事前チェックとして扱う（R3/Table I の Forbidden 分類——コンテキスト評価が完全に無視される
    唯一の分類——に対応）。
  - ルール条件は `context.<signal>` で `derived_signals()`（δ）を参照できる。数値シグナル
    （semantic_distance / confidence_level）は述語オブジェクト `{演算子: 値}` で
    gt/gte/lt/lte/eq、集合シグナル（data_classification）は `{contains: 値}` を使う。
    boolean シグナル（action_matches_intent / scope_expansion_detected /
    scope_expansion_recent）は演算子オブジェクトでなく直接値（`action_matches_intent: false`）
    で書く（`eq` 一択で演算子の明示が無意味なため）。
    R3(a)（未 populate な context 参照 → DEFER）は実装しない。laarma の同期モデルでは δ は
    評価前に必ず算出され「未 populate」が生じないため（derived_signals() は常にデフォルト値で
    埋まる）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, NamedTuple

from .environment import EnvironmentContext
from .models import Action, AuthorizationResult, Decision, SessionContext


_NUMERIC_PREDICATE_OPS: dict[str, Callable[[float, float], bool]] = {
    "gt":  lambda value, operand: value > operand,
    "gte": lambda value, operand: value >= operand,
    "lt":  lambda value, operand: value < operand,
    "lte": lambda value, operand: value <= operand,
    "eq":  lambda value, operand: value == operand,
}


def _match_context_predicate(value: Any, predicate: dict | bool) -> bool:
    """derived_signals() の1シグナル値が述語に一致するか判定する。

    boolean シグナル（例: action_matches_intent）は演算子オブジェクトでなく直接値で
    記述する（`eq` 一択で演算子の明示が無意味なため）。predicate が dict でなければ
    等値比較で判定する。

    複数演算子キーを持つ predicate は AND 評価（例: {"gt": 0.3, "lt": 0.9} で範囲指定）。
    未参照・デフォルト値の区別は行わない（R3(a) 非実装。#112 Phase B0）ため、value が
    None または空集合の場合は「安全側 = 不一致」として false を返す。
    """
    if not isinstance(predicate, dict):
        return value == predicate

    for op, operand in predicate.items():
        if op == "contains":
            if operand not in (value or []):
                return False
        elif op in _NUMERIC_PREDICATE_OPS:
            if value is None or not _NUMERIC_PREDICATE_OPS[op](value, operand):
                return False
        else:
            raise ValueError(f"未知の context 述語演算子です: {op!r}")
    return True


def _match_conditions(
    conditions: dict,
    action: Action,
    environment: EnvironmentContext | None,
    derived_signals: dict | None = None,
) -> bool:
    """全条件が一致した場合に True を返す。any_of（OR）/ none_of（NOT）をサポート。"""
    if "any_of" in conditions:
        if not any(
            _match_conditions(c, action, environment, derived_signals)
            for c in conditions["any_of"]
        ):
            return False

    if "none_of" in conditions:
        if any(
            _match_conditions(c, action, environment, derived_signals)
            for c in conditions["none_of"]
        ):
            return False

    if "tool" in conditions:
        tool_condition = conditions["tool"]
        if isinstance(tool_condition, list):
            if action.tool_name not in tool_condition:
                return False
        elif action.tool_name != tool_condition:
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

    signals = derived_signals or {}
    for signal, predicate in conditions.get("context", {}).items():
        if not _match_context_predicate(signals.get(signal), predicate):
            return False

    return True


@dataclass
class StaticRule:
    """YAML から差し込まれる静的ルールの1エントリ。"""
    id:               str
    decision:         str
    reason:           str
    conditions:       dict        = field(default_factory=dict)
    modify_transform: dict | None = None  # {"param_name": "transform_name"} — MODIFY 時のみ
    priority:         int         = 0     # 値が大きいほど優先。無指定のルールは全て同一階層(0)


@dataclass
class Policy:
    """PolicyEngine に渡すポリシー設定。load_policy() で YAML/JSON ファイルから生成する。"""
    denied_tools:                   set[str]             = field(default_factory=set)
    max_actions:                    int                  = 50
    rules:                          list[StaticRule]     = field(default_factory=list)
    pii_keywords:          frozenset[str] | None = None
    confidential_keywords: frozenset[str] | None = None
    sensitive_tools:       frozenset[str] | None = None
    destructive_tools:     frozenset[str] | None = None
    external_tools:        frozenset[str] | None = None


DEFAULT_POLICY = Policy(
    denied_tools={"drop_database", "delete_all_records", "exfiltrate_data", "disable_logging"},
)


class _PriorityResolution(NamedTuple):
    """`_resolve_priority()` の結果。winner と conflict_group は排他的（片方は必ず None）。"""
    winner:         StaticRule | None
    conflict_group: list[StaticRule] | None
    top_priority:   int | None


class PolicyEngine:
    def __init__(
        self,
        policy: Policy | None = None,
        transform_registry: "dict[str, Callable[[str], str]] | None" = None,
    ) -> None:
        self._policy   = policy or DEFAULT_POLICY
        self._registry = transform_registry or {}
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
        """
        p = self._policy

        # 0. privilege_scope チェック — DENY は常に terminal
        # fail-closed: privilege_scope は ALLOW の明示的根拠（最小権限、仕様 R9）。
        # identity が無い、または privilege_scope が未設定/空の主体は明示的根拠を持たないため DENY。
        if not action.identity or not action.identity.privilege_scope:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason="privilege_scope が未設定のため、許可の明示的根拠がありません。",
                action=action,
                decision_source="privilege_scope",
            )
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

        # 2. 静的ルール評価 — 1パスのみ（収束ループは持たない）
        #    全マッチを収集し priority で解決する。同一 priority で decision が割れている
        #    （または MODIFY が複数マッチした）場合は terminal DEFER（R3(b) 競合トリガー）。
        rule_proposal: AuthorizationResult | None = None
        current_params = dict(action.parameters)
        derived_signals = context_summary.get("derived_signals", {})

        matches = self._collect_matching_rules(action, environment, derived_signals)
        if matches:
            resolution = self._resolve_priority(matches)

            if resolution.conflict_group is not None:
                group = resolution.conflict_group
                decisions = ",".join(dict.fromkeys(r.decision for r in group))
                names = " / ".join(f"{r.id}({r.decision})" for r in group)
                return AuthorizationResult(
                    decision=Decision.DEFER,
                    reason=(
                        f"同一優先度(priority={resolution.top_priority})で競合する複数のルールが"
                        f"マッチしました: {names} — 安全側として保留します。"
                    ),
                    action=action,
                    policy_rule_id=",".join(r.id for r in group),
                    proposed_decision=decisions,
                    decision_source="policy_engine",
                )

            winner = resolution.winner
            if winner is None:
                # _resolve_priority() の不変条件: conflict_group が None なら winner は必ず設定される。
                # ここに来るのは _resolve_priority() 自体にバグがある場合のみ。
                raise RuntimeError("_resolve_priority() が winner・conflict_group のどちらも返しませんでした。")
            decision = Decision(winner.decision)

            if decision == Decision.DENY:
                try:
                    reason = winner.reason.format(**current_params)
                except (KeyError, ValueError):
                    reason = winner.reason
                return AuthorizationResult(
                    decision=Decision.DENY,
                    reason=reason,
                    action=action,
                    policy_rule_id=winner.id,
                    decision_source="policy_engine",
                )

            if decision == Decision.MODIFY:
                modified_params = dict(current_params)
                if winner.modify_transform:
                    for param, transform_name in winner.modify_transform.items():
                        transform = self._registry.get(transform_name)
                        if transform and param in modified_params:
                            modified_params[param] = transform(str(modified_params[param]))
                current_params = modified_params
                try:
                    reason = winner.reason.format(**action.parameters)
                except (KeyError, ValueError):
                    reason = winner.reason
                rule_proposal = AuthorizationResult(
                    decision=Decision.MODIFY,
                    reason=reason,
                    action=action,
                    modified_params=modified_params,
                    policy_rule_id=winner.id,
                    decision_source="policy_engine",
                )
            else:
                # ALLOW / DEFER / STEP_UP
                try:
                    reason = winner.reason.format(**current_params)
                except (KeyError, ValueError):
                    reason = winner.reason
                rule_proposal = AuthorizationResult(
                    decision=decision,
                    reason=reason,
                    action=action,
                    policy_rule_id=winner.id,
                    decision_source="policy_engine",
                )

        # 3. 最大アクション数の制限 — DENY は terminal。固定階層。
        action_count = sum(1 for e in context.action_history if e.get("type") != "tool_output")
        if action_count >= p.max_actions:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"アクション数上限 ({p.max_actions}) に達しました。",
                action=action,
                decision_source="policy_engine",
            )

        # 4. rules 評価の結果をそのまま最終決定とする。マッチが無ければベースライン ALLOW。
        #    このベースライン ALLOW は privilege_scope・denied_tools・max_actions を
        #    全て通過した上での ALLOW であり、無審査の default ではない。
        if rule_proposal is not None:
            return rule_proposal
        return AuthorizationResult(
            decision=Decision.ALLOW,
            reason="ポリシー通過。",
            action=action,
            decision_source="baseline_allow",
        )

    def _collect_matching_rules(
        self,
        action: Action,
        environment: EnvironmentContext | None,
        derived_signals: dict | None = None,
    ) -> list[StaticRule]:
        """action にマッチする全ルールを YAML 記述順で返す。"""
        return [
            rule for rule in self._policy.rules
            if _match_conditions(rule.conditions, action, environment, derived_signals)
        ]

    def _resolve_priority(self, matches: list[StaticRule]) -> _PriorityResolution:
        """
        全マッチから最高 priority のグループを取り、勝者か競合グループを返す。

        競合の定義（単一の原則）:
          - グループが1件のみ → 競合なし。
          - グループが複数件で、全員 decision が同じ かつ decision != MODIFY → 競合なし
            （扱いが一致しているので YAML 記述順の最初を勝者とする）。
          - それ以外（decision が割れている、または MODIFY が複数マッチ）→ 競合。
            MODIFY×MODIFY を無条件に競合とするのは、対象パラメータキーが重ならない場合でも
            1パスでの複数変換マージを行わないため（YAGNI）。
        """
        top_priority = max(r.priority for r in matches)
        group = [r for r in matches if r.priority == top_priority]

        if len(group) == 1:
            return _PriorityResolution(winner=group[0], conflict_group=None, top_priority=top_priority)

        decisions = {r.decision for r in group}
        if len(decisions) == 1 and Decision(next(iter(decisions))) != Decision.MODIFY:
            return _PriorityResolution(winner=group[0], conflict_group=None, top_priority=top_priority)

        return _PriorityResolution(winner=None, conflict_group=group, top_priority=top_priority)
