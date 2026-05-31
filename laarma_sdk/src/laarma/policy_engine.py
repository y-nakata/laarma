"""
AARM Policy Engine — R3 (静的ルール層)
None を返した場合は Intent Alignment へ。None == ALLOW ではない。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Action, AuthorizationResult, Decision, SessionContext


@dataclass
class Policy:
    denied_tools:    set[str]             = field(default_factory=set)
    required_params: dict[str, list[str]] = field(default_factory=dict)
    max_actions:     int                  = 50


DEFAULT_POLICY = Policy(
    denied_tools={"drop_database", "delete_all_records", "exfiltrate_data", "disable_logging"},
    required_params={
        "write_file":  ["path", "content"],
        "delete_file": ["path"],
        "send_email":  ["to", "subject", "body"],
    },
)


class PolicyEngine:
    def __init__(self, policy: Policy | None = None) -> None:
        self._policy = policy or DEFAULT_POLICY

    def evaluate(self, action: Action, context: SessionContext) -> AuthorizationResult | None:
        p = self._policy
        if action.tool_name in p.denied_tools:
            return AuthorizationResult(decision=Decision.DENY,
                reason=f"'{action.tool_name}' はポリシーにより絶対禁止です。", action=action)
        missing = [k for k in p.required_params.get(action.tool_name, []) if k not in action.parameters]
        if missing:
            return AuthorizationResult(decision=Decision.DEFER,
                reason=f"'{action.tool_name}' に必須パラメータが足りません: {missing}", action=action)
        action_count = sum(1 for e in context.action_history if e.get("type") != "tool_output")
        if action_count >= p.max_actions:
            return AuthorizationResult(decision=Decision.DENY,
                reason=f"アクション数上限 ({p.max_actions}) に達しました。", action=action)
        return None  # Intent Alignment へ
