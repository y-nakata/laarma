"""
AARM Context Accumulator

セッション内のアクション履歴、ユーザーの意図、ツール出力を追記専用のログとして蓄積する。
AARM 仕様の "accumulates context" 要件に対応。

仕様 IV-C に従い、アクションとツール出力だけでなく以下の派生シグナルも蓄積する:
  - data_classification : アクセスしたデータの機密レベル
  - semantic_distance   : 元の意図からのドリフト度 (0.0〜1.0)
  - scope_expansion     : 想定スコープ外リソースへのアクセスが発生したか

これらは Policy Engine / Intent Alignment が (a, C) のタプルで評価するために使う。
Imutable Log (レシート) は判断結果の事後 forensic 用であり、別物。
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from .models import Action, AuthorizationResult, SessionContext

# ---------------------------------------------------------------------------
# データ分類キーワード (簡易ヒューリスティック)
# ---------------------------------------------------------------------------

_PII_KEYWORDS       = {"email", "password", "phone", "address", "ssn", "credit", "customer", "personal"}
_CONFIDENTIAL_KEYS  = {"secret", "token", "key", "credential", "private", "internal", "config"}
_SENSITIVE_TOOLS    = {"database", "db", "read_file", "execute_shell", "execute_sql"}

# セマンティック距離の簡易近似: 元の意図のトークン集合と現アクション名の重複率で計算
def _compute_semantic_distance(user_intent: str, tool_name: str, parameters: dict) -> float:
    """0.0 (完全一致) 〜 1.0 (完全乖離) のスコアを返す簡易実装。"""
    intent_tokens = set(user_intent.lower().split())
    action_tokens = set(tool_name.lower().replace("_", " ").split())
    for v in parameters.values():
        action_tokens.update(str(v).lower().split())
    if not intent_tokens:
        return 1.0
    overlap = len(intent_tokens & action_tokens)
    # Jaccard 距離
    union = len(intent_tokens | action_tokens)
    return round(1.0 - overlap / union, 3) if union else 0.0


def _classify_data(tool_name: str, parameters: dict) -> list[str]:
    """アクションのツール名・パラメータから機密レベルを推定する。"""
    labels: list[str] = []
    combined = (tool_name + " " + " ".join(str(v) for v in parameters.values())).lower()
    if any(k in combined for k in _PII_KEYWORDS):
        labels.append("PII")
    if any(k in combined for k in _CONFIDENTIAL_KEYS):
        labels.append("CONFIDENTIAL")
    if tool_name in _SENSITIVE_TOOLS:
        labels.append("SENSITIVE_TOOL")
    return labels or ["PUBLIC"]


def _detect_scope_expansion(user_intent: str, tool_name: str, parameters: dict) -> bool:
    """意図に含まれないリソースへアクセスしていないか簡易チェック。"""
    intent_lower = user_intent.lower()
    # 外部送信ツールを使いつつ意図に外部送信の言及がない場合はスコープ拡張とみなす
    external_tools = {"send_email", "http_request", "webhook", "slack_message"}
    if tool_name in external_tools and "send" not in intent_lower and "email" not in intent_lower:
        return True
    return False


class ContextAccumulator:
    """
    セッション全体のコンテキストを蓄積するコンポーネント。

    追記専用の設計により、一度記録されたアクションや判断結果は変更できない。
    Policy Engine と Intent Alignment はこのクラスからコンテキストを取得する。
    """

    def __init__(self, user_intent: str, metadata: dict[str, Any] | None = None) -> None:
        """
        Args:
            user_intent: ユーザーがセッション開始時に伝えた目的・リクエスト
            metadata:    任意の付加情報 (ユーザーID、環境名など)
        """
        self._context = SessionContext(
            user_intent=user_intent,
            metadata=metadata or {},
        )
        self._receipts: list[dict] = []  # 認可結果の改ざん防止ログ

        # 仕様 IV-C の派生シグナル (蓄積)
        self._data_classifications: list[str] = []
        self._semantic_distances:   list[float] = []
        self._scope_expansions:     list[bool] = []

    # ------------------------------------------------------------------
    # 書き込み操作 (追記専用)
    # ------------------------------------------------------------------

    def record_action(self, action: Action) -> None:
        """アクションを履歴に追記し、派生シグナルを計算・蓄積する。"""
        self._context.append_action(action)

        # 派生シグナルを計算して蓄積
        labels = _classify_data(action.tool_name, action.parameters)
        self._data_classifications.extend(labels)

        dist = _compute_semantic_distance(
            self._context.user_intent, action.tool_name, action.parameters
        )
        self._semantic_distances.append(dist)

        expanded = _detect_scope_expansion(
            self._context.user_intent, action.tool_name, action.parameters
        )
        self._scope_expansions.append(expanded)

    def record_result(self, result: AuthorizationResult) -> None:
        """認可結果をレシートログに追記する。"""
        self._receipts.append(result.to_dict())

    def record_tool_output(self, action_id: str, output: Any) -> None:
        """
        ツール実行後の出力を記録する。
        悪意あるツール応答の検知に使う。
        """
        self._context.action_history.append({
            "type":      "tool_output",
            "action_id": action_id,
            "output":    str(output),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    # ------------------------------------------------------------------
    # 読み出し操作
    # ------------------------------------------------------------------

    @property
    def context(self) -> SessionContext:
        """現在のセッションコンテキストを返す。"""
        return self._context

    @property
    def receipts(self) -> list[dict]:
        """蓄積された認可結果のレシート一覧を返す (コピー)。"""
        return list(self._receipts)

    def recent_actions(self, n: int = 5) -> list[dict]:
        """直近 n 件のアクション履歴を返す (新しい順)。"""
        actions = [
            e for e in self._context.action_history
            if e.get("type") != "tool_output"
        ]
        return list(reversed(actions[-n:]))

    def derived_signals(self) -> dict:
        """仕様 IV-C の派生シグナルをまとめて返す。Intent Alignment への入力用。"""
        distances = self._semantic_distances
        avg_distance = round(sum(distances) / len(distances), 3) if distances else 0.0
        max_distance = max(distances) if distances else 0.0
        return {
            "data_classifications": sorted(set(self._data_classifications)),
            "semantic_distance": {
                "average": avg_distance,
                "max":     round(max_distance, 3),
                "history": distances,
            },
            "scope_expansion_detected": any(self._scope_expansions),
        }

    def summary(self) -> dict:
        """現在のコンテキストのサマリを返す (Intent Alignment / デモ表示用)。"""
        return {
            "session_id":      self._context.session_id,
            "user_intent":     self._context.user_intent,
            "action_count":    len(self.recent_actions(n=9999)),
            "recent_actions":  self.recent_actions(n=5),
            "receipt_count":   len(self._receipts),
            "derived_signals": self.derived_signals(),
        }
