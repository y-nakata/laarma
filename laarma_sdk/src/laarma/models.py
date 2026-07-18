"""
AARM データモデルとコア定数 — 仕様 IV-A2, IV-A3
"""

from __future__ import annotations

import json
import uuid
import warnings
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

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

    委任の連鎖における3つの主体（依頼者 Human / 実行者 Agent / 調停者 Service）が、
    それぞれ自分の Ed25519 秘密鍵で署名する。Human は human_principal と session_id を、
    Agent は agent_identity と session_id を、それぞれ自分の層として個別署名する
    （session_id を含めることで、署名を別セッションへ使い回すリプレイ攻撃を防ぐ）。
    Service は human_principal / agent_identity / service_identity / privilege_scope /
    session_id を束ねた包括署名で「これらが一つのアクションのために結合された」ことを保証する
    （Service 自身の個別署名は包括署名に内包されるため別途持たない）。

    laarma SDK は秘密鍵を生成・保管しない（検証者であって発行者ではない）。署名は鍵を持つ
    呼び出し側（``sign_human`` / ``sign_agent`` / ``sign_service``）が行い、SDK は対応する
    公開鍵での検証（``verify_human`` / ``verify_agent`` / ``verify_service``）のみを提供する。

    設計の詳細は docs/design/identity-signing.md §3〜§4 を参照。
    """
    human_principal:   str
    agent_identity:    str
    service_identity:  str
    session_id:        str
    privilege_scope:   list[str] = field(default_factory=list)
    human_signature:   str | None = field(default=None)
    agent_signature:   str | None = field(default=None)
    service_signature: str | None = field(default=None)

    def _human_payload(self) -> bytes:
        return json.dumps(
            {"human_principal": self.human_principal, "session_id": self.session_id},
            sort_keys=True, ensure_ascii=False,
        ).encode()

    def _agent_payload(self) -> bytes:
        return json.dumps(
            {"agent_identity": self.agent_identity, "session_id": self.session_id},
            sort_keys=True, ensure_ascii=False,
        ).encode()

    def _service_payload(self) -> bytes:
        # 包括署名: 個別署名の対象に service_identity と privilege_scope を加えて束ねる。
        # action_id は含めない（「どの主体が」は identity 署名、「どのアクションを」は
        # receipt の封緘が担保する別レイヤー。docs/design/identity-signing.md §3）。
        return json.dumps(
            {
                "human_principal":  self.human_principal,
                "agent_identity":   self.agent_identity,
                "service_identity": self.service_identity,
                "privilege_scope":  sorted(self.privilege_scope),
                "session_id":       self.session_id,
            },
            sort_keys=True, ensure_ascii=False,
        ).encode()

    def sign_human(self, private_key: Ed25519PrivateKey) -> "IdentityContext":
        """human_principal の秘密鍵で個別署名した新しい IdentityContext を返す。"""
        return replace(self, human_signature=private_key.sign(self._human_payload()).hex())

    def sign_agent(self, private_key: Ed25519PrivateKey) -> "IdentityContext":
        """agent_identity の秘密鍵で個別署名した新しい IdentityContext を返す。"""
        return replace(self, agent_signature=private_key.sign(self._agent_payload()).hex())

    def sign_service(self, private_key: Ed25519PrivateKey) -> "IdentityContext":
        """service_identity の秘密鍵で包括署名した新しい IdentityContext を返す。"""
        return replace(self, service_signature=private_key.sign(self._service_payload()).hex())

    def verify_human(self, public_key: Ed25519PublicKey) -> bool:
        if self.human_signature is None:
            return False
        try:
            public_key.verify(bytes.fromhex(self.human_signature), self._human_payload())
            return True
        except InvalidSignature:
            return False

    def verify_agent(self, public_key: Ed25519PublicKey) -> bool:
        if self.agent_signature is None:
            return False
        try:
            public_key.verify(bytes.fromhex(self.agent_signature), self._agent_payload())
            return True
        except InvalidSignature:
            return False

    def verify_service(self, public_key: Ed25519PublicKey) -> bool:
        if self.service_signature is None:
            return False
        try:
            public_key.verify(bytes.fromhex(self.service_signature), self._service_payload())
            return True
        except InvalidSignature:
            return False

    def to_dict(self) -> dict:
        d = {
            "human_principal":  self.human_principal,
            "agent_identity":   self.agent_identity,
            "service_identity": self.service_identity,
            "session_id":       self.session_id,
            "privilege_scope":  self.privilege_scope,
        }
        if self.human_signature:
            d["human_signature"] = self.human_signature
        if self.agent_signature:
            d["agent_signature"] = self.agent_signature
        if self.service_signature:
            d["service_signature"] = self.service_signature
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
    decision_source:       str             = "policy_engine"  # "policy_engine" | "denied_tools" | "privilege_scope" | "baseline_allow" | "deferral_resolver" | "step_up_resolver"
    # #112 Phase C: confidence 計算への LLM 検出層による減点幅・検出理由。decision には
    # 関与しない（decision を出すのはポリシーの confidence 閾値ルール）が、どの decision が
    # 決定論由来でどれが confidence 経由（LLM 検出含む）で下されたかを切り分けられるよう
    # 受領書に記録する（設計メモ §5）。penalty=0.0 は「LLM 層は呼ばれたが検出なし」、
    # None は「LLM 層自体が呼ばれていない」を表す。
    confidence_llm_penalty: float | None    = None
    confidence_llm_detail:  str | None      = None
    # DEFER ワークフロー用フィールド
    deferral_reason:       str | None      = None
    resolution_method:     str | None      = None  # "autonomous" | "step_up" | "human_approved" | "human_denied" | None
    resolution_timestamp:  datetime | None = None
    # 同一 priority 競合(R3(b))の DEFER でのみ設定 — 競合した decision 値の集合（comma-joined）
    proposed_decision:     str | None      = None
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
            "confidence_llm_penalty": self.confidence_llm_penalty,
            "confidence_llm_detail":  self.confidence_llm_detail,
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
        if self.confidence_llm_penalty is not None:
            d["confidence_llm_penalty"] = self.confidence_llm_penalty
        if self.confidence_llm_detail:
            d["confidence_llm_detail"] = self.confidence_llm_detail
        if self.proposed_decision:
            d["proposed_decision"] = self.proposed_decision
        if self.deferral_reason:
            d["deferral_reason"]      = self.deferral_reason
        if self.resolution_method:
            d["resolution_method"]    = self.resolution_method
        if self.resolution_timestamp:
            d["resolution_timestamp"] = self.resolution_timestamp.isoformat()
        return d
