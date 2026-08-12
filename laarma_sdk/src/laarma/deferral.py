"""
AARM DeferralResolver — DEFER 局面の解決

AARM 仕様 Section IV-B4 / R6 の DEFER 定義:
  「コンテキストが不十分・曖昧・内部矛盾の場合、安全な allow/deny にコミットする
   よりも実行を一時保留する」

DEFER を出せること自体は R4（MUST: policy engine は ALLOW/DENY/MODIFY/STEP_UP/DEFER の
5決定のいずれかを出せなければならない）が要求し、PolicyEngine が満たす。DEFER 後の解決機構の
中身を規定する適合要件は存在しない（適合性は R3(a)(b)(c) で判定される。`docs/aarm/deferral.md`
参照）ため、機構の設計は laarma の選択である。

laarma の現状（#135）は、DEFER の発生源（同一 priority 競合／メンテナンス窓不足／confidence
低下）のいずれについても、resolve() が呼ばれる時点で正当に扱える新しい情報を持たない
（追加コンテンツ収集の実装が無く、環境状態の待機も
docs/design/environment-demo-fiction.md の確定判断によりデモフィクションの域を出ない）。

新情報が無い以上、LLM にここで ALLOW/DENY/STEP_UP の decision を出させる正当な根拠は無い
（#112 の「LLM は signal を出す・decision はポリシーが決める」という原則が、DEFER 解決層
だけ破られていた）。したがって resolve() は決定論的に常に STEP_UP へエスカレーションする。
「自律解決を試みる」という体裁（呼び出し元 `tool_proxy.py` の演出）はデモフィクションとして
残すが、実際の decision は LLM の出力に左右されない。

処理フロー:
  1. PolicyEngine が DEFER を返す
  2. DeferralResolver が決定論的に STEP_UP へ格上げする（人間介入を要求）
"""

from __future__ import annotations

from datetime import datetime, timezone

from .models import AuthorizationResult, Decision


class DeferralResolver:
    """
    DEFER 判断を決定論的に STEP_UP へ格上げする。

    resolve() の時点で新たに得られる情報は無いため（#135）、LLM 等による自律的な
    ALLOW/DENY 判定は行わない。常に人間の承認へエスカレーションする。
    """

    def resolve(
        self,
        deferred_result: AuthorizationResult,
        context_summary: dict,
    ) -> AuthorizationResult:
        """
        DEFER したアクションを STEP_UP へ格上げする。

        Returns:
            decision=STEP_UP の AuthorizationResult。元の DEFER 理由は
            deferral_reason にそのまま引き継がれる。
        """
        action = deferred_result.action
        now = datetime.now(timezone.utc)
        return AuthorizationResult(
            decision=Decision.STEP_UP,
            reason=(
                f"自律解決の材料となる新しい情報が存在しないため、人間の承認が必要です"
                f"（保留理由: {deferred_result.reason}）"
            ),
            action=action,
            deferral_reason=deferred_result.reason,
            resolution_method="step_up",
            resolution_timestamp=now,
            decision_source="deferral_resolver",
        )
