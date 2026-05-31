"""
AARM Context Accumulator — R2
Cn = Cn-1 ∪ {an, on, δn} — 仕様 IV-C
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import Action, AuthorizationResult, SessionContext

_PII_KEYWORDS      = {"email", "password", "phone", "address", "ssn", "credit", "customer", "personal"}
_CONFIDENTIAL_KEYS = {"secret", "token", "key", "credential", "private", "internal", "config"}
_SENSITIVE_TOOLS   = {"database", "db", "read_file", "execute_shell", "execute_sql"}


def _compute_semantic_distance(user_intent: str, tool_name: str, parameters: dict) -> float:
    intent_tokens = set(user_intent.lower().split())
    action_tokens = set(tool_name.lower().replace("_", " ").split())
    for v in parameters.values():
        action_tokens.update(str(v).lower().split())
    union = len(intent_tokens | action_tokens)
    return round(1.0 - len(intent_tokens & action_tokens) / union, 3) if union else 0.0


def _classify_data(tool_name: str, parameters: dict) -> list[str]:
    combined = (tool_name + " " + " ".join(str(v) for v in parameters.values())).lower()
    labels = []
    if any(k in combined for k in _PII_KEYWORDS):      labels.append("PII")
    if any(k in combined for k in _CONFIDENTIAL_KEYS): labels.append("CONFIDENTIAL")
    if tool_name in _SENSITIVE_TOOLS:                  labels.append("SENSITIVE_TOOL")
    return labels or ["PUBLIC"]


def _detect_scope_expansion(user_intent: str, tool_name: str, parameters: dict) -> bool:
    external = {"send_email", "http_request", "webhook", "slack_message"}
    return tool_name in external and "send" not in user_intent.lower() and "email" not in user_intent.lower()


class ContextAccumulator:
    def __init__(self, user_intent: str, metadata: dict[str, Any] | None = None) -> None:
        self._context = SessionContext(user_intent=user_intent, metadata=metadata or {})
        self._receipts: list[dict]  = []
        self._data_classifications: list[str]   = []
        self._semantic_distances:   list[float] = []
        self._scope_expansions:     list[bool]  = []

    def record_action(self, action: Action) -> None:
        self._context.append_action(action)
        self._data_classifications.extend(_classify_data(action.tool_name, action.parameters))
        self._semantic_distances.append(_compute_semantic_distance(
            self._context.user_intent, action.tool_name, action.parameters))
        self._scope_expansions.append(_detect_scope_expansion(
            self._context.user_intent, action.tool_name, action.parameters))

    def record_result(self, result: AuthorizationResult) -> None:
        self._receipts.append(result.to_dict())

    def record_tool_output(self, action_id: str, output: Any) -> None:
        self._context.action_history.append({
            "type": "tool_output", "action_id": action_id,
            "output": str(output), "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    @property
    def context(self) -> SessionContext:
        return self._context

    @property
    def receipts(self) -> list[dict]:
        return list(self._receipts)

    def recent_actions(self, n: int = 5) -> list[dict]:
        actions = [e for e in self._context.action_history if e.get("type") != "tool_output"]
        return list(reversed(actions[-n:]))

    def derived_signals(self) -> dict:
        d = self._semantic_distances
        return {
            "data_classifications":     sorted(set(self._data_classifications)),
            "semantic_distance":        {"average": round(sum(d)/len(d), 3) if d else 0.0,
                                         "max": round(max(d), 3) if d else 0.0,
                                         "history": d},
            "scope_expansion_detected": any(self._scope_expansions),
        }

    def summary(self) -> dict:
        return {
            "session_id":      self._context.session_id,
            "user_intent":     self._context.user_intent,
            "action_count":    len(self.recent_actions(n=9999)),
            "recent_actions":  self.recent_actions(n=5),
            "receipt_count":   len(self._receipts),
            "derived_signals": self.derived_signals(),
        }
