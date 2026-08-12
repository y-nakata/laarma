"""
AARM Runtime — R1〜R6 統合
「インターセプト → コンテキスト蓄積 → ポリシー評価 (a, C, E) → 記録」
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

from .context_accumulator import ContextAccumulator
from .environment import EnvironmentContext
from .models import Action, AuthorizationResult, Decision, IdentityContext
from .policy_engine import DEFAULT_POLICY, Policy, PolicyEngine


def _load_ed25519_pubkey(pubkey_dir: str, principal: str) -> Ed25519PublicKey | None:
    """``pubkey_dir/{principal}.pub`` があれば読み込んで返す。無ければ None。"""
    path = Path(pubkey_dir) / f"{principal}.pub"
    if not path.is_file():
        return None
    key = load_pem_public_key(path.read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError(f"{path} は Ed25519 公開鍵ではありません。")
    return key


class AARMRuntime:
    def __init__(
        self,
        user_intent: str,
        identity: IdentityContext | None = None,
        environment: EnvironmentContext | None = None,
        policy: Policy | None = None,
        metadata: dict[str, Any] | None = None,
        transform_registry: "dict[str, Any] | None" = None,
        confidence_llm: Any | None = None,
        scope_expansion_llm: Any | None = None,
        action_matches_intent_llm: Any | None = None,
    ) -> None:
        self._identity    = identity
        self._environment = environment
        _policy           = policy or DEFAULT_POLICY
        self._accumulator = ContextAccumulator(
            user_intent=user_intent, metadata=metadata, policy=_policy, confidence_llm=confidence_llm,
            scope_expansion_llm=scope_expansion_llm, action_matches_intent_llm=action_matches_intent_llm)
        self._policy_engine = PolicyEngine(
            policy=_policy,
            transform_registry=transform_registry,
        )
        self._audit_log_path = os.getenv("AARM_AUDIT_LOG_PATH")
        self._receipt_secret = os.getenv("AARM_RECEIPT_SECRET")
        # R6 MUST: identity の cryptographic binding 検証（Human/Agent 個別署名 + Service 包括署名）。
        # AARM_IDENTITY_PUBKEY_DIR が未設定なら検証自体をスキップする（オプトイン、既存挙動を維持）。
        # 設定されている場合、検証に失敗したら identity.verification_error に理由を記録する。
        # PolicyEngine.evaluate() がこれを gate として参照し、privilege_scope と同じ fail-closed で
        # DENY にする（#55 PR-4。以前は warnings.warn() のみで処理を止めなかった）。
        _pubkey_dir = os.getenv("AARM_IDENTITY_PUBKEY_DIR")
        if _pubkey_dir and identity is not None:
            for label, principal, verify in (
                ("human",   identity.human_principal,  identity.verify_human),
                ("agent",   identity.agent_identity,    identity.verify_agent),
                ("service", identity.service_identity,  identity.verify_service),
            ):
                pubkey = _load_ed25519_pubkey(_pubkey_dir, principal)
                if pubkey is None:
                    identity.verification_error = (
                        f"IdentityContext の {label} 公開鍵が {_pubkey_dir} に見つかりません"
                        f"（{principal}.pub）。"
                    )
                    break
                elif not verify(pubkey):
                    identity.verification_error = (
                        f"IdentityContext の {label}_signature が未設定または不正です。"
                        f"identity.sign_{label}(private_key) で署名してから渡してください。"
                    )
                    break

    def intercept(self, tool_name: str, parameters: dict[str, Any]) -> AuthorizationResult:
        """
        アクションをインターセプトして認可判断を返す。

        Returns:
            AuthorizationResult。decision の値によって呼び出し側の責務が異なる:

            - ALLOW / MODIFY : ツールを実行してよい。
            - DENY           : ツールをブロックすること。
            - STEP_UP        : 人間の承認が必要。StepUpResolver を使うか DENY として扱う。
            - DEFER          : 追加コンテキストによる再評価が必要。
                AARMToolProxy を使っている場合は DeferralResolver が自動処理する。
                直接 AARMRuntime を使う場合は以下のパターンで手動ハンドリングすること::

                    from laarma.deferral import DeferralResolver
                    result = runtime.intercept(tool_name, params)
                    if result.decision == Decision.DEFER:
                        resolver = DeferralResolver()
                        resolved = resolver.resolve(result, runtime.context_summary)
                        runtime.record_deferred_resolution(resolved)
                        result = resolved
                    # result.decision は ALLOW / MODIFY / DENY / STEP_UP のいずれか
        """
        action = Action(
            tool_name=tool_name,
            parameters=parameters,
            identity=self._identity,
        )
        self._accumulator.record_action(action)
        result = self._policy_engine.evaluate(
            action,
            self._accumulator.context,
            self._accumulator.summary(),
            self._environment,
        )
        # DEFER を含む全判断をここで一元ログする。
        # tool_proxy.py 側で DEFER を別途 print しないこと（二重ログになる）。
        return self._finalize(result)

    def record_tool_output(self, action_id: str, output: Any) -> None:
        self._accumulator.record_tool_output(action_id, output)

    def record_deferred_resolution(self, resolved: AuthorizationResult) -> None:
        """認可結果に追記する (DEFER 解決後)。"""
        # DEFER 解決後の最終判断（ALLOW / DENY / STEP_UP）のみをログする。
        # DEFER 自体は intercept() が既にログ済み。
        self._finalize(resolved)

    def record_step_up_resolution(self, resolved: AuthorizationResult) -> None:
        """認可結果に追記する (STEP_UP 人間承認後)。"""
        # STEP_UP 自体は intercept() が既にログ済み。
        # ここでは人間承認後の最終判断（ALLOW / DENY）のみをログする。
        self._finalize(resolved)

    def _finalize(self, result: AuthorizationResult) -> AuthorizationResult:
        """receipt_hash を封緘してから記録・ログする単一経路。鍵を知るのはここだけ。"""
        # #112 Phase C: confidence LLM 検出層の減点幅・検出理由を受領書に写す。#99: scope_expansion
        # LLM 検出層の検出理由、#161: action_matches_intent LLM 検出層の検出理由も同様に写す。
        # DEFER/STEP_UP 解決後の呼び出しでも record_action() は再実行されないため、この時点の
        # derived_signals は元アクションのものがそのまま有効。
        derived = self._accumulator.summary().get("derived_signals", {})
        result.confidence_llm_penalty  = derived.get("confidence_llm_penalty")
        result.confidence_llm_detail   = derived.get("confidence_llm_detail")
        result.scope_expansion_detail  = derived.get("scope_expansion_detail")
        result.action_matches_intent_detail = derived.get("action_matches_intent_detail")
        result.seal(self._receipt_secret)
        self._accumulator.record_result(result)
        self._log(result)
        return result

    @property
    def session_id(self) -> str:                          return self._accumulator.context.session_id
    @property
    def receipts(self) -> list[dict]:                     return self._accumulator.receipts
    @property
    def context_summary(self) -> dict:                    return self._accumulator.summary()
    @property
    def identity(self) -> IdentityContext | None:         return self._identity
    @property
    def environment(self) -> EnvironmentContext | None:   return self._environment

    def _log(self, result: AuthorizationResult) -> None:
        icon = {Decision.ALLOW: "✅", Decision.DENY: "❌",
                Decision.MODIFY: "✏️", Decision.DEFER: "⏸️",
                Decision.STEP_UP: "🚨"}.get(result.decision, "?")
        who    = f" | {self._identity.human_principal}" if self._identity else ""
        suffix = f" [解決: {result.resolution_method}]" if result.resolution_method else ""
        print(f"[AARM] {icon} {result.decision.value:7s} | {result.action.tool_name:25s} | {result.reason}{who}{suffix}")
        if self._audit_log_path:
            import json
            entry = result.to_dict()
            entry["session_id"] = self.session_id
            with open(self._audit_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
