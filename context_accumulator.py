"""
AARM Context Accumulator

セッション内のアクション履歴、ユーザーの意図、ツール出力を追記専用のログとして蓄積する。
AARM 仕様の "accumulates context" 要件に対応。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import Action, AuthorizationResult, SessionContext


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

    # ------------------------------------------------------------------
    # 書き込み操作 (追記専用)
    # ------------------------------------------------------------------

    def record_action(self, action: Action) -> None:
        """アクションを履歴に追記する。"""
        self._context.append_action(action)

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

    def summary(self) -> dict:
        """現在のコンテキストのサマリを返す (Policy Engine への入力用)。"""
        return {
            "session_id":     self._context.session_id,
            "user_intent":    self._context.user_intent,
            "action_count":   len(self.recent_actions(n=9999)),
            "recent_actions": self.recent_actions(n=5),
            "receipt_count":  len(self._receipts),
        }
