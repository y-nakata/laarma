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

_DEFAULT_PII_KEYWORDS      = frozenset({"email", "password", "phone", "address", "ssn", "credit", "customer", "personal", "name", "info"})
_DEFAULT_CONFIDENTIAL_KEYS = frozenset({"secret", "token", "key", "credential", "private", "internal", "config"})
_DEFAULT_SENSITIVE_TOOLS   = frozenset({"database", "db", "execute_shell", "execute_sql"})
_DEFAULT_DESTRUCTIVE_TOOLS = frozenset({"delete_file", "drop_database", "delete_all_records", "execute_shell"})
_DEFAULT_EXTERNAL_TOOLS    = frozenset({"send_email", "http_request", "webhook", "slack_message"})


def _classify_data(
    tool_name: str,
    parameters: dict,
    pii_keywords: frozenset[str],
    confidential_keywords: frozenset[str],
    sensitive_tools: frozenset[str],
) -> list[str]:
    combined = (tool_name + " " + " ".join(str(v) for v in parameters.values())).lower()
    labels = []
    if any(k in combined for k in pii_keywords):         labels.append("PII")
    if any(k in combined for k in confidential_keywords): labels.append("CONFIDENTIAL")
    if tool_name in sensitive_tools:                      labels.append("SENSITIVE_TOOL")
    return labels or ["PUBLIC"]


def _detect_scope_expansion(user_intent: str, tool_name: str, parameters: dict, external_tools: frozenset[str]) -> bool:
    return tool_name in external_tools and "send" not in user_intent.lower() and "email" not in user_intent.lower()


def _extract_entities(tool_name: str, parameters: dict) -> set[str]:
    """アクションから参照されたリソース名を抽出する。"""
    entities = set()
    for v in parameters.values():
        if isinstance(v, str) and v:
            entities.add(v)
    return entities


def _action_matches_intent(user_intent: str, tool_name: str, parameters: dict) -> bool:
    """ユーザーの要求がアクションのツール名や主要パラメータと明示的に一致するか判定する。"""
    text = user_intent.lower()
    if tool_name.lower().replace("_", " ") in text:
        return True
    for value in parameters.values():
        if isinstance(value, str) and value.lower() in text:
            return True
    return False


def _compute_confidence(
    semantic_distance: float,
    scope_expansion: bool,
    action_matches_intent: bool,
) -> float:
    """
    確信度を 0.0 (全く評価できない) 〜 1.0 (完全に評価できる) で算出する。
    AARM 仕様 §IV-C: confidence は「(a, C) を自信を持って評価できる度合い」であり、
    アクションの危険度ではない。危険度は data_classification シグナルを参照する
    ポリシー条件（STEP_UP / DENY）が担う。
    """
    score = 1.0

    # 意味的距離が高いほど評価が困難
    score -= semantic_distance * 0.3

    # スコープ拡張は想定外のコンテキストであり評価が困難
    if scope_expansion:
        score -= 0.25

    # 明示的な意図との一致があれば評価しやすい
    if action_matches_intent:
        score += 0.1

    return round(max(0.0, min(1.0, score)), 3)


class ContextAccumulator:
    def __init__(
        self,
        user_intent: str,
        metadata: dict[str, Any] | None = None,
        distance_calculator: DistanceCalculator | None = None,
        policy: Any | None = None,
    ) -> None:
        self._context = SessionContext(user_intent=user_intent, metadata=metadata or {})
        self._receipts: list[dict]  = []
        self._data_classifications: list[str]   = []
        self._semantic_distances:   list[float] = []
        self._scope_expansions:     list[bool]  = []
        self._entity_set:           set[str]    = set()
        self._confidence_history:   list[float] = []
        self._action_matches_intent: list[bool] = []
        self._distance_calculator = distance_calculator or create_default_distance_calculator()
        self._pii_keywords         = (policy.pii_keywords          if policy and policy.pii_keywords          is not None else _DEFAULT_PII_KEYWORDS)
        self._confidential_keywords = (policy.confidential_keywords if policy and policy.confidential_keywords is not None else _DEFAULT_CONFIDENTIAL_KEYS)
        self._sensitive_tools      = (policy.sensitive_tools        if policy and policy.sensitive_tools       is not None else _DEFAULT_SENSITIVE_TOOLS)
        self._destructive_tools    = (policy.destructive_tools      if policy and policy.destructive_tools     is not None else _DEFAULT_DESTRUCTIVE_TOOLS)
        self._external_tools       = (policy.external_tools         if policy and policy.external_tools        is not None else _DEFAULT_EXTERNAL_TOOLS)

    def record_action(self, action: Action) -> None:
        self._context.append_action(action)

        classifications = _classify_data(
            action.tool_name, action.parameters,
            self._pii_keywords, self._confidential_keywords, self._sensitive_tools,
        )
        self._data_classifications.extend(classifications)

        dist = self._distance_calculator.compute(
            self._context.user_intent, action.tool_name, action.parameters)
        self._semantic_distances.append(dist)

        expanded = _detect_scope_expansion(
            self._context.user_intent, action.tool_name, action.parameters, self._external_tools)
        self._scope_expansions.append(expanded)

        self._entity_set.update(_extract_entities(action.tool_name, action.parameters))

        matches_intent = _action_matches_intent(
            self._context.user_intent, action.tool_name, action.parameters)

        confidence = _compute_confidence(
            semantic_distance=dist,
            scope_expansion=expanded,
            action_matches_intent=matches_intent,
        )
        self._confidence_history.append(confidence)

        self._action_matches_intent.append(matches_intent)

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

    _DRIFT_WINDOW = 5

    def derived_signals(self) -> dict:
        d = self._semantic_distances
        c = self._confidence_history
        current_confidence = c[-1] if c else 1.0
        m = self._action_matches_intent
        window = d[-self._DRIFT_WINDOW:]
        recent_avg  = round(sum(window) / len(window), 3) if window else 0.0
        avg         = sum(d) / len(d) if d else 0.0
        drift_trend = round(d[-1] - avg, 3) if d else 0.0
        return {
            "data_classifications":     sorted(set(self._data_classifications)),
            "semantic_distance":        {
                "current":    d[-1] if d else 0.0,
                "average":    round(avg, 3) if d else 0.0,
                "max":        round(max(d), 3) if d else 0.0,
                "history":    d,
                "recent_avg": recent_avg,   # 直近 DRIFT_WINDOW アクションの平均
                "drift_trend": drift_trend, # current - average（正=平均より遠ざかっている）
            },
            "scope_expansion_detected": any(self._scope_expansions),
            "scope_expansion_recent":   any(self._scope_expansions[-self._DRIFT_WINDOW:]),
            "action_matches_intent":     m[-1] if m else False,
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
