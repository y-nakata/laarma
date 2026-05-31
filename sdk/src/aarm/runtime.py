"""
AARM Runtime — R1〜R6 統合
「インターセプト → コンテキスト蓄積 → ポリシー評価 → 意図整合性評価 → 記録」
"""

from __future__ import annotations

import os
from typing import Any

from .context_accumulator import ContextAccumulator
from .intent_alignment import IntentAlignment
from .models import Action, AuthorizationResult, Decision, IdentityContext
from .policy_engine import DEFAULT_POLICY, Policy, PolicyEngine


class AARMRuntime:
    def __init__(
        self,
        user_intent: str,
        identity: IdentityContext | None = None,
        policy: Policy | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        skip_intent_alignment: bool = False,
    ) -> None:
        self._identity              = identity
        self._accumulator           = ContextAccumulator(user_intent=user_intent, metadata=metadata)
        self._policy_engine         = PolicyEngine(policy=policy or DEFAULT_POLICY)
        self._intent_alignment      = IntentAlignment(model=model or os.getenv("AARM_MODEL", "claude-sonnet-4-6"))
        self._skip_intent_alignment = skip_intent_alignment

    def intercept(self, tool_name: str, parameters: dict[str, Any]) -> AuthorizationResult:
        action = Action(tool_name=tool_name, parameters=parameters, identity=self._identity)
        self._accumulator.record_action(action)
        result = self._policy_engine.evaluate(action, self._accumulator.context)
        if result is None:
            if self._skip_intent_alignment:
                result = AuthorizationResult(decision=Decision.ALLOW, reason="ポリシー通過。", action=action)
            else:
                result = self._intent_alignment.evaluate(action, self._accumulator.summary())
        self._accumulator.record_result(result)
        self._log(result)
        return result

    def record_tool_output(self, action_id: str, output: Any) -> None:
        self._accumulator.record_tool_output(action_id, output)

    @property
    def session_id(self) -> str:           return self._accumulator.context.session_id
    @property
    def receipts(self) -> list[dict]:      return self._accumulator.receipts
    @property
    def context_summary(self) -> dict:     return self._accumulator.summary()
    @property
    def identity(self) -> IdentityContext | None: return self._identity

    def _log(self, result: AuthorizationResult) -> None:
        icon = {Decision.ALLOW: "✅", Decision.DENY: "❌",
                Decision.MODIFY: "✏️", Decision.DEFER: "⏸️",
                Decision.STEP_UP: "🚨"}.get(result.decision, "?")
        who = f" | {self._identity.human_principal}" if self._identity else ""
        print(f"[AARM] {icon} {result.decision.value:7s} | {result.action.tool_name:25s} | {result.reason}{who}")
