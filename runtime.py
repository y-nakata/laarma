"""
AARM Runtime

Step 1〜5の全コンポーネントを統合し、
「インターセプト → コンテキスト蓄積 → 評価 → 決定 → 記録」のアクションライフサイクルを実行する。
AARM 仕様の中核コンポーネント。
"""

from __future__ import annotations

from typing import Any

from .context_accumulator import ContextAccumulator
from .intent_alignment import IntentAlignment
from .models import Action, AuthorizationResult, Decision, IdentityContext
from .policy_engine import DEFAULT_POLICY, Policy, PolicyEngine


class AARMRuntime:
    """
    AARM ランタイムのメインクラス。

    エージェントはツールを呼び出す前に `intercept()` を通す。
    ALLOW の場合のみツールを実行し、結果を `record_tool_output()` で記録する。

    使い方:
        identity = IdentityContext(
            human_principal="alice@example.com",
            service_identity="agent-svc@iam",
            session_id="sess_abc123",
            privilege_scope=["read_file", "write_file"],
        )
        runtime = AARMRuntime(user_intent="レポートを作る", identity=identity)
        result = runtime.intercept("write_file", {"path": "report.md", "content": "..."})
    """

    def __init__(
        self,
        user_intent: str,
        identity: IdentityContext | None = None,
        policy: Policy | None = None,
        model: str = "claude-sonnet-4-20250514",
        metadata: dict[str, Any] | None = None,
        skip_intent_alignment: bool = False,
    ) -> None:
        """
        Args:
            user_intent:            ユーザーの元の目的・リクエスト
            identity:               このセッションを実行するアイデンティティ (R6)
            policy:                 カスタムポリシー (省略時は DEFAULT_POLICY)
            model:                  Intent Alignment で使う Claude モデル
            metadata:               セッションの付加情報
            skip_intent_alignment:  True の場合 Intent Alignment をスキップ (テスト用)
        """
        self._identity = identity
        self._accumulator = ContextAccumulator(user_intent=user_intent, metadata=metadata)
        self._policy_engine = PolicyEngine(policy=policy or DEFAULT_POLICY)
        self._intent_alignment = IntentAlignment(model=model)
        self._skip_intent_alignment = skip_intent_alignment

    # ------------------------------------------------------------------
    # パブリック API
    # ------------------------------------------------------------------

    def intercept(self, tool_name: str, parameters: dict[str, Any]) -> AuthorizationResult:
        """
        ツール呼び出しをインターセプトし、認可判断を返す。

        処理フロー:
          1. Action を生成 (identity を紐付け) しコンテキストに記録
          2. PolicyEngine で静的評価
          3. IntentAlignment で (a, C) タプル評価
          4. 認可結果をレシートログに記録
          5. 結果を返す
        """
        # Step 1: identity を紐付けた Action を生成
        action = Action(
            tool_name=tool_name,
            parameters=parameters,
            identity=self._identity,
        )
        self._accumulator.record_action(action)
        context = self._accumulator.context

        # Step 2: 静的ポリシー評価
        result = self._policy_engine.evaluate(action, context)

        # Step 3: 意図整合性評価 (ポリシーを通過した場合のみ)
        if result is None:
            if self._skip_intent_alignment:
                result = AuthorizationResult(
                    decision=Decision.ALLOW,
                    reason="ポリシーチェック通過。",
                    action=action,
                )
            else:
                result = self._intent_alignment.evaluate(
                    action,
                    self._accumulator.summary(),
                )

        # Step 4: レシート記録
        self._accumulator.record_result(result)

        self._log(result)
        return result

    def record_tool_output(self, action_id: str, output: Any) -> None:
        """ツール実行後の出力をコンテキストに記録する。"""
        self._accumulator.record_tool_output(action_id, output)

    @property
    def session_id(self) -> str:
        return self._accumulator.context.session_id

    @property
    def receipts(self) -> list[dict]:
        """セッション内の全レシートを返す。"""
        return self._accumulator.receipts

    @property
    def context_summary(self) -> dict:
        """Context Accumulator が蓄積したセッションサマリを返す (派生シグナル含む)。"""
        return self._accumulator.summary()

    @property
    def identity(self) -> IdentityContext | None:
        """このセッションのアイデンティティを返す。"""
        return self._identity

    # ------------------------------------------------------------------
    # プライベートメソッド
    # ------------------------------------------------------------------

    def _log(self, result: AuthorizationResult) -> None:
        icon = {
            Decision.ALLOW:   "\u2705",
            Decision.DENY:    "\u274c",
            Decision.MODIFY:  "\u270f\ufe0f",
            Decision.DEFER:   "\u23f8\ufe0f",
            Decision.STEP_UP: "\U0001f6a8",
        }.get(result.decision, "?")
        identity_str = ""
        if self._identity:
            identity_str = f" | {self._identity.human_principal}"
        print(
            f"[AARM] {icon} {result.decision.value:7s} "
            f"| {result.action.tool_name:25s} "
            f"| {result.reason}"
            f"{identity_str}"
        )
