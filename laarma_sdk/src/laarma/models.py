"""
AARM データモデルとコア定数 — 仕様 IV-A2, IV-A3
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Decision(str, Enum):
    ALLOW   = "ALLOW"
    DENY    = "DENY"
    MODIFY  = "MODIFY"
    DEFER   = "DEFER"
    STEP_UP = "STEP_UP"


class ToolRiskClass(str, Enum):
    """
    ツールのリスク分類。SDK 利用者（ツール実装者）が各ツールに宣言する。

    SDK はツール名を知らず、この分類だけを見て評価戦略を変える:
      READ_ONLY   : 情報取得のみ。状態を変更しない（read_file, list_files など）
      WRITE       : 状態を変更するが可逆・限定的（write_file など）
      DESTRUCTIVE : 不可逆な破壊操作（delete_file, drop_database など）

    未宣言の場合は WRITE 相当（安全側）として扱う。
    """
    READ_ONLY   = "READ_ONLY"
    WRITE       = "WRITE"
    DESTRUCTIVE = "DESTRUCTIVE"


@dataclass
class IdentityContext:
    """R6: アクションを実行するアイデンティティの多層表現。"""
    human_principal:  str
    service_identity: str
    session_id:       str
    privilege_scope:  list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "human_principal":  self.human_principal,
            "service_identity": self.service_identity,
            "session_id":       self.session_id,
            "privilege_scope":  self.privilege_scope,
        }


@dataclass
class Action:
    """a = (t, op, p, id, ctx, ts) — 仕様 IV-A3。"""
    tool_name:   str
    parameters:  dict[str, Any]
    identity:    IdentityContext | None = None
    risk_class:  ToolRiskClass = ToolRiskClass.WRITE
    action_id:   str      = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "action_id":  self.action_id,
            "tool_name":  self.tool_name,
            "parameters": self.parameters,
            "identity":   self.identity.to_dict() if self.identity else None,
            "risk_class": self.risk_class.value,
            "timestamp":  self.timestamp.isoformat(),
        }


@dataclass
class SessionContext:
    user_intent:    str
    session_id:     str             = field(default_factory=lambda: str(uuid.uuid4()))
    action_history: list[dict]      = field(default_factory=list)
    metadata:       dict[str, Any]  = field(default_factory=dict)
    created_at:     datetime        = field(default_factory=lambda: datetime.now(timezone.utc))

    def append_action(self, action: Action) -> None:
        self.action_history.append(action.to_dict())


@dataclass
class AuthorizationResult:
    """
    AARM 認可判断結果。

    DEFER の場合は deferral_reason を記録し、
    解決後に resolution_method と resolution_timestamp を添付する。
    仕様の Receipt Schema に対応。
    """
    decision:              Decision
    reason:                str
    action:                Action
    receipt_id:            str             = field(default_factory=lambda: str(uuid.uuid4()))
    modified_params:       dict | None     = None
    timestamp:             datetime        = field(default_factory=lambda: datetime.now(timezone.utc))
    # DEFER ワークフロー用フィールド
    deferral_reason:       str | None      = None
    resolution_method:     str | None      = None  # "autonomous" | "step_up" | None
    resolution_timestamp:  datetime | None = None
    receipt_hash:          str             = field(init=False)

    def __post_init__(self) -> None:
        self.receipt_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = json.dumps(
            {"receipt_id": self.receipt_id, "action": self.action.to_dict(),
             "decision": self.decision.value, "reason": self.reason},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> dict:
        d = {
            "receipt_id":           self.receipt_id,
            "receipt_hash":         self.receipt_hash,
            "decision":             self.decision.value,
            "reason":               self.reason,
            "action":               self.action.to_dict(),
            "modified_params":      self.modified_params,
            "timestamp":            self.timestamp.isoformat(),
        }
        if self.deferral_reason:
            d["deferral_reason"]      = self.deferral_reason
        if self.resolution_method:
            d["resolution_method"]    = self.resolution_method
        if self.resolution_timestamp:
            d["resolution_timestamp"] = self.resolution_timestamp.isoformat()
        return d
