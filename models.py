"""
AARM データモデルとコア定数

AARMの仕様に基づく型定義。
アクション、コンテキスト、認可結果など、システム全体で使う共通の型をここで定義する。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# 判断結果 (AARM 仕様 Section 4)
# ---------------------------------------------------------------------------

class Decision(str, Enum):
    """AARM が下す5種類の認可判断。"""
    ALLOW   = "ALLOW"    # 実行を許可
    DENY    = "DENY"     # 実行を拒否
    MODIFY  = "MODIFY"   # パラメータを修正したうえで許可
    DEFER   = "DEFER"    # 情報不足のため一時保留
    STEP_UP = "STEP_UP"  # 人間の承認を要求


# ---------------------------------------------------------------------------
# アクション
# ---------------------------------------------------------------------------

@dataclass
class Action:
    """
    エージェントがツールを呼び出す1回分の操作。

    Attributes:
        tool_name:   呼び出すツール名 (例: "write_file", "delete_record")
        parameters:  ツールに渡すパラメータ
        action_id:   自動生成される一意ID
        timestamp:   生成日時 (UTC)
    """
    tool_name:  str
    parameters: dict[str, Any]
    action_id:  str      = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:  datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "action_id":  self.action_id,
            "tool_name":  self.tool_name,
            "parameters": self.parameters,
            "timestamp":  self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# セッションコンテキスト
# ---------------------------------------------------------------------------

@dataclass
class SessionContext:
    """
    セッション全体で蓄積されるコンテキスト情報。
    Context Accumulator が管理し、Policy Engine / Intent Alignment が参照する。

    Attributes:
        session_id:      セッションの一意ID
        user_intent:     ユーザーが最初に伝えた目的・リクエスト
        action_history:  このセッションで実行・評価されたアクションの履歴 (追記専用)
        metadata:        任意の付加情報
    """
    user_intent:    str
    session_id:     str             = field(default_factory=lambda: str(uuid.uuid4()))
    action_history: list[dict]      = field(default_factory=list)
    metadata:       dict[str, Any]  = field(default_factory=dict)
    created_at:     datetime        = field(default_factory=lambda: datetime.now(timezone.utc))

    def append_action(self, action: Action) -> None:
        """アクションを履歴に追記する (削除・上書き不可)。"""
        self.action_history.append(action.to_dict())


# ---------------------------------------------------------------------------
# 認可結果
# ---------------------------------------------------------------------------

@dataclass
class AuthorizationResult:
    """
    AARM が1つのアクションに対して下した認可判断とその根拠。

    Attributes:
        decision:          5種類の判断結果
        reason:            判断理由 (監査ログ・デバッグ用)
        action:            評価対象のアクション
        receipt_id:        改ざん検知用の一意ID
        receipt_hash:      action + decision + reason の SHA-256 ハッシュ
        modified_params:   decision == MODIFY の場合に使う修正後パラメータ
        timestamp:         判断日時 (UTC)
    """
    decision:        Decision
    reason:          str
    action:          Action
    receipt_id:      str             = field(default_factory=lambda: str(uuid.uuid4()))
    modified_params: dict | None     = None
    timestamp:       datetime        = field(default_factory=lambda: datetime.now(timezone.utc))
    receipt_hash:    str             = field(init=False)

    def __post_init__(self) -> None:
        self.receipt_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """receipt の内容から SHA-256 を計算する。"""
        payload = json.dumps(
            {
                "receipt_id": self.receipt_id,
                "action":     self.action.to_dict(),
                "decision":   self.decision.value,
                "reason":     self.reason,
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "receipt_id":      self.receipt_id,
            "receipt_hash":    self.receipt_hash,
            "decision":        self.decision.value,
            "reason":          self.reason,
            "action":          self.action.to_dict(),
            "modified_params": self.modified_params,
            "timestamp":       self.timestamp.isoformat(),
        }
