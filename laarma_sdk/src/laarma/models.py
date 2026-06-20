"""
AARM データモデルとコア定数 — 仕様 IV-A2, IV-A3
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
import warnings
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .audit import compute_receipt_hash


class Decision(str, Enum):
    ALLOW   = "ALLOW"
    DENY    = "DENY"
    MODIFY  = "MODIFY"
    DEFER   = "DEFER"
    STEP_UP = "STEP_UP"


@dataclass
class IdentityContext:
    """
    R6: アクションを実行するアイデンティティの多層表現。

    現在の ``identity_token`` は、4層（human_principal / service_identity /
    session_id / privilege_scope）全体を ``AARM_IDENTITY_SECRET``（システム共有鍵）で
    一括計算した HMAC-SHA256 による **attestation（システム証明）** である。

    HMAC は対称鍵であるため署名者と検証者が同じ鍵を共有し、「alice が依頼した」という
    non-repudiation（否認防止）は成立しない（R6 MUST 要件を満たさない）。
    解消は Issue #55 後続ステップ（PR-2 以降で ``sign`` の中身を Ed25519 に置き換える）で行う。
    """
    human_principal:  str
    service_identity: str
    session_id:       str
    privilege_scope:  list[str] = field(default_factory=list)
    identity_token:   str | None = field(default=None)

    def _compute_token(self, secret: str) -> str:
        # 4層を 1 つの HMAC-SHA256 で一括計算するシステム attestation。
        # 各主体（human / agent）による個別署名ではない（Issue #55 参照）。
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
        """
        identity_token を付与した新しい IdentityContext を返す（元インスタンスは変更しない）。

        メソッド名 ``sign`` は「主体が署名する」を示唆するが、現実装は
        ``AARM_IDENTITY_SECRET`` を持つ **システム（サービス）が全体に付与する attestation** である。
        引数 ``secret`` はシステムの共有鍵（``AARM_IDENTITY_SECRET``）であり、
        human_principal（alice 等）の秘密鍵ではない。
        """
        return replace(self, identity_token=self._compute_token(secret))

    def verify(self, secret: str) -> bool:
        """
        identity_token がシステム attestation として正しい HMAC か検証する。

        同じシステム共有鍵（``secret``）で HMAC を再計算し一致を確認する。
        「誰が署名したか」を区別する non-repudiation 検証ではない。
        """
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
    resolution_method:     str | None      = None  # "autonomous" | "step_up" | "human_approved" | "human_denied" | None
    resolution_timestamp:  datetime | None = None
    # 提案/上書きモデル用フィールド — PolicyEngine の提案が IntentAlignment に上書きされた際に記録
    proposed_decision:     str | None      = None  # PolicyEngine が提案した decision 値
    _receipt_hash:         str | None      = field(default=None, init=False, repr=False)
    _sealed:                bool           = field(default=False, init=False, repr=False)

    @property
    def receipt_hash(self) -> str:
        if not self._sealed:
            raise RuntimeError(
                "AuthorizationResult is not sealed yet. Call seal(secret) before "
                "reading receipt_hash."
            )
        return self._receipt_hash

    def seal(self, secret: str | None) -> None:
        """
        receipt_hash を計算して確定する。鍵を知るのは呼び出し側（runtime）だけに
        閉じる。判断層（policy_engine / deferral / step_up_resolver）は鍵を知らずに
        AuthorizationResult を生成し、runtime が結果を受け取った直後に封緘する。
        """
        if self._sealed:
            raise RuntimeError("AuthorizationResult is already sealed.")
        payload_fields = {
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
        }
        if not secret:
            warnings.warn(
                "AARM_RECEIPT_SECRET が未設定です。receipt_hash は改ざん検知に使用できません。",
                stacklevel=3,
            )
        self._receipt_hash = compute_receipt_hash(payload_fields, secret)
        self._sealed = True

    def to_dict(self) -> dict:
        if not self._sealed:
            raise RuntimeError(
                "AuthorizationResult is not sealed yet. Call seal(secret) before "
                "calling to_dict()."
            )
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
