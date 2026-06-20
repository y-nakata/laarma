"""
AARM Runtime — R1〜R6 統合
「インターセプト → コンテキスト蓄積 → ポリシー評価 → 意図整合性評価 (a, C, E) → 記録」
"""

from __future__ import annotations

import os
import warnings
from typing import Any

from .context_accumulator import ContextAccumulator
from .environment import EnvironmentContext
from .intent_alignment import IntentAlignment
from .models import Action, AuthorizationResult, Decision, IdentityContext
from .policy_engine import DEFAULT_POLICY, Policy, PolicyEngine


class AARMRuntime:
    def __init__(
        self,
        user_intent: str,
        identity: IdentityContext | None = None,
        environment: EnvironmentContext | None = None,
        policy: Policy | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
        _skip_intent_alignment_for_testing: bool = False,
        transform_registry: "dict[str, Any] | None" = None,
        _intent_alignment: "Any | None" = None,
    ) -> None:
        self._identity    = identity
        self._environment = environment
        _policy           = policy or DEFAULT_POLICY
        self._accumulator = ContextAccumulator(user_intent=user_intent, metadata=metadata, policy=_policy)
        # IntentAlignment を構築して PolicyEngine に注入する（提案/上書きモデル）
        if _skip_intent_alignment_for_testing:
            if not os.getenv("AARM_ALLOW_SKIP_INTENT_ALIGNMENT"):
                raise RuntimeError(
                    "skip_intent_alignment_for_testing は本番環境では使用禁止です。"
                    "テスト目的で使用する場合は AARM_ALLOW_SKIP_INTENT_ALIGNMENT=1 を設定してください。"
                )
            ia = _intent_alignment  # スタブが注入されている場合はそれを使用
        else:
            ia = _intent_alignment or IntentAlignment(
                model=model or os.getenv("AARM_MODEL", "claude-sonnet-4-6"),
            )
        self._policy_engine = PolicyEngine(
            policy=_policy,
            transform_registry=transform_registry,
            intent_alignment=ia,
        )
        self._audit_log_path = os.getenv("AARM_AUDIT_LOG_PATH")
        self._receipt_secret = os.getenv("AARM_RECEIPT_SECRET")
        # R6 MUST: identity の cryptographic binding 検証
        _identity_secret = os.getenv("AARM_IDENTITY_SECRET")
        if _identity_secret and identity is not None and not identity.verify(_identity_secret):
            warnings.warn(
                "IdentityContext の identity_token が未設定または不正です。"
                "identity.sign(secret) で署名してから渡してください。",
                stacklevel=2,
            )

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
