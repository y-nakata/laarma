"""
AARM StepUpResolver — STEP_UP 局面の人間承認ワークフロー

STEP_UP は「自律的に ALLOW/DENY に決定できない、人間の判断が必要」を意味する。
DeferralResolver（DEFER の自律解決）と対称的な位置づけ。

処理フロー:
  1. PolicyEngine または IntentAlignment が STEP_UP を返す
  2. StepUpResolver が承認者にエスカレーション（コンソール等）
  3. 承認: ALLOW を返す → ツール実行へ
  4. 拒否: DENY を返す → ToolBlocked 例外へ
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import AuthorizationResult, Decision


class StepUpResolver:
    """
    STEP_UP 判断後に人間の承認を求める。
    デフォルト実装はコンソール（stdin）による同期待機。
    """

    def resolve(self, step_up_result: AuthorizationResult) -> AuthorizationResult:
        """
        STEP_UP したアクションを人間に提示して承認/拒否を得る。

        Returns:
            ALLOW（承認）または DENY（拒否）の AuthorizationResult。
        """
        action = step_up_result.action
        print(f"[AARM] 🔔 STEP_UP: {step_up_result.reason}")
        print(f"[AARM]    ツール : {action.tool_name}")
        print(f"[AARM]    引数   : {action.parameters}")
        try:
            answer = input("[AARM] 承認しますか？ (y/N): ").strip().lower()
        except EOFError:
            answer = "n"
        approved = answer == "y"

        return AuthorizationResult(
            decision=Decision.ALLOW if approved else Decision.DENY,
            reason="承認者により承認されました。" if approved else "承認者により拒否されました。",
            action=action,
            resolution_method="human_approved" if approved else "human_denied",
            resolution_timestamp=datetime.now(timezone.utc),
        )
