"""
AARM データモデルとコア定数 — 仕様 IV-A2, IV-A3
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
import warnings
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class Decision(str, Enum):
    ALLOW   = "ALLOW"
    DENY    = "DENY"
    MODIFY  = "MODIFY"
    DEFER   = "DEFER"
    STEP_UP = "STEP_UP"


@dataclass
class IdentityContext:
    """R6: アクションを実行するアイデンティティの多層表現。"""
    human_principal:  str
    service_identity: str
    session_id:       str
    privilege_scope:  list[str] = field(default_factory=list)
    identity_token:   str | None = field(default=None)

    def _compute_token(self, secret: str) -> str:
        payload = json.dumps(
            {
                "human_principal":  self.human_principal,
                "service_identity": self.service_identity,
                "session_id":       self.session_id,
                "privilege_scope":  sorted(self.privilege_scope),
            },
            sort_keys=True, ensure_ascii=False,
        ).encode()
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    def sign(self, secret: str) -> "IdentityContext":
        """HMAC で署名した新しい IdentityContext を返す（元インスタンスは変更しない）。"""
        return replace(self, identity_token=self._compute_token(secret))

    def verify(self, secret: str) -> bool:
        """identity_token が正しい HMAC か検証する。"""
        if self.identity_token is None:
            return False
        return hmac.compare_digest(self.identity_token, self._compute_token(secret))

    def to_dict(self) -> dict:
        d = {
            "human_principal":  self.human_principal,
            "service_identity": self.service_identity,
            "session_id":       self.session_id,
            "privilege_scope":  self.privilege_scope,
        }
        if self.identity_token:
            d["identity_token"] = self.identity_token
        return d


@dataclass
class Action:
    """a = (t, op, p, id, ctx, ts) — 仕様 IV-A3。"""
    tool_name:   str
    parameters:  dict[str, Any]
    identity:    IdentityContext | None = None
    action_id:   str      = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "action_id":  self.action_id,
            "tool_name":  self.tool_name,
            "parameters": self.parameters,
            "identity":   self.identity.to_dict() if self.identity else None,
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
    # ポリシー参照 — 仕様 R5: "receipt must include the policy context used in evaluation"
    policy_rule_id:        str | None      = None   # 発火した StaticRule.id (PolicyEngine のみ)
    decision_source:       str             = "intent_alignment"  # "policy_engine" | "denied_tools" | "privilege_scope" | "intent_alignment"
    # DEFER ワークフロー用フィールド
    deferral_reason:       str | None      = None
    resolution_method:     str | None      = None  # "autonomous" | "human_approved" | "human_denied" | None
    resolution_timestamp:  datetime | None = None
    # 提案/上書きモデル用フィールド — PolicyEngine の提案が IntentAlignment に上書きされた際に記録
    proposed_decision:     str | None      = None  # PolicyEngine が提案した decision 値
    receipt_hash:          str             = field(init=False)

    def __post_init__(self) -> None:
        self.receipt_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        payload = json.dumps(
            {
                "receipt_id":         self.receipt_id,
                "action":             self.action.to_dict(),
                "decision":           self.decision.value,
                "reason":             self.reason,
                "modified_params":    self.modified_params,
                "decision_source":    self.decision_source,
                "policy_rule_id":     self.policy_rule_id,
                "deferral_reason":    self.deferral_reason,
                "proposed_decision":  self.proposed_decision,
                "resolution_method":  self.resolution_method,
                "resolution_timestamp": (
                    self.resolution_timestamp.isoformat()
                    if self.resolution_timestamp else None
                ),
            },
            sort_keys=True, ensure_ascii=False,
        ).encode()
        secret = os.getenv("AARM_HMAC_SECRET")
        if secret:
            return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        warnings.warn(
            "AARM_HMAC_SECRET が未設定です。receipt_hash は改ざん検知に使用できません。",
            stacklevel=3,
        )
        return hashlib.sha256(payload).hexdigest()

    def to_dict(self) -> dict:
        d = {
            "receipt_id":           self.receipt_id,
            "receipt_hash":         self.receipt_hash,
            "decision":             self.decision.value,
            "reason":               self.reason,
            "action":               self.action.to_dict(),
            "modified_params":      self.modified_params,
            "timestamp":            self.timestamp.isoformat(),
            "decision_source":      self.decision_source,
        }
        if self.policy_rule_id:
            d["policy_rule_id"] = self.policy_rule_id
        if self.proposed_decision:
            d["proposed_decision"] = self.proposed_decision
        if self.deferral_reason:
            d["deferral_reason"]      = self.deferral_reason
        if self.resolution_method:
            d["resolution_method"]    = self.resolution_method
        if self.resolution_timestamp:
            d["resolution_timestamp"] = self.resolution_timestamp.isoformat()
        return d
