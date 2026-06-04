"""
AARM Context Accumulator — R2
Cn = Cn-1 ∪ {an, on, δn} — 仕様 IV-C

派生シグナル δ に仕様の全項目を実装:
  - data_classification    : アクセスしたデータの機密レベル
  - semantic_distance      : 元の意図からのドリフト度
  - scope_expansion        : 想定スコープ外へのアクセス
  - entity_set             : セッション中に参照されたリソース
  - confidence_level       : 現在のアクション評価の確信度（DEFER 判断の主要トリガー）
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .distance_calculator import DistanceCalculator, create_default_distance_calculator
from .models import Action, AuthorizationResult, SessionContext

_PII_KEYWORDS      = {"email", "password", "phone", "address", "ssn", "credit", "customer", "personal", "name", "info"}
_CONFIDENTIAL_KEYS = {"secret", "token", "key", "credential", "private", "internal", "config"}
_SENSITIVE_TOOLS   = {"database", "db", "execute_shell", "execute_sql"}
_DESTRUCTIVE_TOOLS = {"delete_file", "drop_database", "delete_all_records", "execute_shell"}


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


def _extract_entities(tool_name: str, parameters: dict) -> set[str]:
    """アクションから参照されたリソース名を抽出する。"""
    entities = set()
    for v in parameters.values():
        if isinstance(v, str) and v:
            entities.add(v)
    return entities


def _compute_confidence(
    semantic_distance: float,
    data_classifications: list[str],
    scope_expansion: bool,
    action_count: int,
    is_destructive: bool,
) -> float:
    """
    確信度を 0.0 (全く評価できない) 〜 1.0 (完全に評価できる) で算出する。
    0.4 未満 → DEFER のトリガーになる。
    """
    score = 1.0

    # 意味的距離が高いはど不確か
    score -= semantic_distance * 0.3

    # PII/CONFIDENTIAL が混在すると確信度低下
    if "PII" in data_classifications:
        score -= 0.15
    if "CONFIDENTIAL" in data_classifications:
        score -= 0.15

    # スコープ拡張は確信度を大きく下げる
    if scope_expansion:
        score -= 0.25

    # 破壊的操作は確信度を下げる
    if is_destructive:
        score -= 0.1

    # 初回アクションはコンテキストが少ないので評価下げ
    if action_count == 0:
        score -= 0.1

    return round(max(0.0, min(1.0, score)), 3)


class ContextAccumulator:
    def __init__(
        self,
        user_intent: str,
        metadata: dict[str, Any] | None = None,
        distance_calculator: DistanceCalculator | None = None,
    ) -> None:
        self._context = SessionContext(user_intent=user_intent, metadata=metadata or {})
        self._receipts: list[dict]  = []
        self._data_classifications: list[str]   = []
        self._semantic_distances:   list[float] = []
        self._scope_expansions:     list[bool]  = []
        self._entity_set:           set[str]    = set()
        self._confidence_history:   list[float] = []
        self._distance_calculator = distance_calculator or create_default_distance_calculator()

    def record_action(self, action: Action) -> None:
        self._context.append_action(action)

        classifications = _classify_data(action.tool_name, action.parameters)
        self._data_classifications.extend(classifications)

        dist = self._distance_calculator.compute(
            self._context.user_intent, action.tool_name, action.parameters)
        self._semantic_distances.append(dist)

        expanded = _detect_scope_expansion(
            self._context.user_intent, action.tool_name, action.parameters)
        self._scope_expansions.append(expanded)

        self._entity_set.update(_extract_entities(action.tool_name, action.parameters))

        confidence = _compute_confidence(
            semantic_distance=dist,
            data_classifications=classifications,
            scope_expansion=expanded,
            action_count=len(self._confidence_history),
            is_destructive=action.tool_name in _DESTRUCTIVE_TOOLS,
        )
        self._confidence_history.append(confidence)

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
        c = self._confidence_history
        current_confidence = c[-1] if c else 1.0
        return {
            "data_classifications":     sorted(set(self._data_classifications)),
            "semantic_distance":        {
                "current": d[-1] if d else 0.0,
                "average": round(sum(d)/len(d), 3) if d else 0.0,
                "max":     round(max(d), 3) if d else 0.0,
                "history": d,
            },
            "scope_expansion_detected": any(self._scope_expansions),
            "entity_set":               sorted(self._entity_set),
            "confidence_level":         current_confidence,
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
