"""
AARM DeferralResolver — DEFER 局面の自律解決ワークフロー

AARM 仕様 Section IV-B4 / R6 の DEFER 定義:
  「コンテキストが不十分・曖昧・内部矛盾の場合、安全な allow/deny にコミットする
   よりも実行を一時保留する」

SDK 方式では「エージェントの推論トレース・メモリ・保留ツール出力から
追加データを収集して最終判断を下せる」と仕様に明記されている。

処理フロー:
  1. IntentAlignment が DEFER を返す
  2. DeferralResolver が自後に追加コンテキストを仙8させて再評価を試みる
  3. 自律解決できた場合: ALLOW または DENY を返す
  4. 自律解決できない場合: STEP_UP に格上げして人間介入を要求
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

from .models import Action, AuthorizationResult, Decision


# このプロンプトを IntentAlignment と分けるのは、「追加コンテキスト付きで再評価する」
# という DeferralResolver 固有の責務を明示するため
SYSTEM_PROMPT = """\
You are an AARM deferral resolver.
A previous evaluation returned DEFER because context was insufficient or ambiguous.
You now have additional context. Re-evaluate whether the action should be allowed or denied.

You receive:
- original_deferral_reason: why the first evaluation was deferred
- user_intent: the user's original request
- recent_actions: prior actions in this session
- derived_signals: data_classifications, semantic_distance, scope_expansion_detected
- proposed_action: the action pending execution
- additional_context: supplementary information gathered after deferral

Respond ONLY with a raw JSON object (do not wrap in markdown block quotes, do not include pre-text, post-text, or explanations):
{"decision": "ALLOW"|"DENY"|"STEP_UP", "reason": "<one sentence in Japanese>"}

Note: Do NOT return DEFER again. You must reach a conclusion based on the following strict criteria:

- ALLOW  : Additional context fully and explicitly mitigates the core risk stated in `original_deferral_reason`, and confirms perfect alignment with intent. (e.g., if deferred due to lack of token/permission, the missing proof is now provided).
- DENY   : Additional context confirms the action is unauthorized, malicious, or violates absolute safety constraints.
- STEP_UP: The original risk (e.g., destructive action in Production outside maintenance window) remains fundamentally unmitigated despite the additional context being clean. Choose STEP_UP if autonomous resolution cannot absolute guarantee environmental safety, forcing human approval.

CRITICAL CRITERIA:
- Even if `derived_signals` show no anomalies (e.g., low semantic distance, PUBLIC data classification), you MUST NOT choose ALLOW if the `original_deferral_reason` involves high-risk environment/operation rules that require human oversight. In such cases, you MUST escalate to STEP_UP.
"""

class DeferralResolver:
    """
    DEFER 判断後に自律的に追加コンテキストを収集して再評価する。
    解決できなければ STEP_UP に格上げする。
    """

    def __init__(
        self,
        model: str | None = None,
        additional_context_fn: Any = None,
    ) -> None:
        """
        Args:
            model: 再評価に使う Claude モデル
            additional_context_fn: 追加コンテキストを収集する関数。
                signature: (action: Action, context_summary: dict) -> dict
                None の場合はデフォルト実装を使う。
        """
        self._model = model or os.getenv("AARM_MODEL", "claude-sonnet-4-6")
        self._client = None
        self._additional_context_fn = additional_context_fn or self._default_additional_context

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def resolve(
        self,
        deferred_result: AuthorizationResult,
        context_summary: dict,
    ) -> AuthorizationResult:
        """
        DEFER したアクションを再評価する。

        Returns:
            解決後の AuthorizationResult。
            decision は ALLOW / DENY / STEP_UP のいずれか。
        """
        action = deferred_result.action
        additional_ctx = self._additional_context_fn(action, context_summary)

        try:
            resp = self._get_client().messages.create(
                model=self._model,
                max_tokens=256,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps({
                    "original_deferral_reason": deferred_result.reason,
                    "user_intent":              context_summary.get("user_intent", ""),
                    "recent_actions":           context_summary.get("recent_actions", []),
                    "derived_signals":          context_summary.get("derived_signals", {}),
                    "proposed_action": {
                        "tool_name":  action.tool_name,
                        "parameters": action.parameters,
                    },
                    "additional_context": additional_ctx,
                }, ensure_ascii=False, indent=2)}],
            )
            text_parts = [b.text for b in resp.content if hasattr(b, "text") and b.text]
            raw = "\n".join(text_parts).strip()

            # Markdownのコードブロック（```json ... ```）を検出するための正規表現
            # システムパーサーの誤認を防ぐため、3連続のバックティックを動的に組み立てます
            bt = "`" * 3
            pattern = rf"{bt}(?:json)?\s*(\{{.*?\}})\s*{bt}"
            
            fence = re.search(pattern, raw, re.S)
            if fence:
                raw = fence.group(1).strip()
            else:
                # LLMが前置きを入れて出力してしまった場合のフォールバック（最初の { と最後の } を探す）
                start = raw.find('{')
                end = raw.rfind('}')
                if start != -1 and end != -1:
                    raw = raw[start:end+1].strip()
            
            parsed   = json.loads(raw)
            decision = Decision(parsed["decision"])
            reason   = parsed.get("reason", "(reason not provided)")
        except Exception as e:
            # 再評価失敗時は人間介入へ
            decision = Decision.STEP_UP
            reason   = f"再評価中にエラーが発生したため人間の承認が必要: {e}"

        now = datetime.now(timezone.utc)
        result = AuthorizationResult(
            decision=decision,
            reason=reason,
            action=action,
            deferral_reason=deferred_result.reason,
            resolution_method="autonomous" if decision != Decision.STEP_UP else "step_up",
            resolution_timestamp=now,
        )
        return result

    @staticmethod
    def _default_additional_context(action: Action, context_summary: dict) -> dict:
        """
        デフォルトの追加コンテキスト収集実装。
        セッション内の全履歴とアクション数を返す。
        本番ではエージェントのメモリや保留ツール出力などを使うこともできる。
        """
        return {
            "total_actions_in_session": context_summary.get("action_count", 0),
            "all_actions": context_summary.get("recent_actions", []),
            "note": "No additional runtime context available in this prototype.",
        }
