"""
AARM Policy Engine — R3 式(3) の π を完全実装（提案/上書きモデル）

PolicyEngine.evaluate() は常に terminal な AuthorizationResult を返す。
IntentAlignment はその内部協力者（外部から注入される）。

設計方針: docs/design/policy-engine-proposal-override.md §6 参照。

  - decision == DENY  → terminal（IntentAlignment 不要。常に安全側）
  - それ以外（ALLOW / MODIFY / DEFER / STEP_UP、またはルールなし → 暗黙 ALLOW）
      → 「提案」として IntentAlignment に確認する
      → IA が ALLOW → 提案確定
      → IA が ALLOW 以外 → IA の判断で上書き（proposed_decision に元の提案を記録）

収束ループ（§6「MODIFY 変換は書き換え後に再評価して収束させる」）:
  MODIFY ルールが発火するたびにアクションを変換し、変換後のアクションでルール評価を再実行。
  DENY が出たら即 terminal。マッチするルールが尽きたら MODIFY 提案として確定。
  max_modify_iterations（デフォルト 10）で振動を検出し、到達時は DENY。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace as dc_replace
from typing import TYPE_CHECKING, Callable

from .environment import EnvironmentContext
from .models import Action, AuthorizationResult, Decision, SessionContext

if TYPE_CHECKING:
    from .intent_alignment import IntentAlignment


def _match_conditions(
    conditions: dict,
    action: Action,
    environment: EnvironmentContext | None,
) -> bool:
    """全条件が一致した場合に True を返す。any_of（OR）/ none_of（NOT）をサポート。"""
    if "any_of" in conditions:
        if not any(_match_conditions(c, action, environment) for c in conditions["any_of"]):
            return False

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
    """YAML から差し込まれる静的ルールの1エントリ。"""
    id:               str
    decision:         str
    reason:           str
    conditions:       dict        = field(default_factory=dict)
    modify_transform: dict | None = None  # {"param_name": "transform_name"} — MODIFY 時のみ


@dataclass
class Policy:
    """PolicyEngine に渡すポリシー設定。load_policy() で YAML/JSON ファイルから生成する。"""
    denied_tools:                   set[str]             = field(default_factory=set)
    required_params:                dict[str, list[str]] = field(default_factory=dict)
    max_actions:                    int                  = 50
    rules:                          list[StaticRule]     = field(default_factory=list)
    pii_keywords:          frozenset[str] | None = None
    confidential_keywords: frozenset[str] | None = None
    sensitive_tools:       frozenset[str] | None = None
    destructive_tools:     frozenset[str] | None = None
    external_tools:        frozenset[str] | None = None


DEFAULT_POLICY = Policy(
    denied_tools={"drop_database", "delete_all_records", "exfiltrate_data", "disable_logging"},
    required_params={
        "write_file":  ["path", "content"],
        "delete_file": ["path"],
        "send_email":  ["to", "subject", "body"],
    },
)

_DEFAULT_MAX_MODIFY_ITERATIONS = 10


class PolicyEngine:
    def __init__(
        self,
        policy: Policy | None = None,
        transform_registry: dict[str, Callable[[str], str]] | None = None,
        intent_alignment: "IntentAlignment | None" = None,
        max_modify_iterations: int = _DEFAULT_MAX_MODIFY_ITERATIONS,
    ) -> None:
        self._policy                = policy or DEFAULT_POLICY
        self._registry              = transform_registry or {}
        self._ia                    = intent_alignment
        self._max_modify_iterations = max_modify_iterations
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

        # 2. 静的ルール収束ループ
        #    MODIFY がマッチするたびアクションを変換して再評価する。
        #    DENY が出たら即 terminal。ルールが尽きたら MODIFY 提案（変換があれば）。
        #    max_modify_iterations に達したら設定ミス（振動）として DENY。
        current_params    = dict(action.parameters)
        accumulated_mod   = None   # 累積変換結果
        last_rule_id      = None   # 最後に発火した MODIFY ルールの ID
        last_rule_reason  = None
        rule_proposal     = None   # MODIFY 以外のルールがマッチした場合の提案

        for _iter in range(self._max_modify_iterations + 1):
            if _iter == self._max_modify_iterations:
                return AuthorizationResult(
                    decision=Decision.DENY,
                    reason=(
                        f"静的ルール評価が収束しませんでした"
                        f"（max_modify_iterations={self._max_modify_iterations} 到達）。"
                        "ルール設定を確認してください。"
                    ),
                    action=action,
                    decision_source="policy_engine",
                )

            eval_action = Action(
                tool_name=action.tool_name,
                parameters=current_params,
                identity=action.identity,
                action_id=action.action_id,
                timestamp=action.timestamp,
            )
            match = self._find_matching_rule(eval_action, environment)

            if match is None:
                break  # マッチするルールが尽きた

            rule, mod_params = match
            decision = Decision(rule.decision)

            if decision == Decision.DENY:
                try:
                    reason = rule.reason.format(**current_params)
                except (KeyError, ValueError):
                    reason = rule.reason
                return AuthorizationResult(
                    decision=Decision.DENY,
                    reason=reason,
                    action=action,
                    modified_params=accumulated_mod,
                    policy_rule_id=rule.id,
                    decision_source="policy_engine",
                )

            if decision == Decision.MODIFY and mod_params is not None:
                current_params  = mod_params
                accumulated_mod = mod_params
                last_rule_id    = rule.id
                try:
                    last_rule_reason = rule.reason.format(**action.parameters)
                except (KeyError, ValueError):
                    last_rule_reason = rule.reason
                continue  # 変換後のアクションで再評価

            # MODIFY 以外（DEFER / STEP_UP / ALLOW from rules）→ ループを抜ける
            try:
                reason = rule.reason.format(**current_params)
            except (KeyError, ValueError):
                reason = rule.reason
            rule_proposal = AuthorizationResult(
                decision=decision,
                reason=reason,
                action=action,
                modified_params=accumulated_mod,  # それまでの MODIFY 変換を保持
                policy_rule_id=rule.id,
                decision_source="policy_engine",
            )
            break

        # ループを "match is None" で抜け、かつ変換が累積していた場合 → MODIFY 提案
        if rule_proposal is None and accumulated_mod is not None:
            rule_proposal = AuthorizationResult(
                decision=Decision.MODIFY,
                reason=last_rule_reason or "",
                action=action,
                modified_params=accumulated_mod,
                policy_rule_id=last_rule_id,
                decision_source="policy_engine",
            )

        # 3. required_params のチェック — 最終 a'（current_params）に対して行う
        #    提案（DENY 以外）として扱い、IntentAlignment を通す。
        #    変換済み accumulated_mod は保持したまま DEFER 提案に切り替える。
        missing = [
            k for k in p.required_params.get(action.tool_name, [])
            if k not in current_params
        ]
        if missing:
            proposal = AuthorizationResult(
                decision=Decision.DEFER,
                reason=f"'{action.tool_name}' に必須パラメータが足りません: {missing}",
                action=action,
                modified_params=accumulated_mod,
                decision_source="policy_engine",
            )
            return self._confirm_with_ia(proposal, action, context_summary, environment)

        # 4. 最大アクション数の制限 — DENY は terminal
        action_count = sum(1 for e in context.action_history if e.get("type") != "tool_output")
        if action_count >= p.max_actions:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"アクション数上限 ({p.max_actions}) に達しました。",
                action=action,
                decision_source="policy_engine",
            )

        # 5. 提案を IntentAlignment に確認
        proposal = rule_proposal or AuthorizationResult(
            decision=Decision.ALLOW,
            reason="ポリシー通過。",
            action=action,
            decision_source="policy_engine",
        )
        return self._confirm_with_ia(proposal, action, context_summary, environment)

    def _find_matching_rule(
        self,
        eval_action: Action,
        environment: EnvironmentContext | None,
    ) -> tuple[StaticRule, dict | None] | None:
        """
        eval_action に対して最初にマッチするルールと変換後パラメータを返す。
        MODIFY でない場合の変換後パラメータは None。マッチなしは None。
        """
        for rule in self._policy.rules:
            if not _match_conditions(rule.conditions, eval_action, environment):
                continue

            decision = Decision(rule.decision)
            if decision == Decision.MODIFY and rule.modify_transform:
                modified_params = dict(eval_action.parameters)
                for param, transform_name in rule.modify_transform.items():
                    transform = self._registry.get(transform_name)
                    if transform and param in modified_params:
                        modified_params[param] = transform(str(modified_params[param]))
                return rule, modified_params

            return rule, None

        return None

    def _confirm_with_ia(
        self,
        proposal: AuthorizationResult,
        original_action: Action,
        context_summary: dict,
        environment: EnvironmentContext | None,
    ) -> AuthorizationResult:
        """
        提案を IntentAlignment に確認する。IA が未注入の場合は提案をそのまま確定。

        IntentAlignment には常に original_action（a）を渡す。IA の役割は
        「エージェントの意図 a が妥当か」の評価であり、実行されるパラメータ a' が
        安全かどうかではない。パラメータの封じ込め（path 無害化等）は PolicyEngine の
        決定論的な別レイヤーであり、IA はそれを覆す権威を持たない。

        採用関係は非対称:
        - IA が ALLOW → proposal をそのまま確定（decision・modified_params・
          policy_rule_id は PolicyEngine 提案のまま）。
        - IA が ALLOW 以外（DENY/DEFER/STEP_UP） → 最終 decision・reason は IA のものを
          採用する（IA は「a が妥当でない」という判断自体の権威を持つ）。ただし
          modified_params は proposal（PolicyEngine 由来）を保持し、IA の結果で
          上書きしない — IA は変換を生成も書き換えもできない。
        """
        if self._ia is None:
            return proposal

        ia_result = self._ia.evaluate(original_action, context_summary, environment)

        if ia_result.decision == Decision.ALLOW:
            return proposal  # 提案確定

        # IA が上書き — decision/reason は IA 由来。modified_params は proposal を保持し、
        # policy_rule_id（発火ルール）と proposed_decision（元の提案）を記録する。
        return dc_replace(
            ia_result,
            modified_params=proposal.modified_params,
            policy_rule_id=proposal.policy_rule_id,
            proposed_decision=proposal.decision.value,
        )
