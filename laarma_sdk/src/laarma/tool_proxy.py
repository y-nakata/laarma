"""
AARM ToolProxy — SDK Instrumentation 層
エージェントとツール実装の間に透過的に挿入されるインターセプトレイヤー。
エージェントは proxy.call() を呼ぶだけ。AARM の存在を知らない。

proxy.call() の戻り値:
  実行が許可された場合（ALLOW / MODIFY / DEFER→解決後ALLOW / STEP_UP→承認後ALLOW）は dict を返す:
    {
      "decision":        最終判断 (ALLOW | MODIFY),
      "content":         ツールの実行結果（文字列）,
      "actual_params":   実際に実行されたパラメータ,
      "modified_params": MODIFY の場合の書き換え後パラメータ（なければ None）,
    }
  ブロックされた場合（DENY / STEP_UP→拒否）は ToolBlocked 例外を送出する。
"""

from __future__ import annotations

from typing import Any, Callable

from .deferral import DeferralResolver
from .models import Decision
from .runtime import AARMRuntime
from .step_up_resolver import StepUpResolver


class ToolBlocked(Exception):
    def __init__(self, decision: Decision, reason: str) -> None:
        self.decision = decision
        self.reason   = reason
        super().__init__(f"[AARM {decision.value}] {reason}")


class AARMToolProxy:
    def __init__(
        self,
        runtime: AARMRuntime,
        deferral_resolver: DeferralResolver | None = None,
        step_up_resolver: StepUpResolver | None = None,
    ) -> None:
        self._runtime          = runtime
        self._resolver         = deferral_resolver or DeferralResolver()
        self._step_up_resolver = step_up_resolver or StepUpResolver()
        self._tools: dict[str, Callable[[dict], Any]] = {}

    def register(self, tool_name: str, fn: Callable[[dict], Any]) -> None:
        self._tools[tool_name] = fn

    def call(self, tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """
        ツールを透過的にインターセプトして実行する。

        Returns:
            実行が許可された場合は dict（decision/content/actual_params/modified_params）。
        Raises:
            ToolBlocked: DENY / STEP_UP の場合。
        """
        result = self._runtime.intercept(tool_name, params)

        # 1. DEFER（保留）処理 — 自律解決を試みる
        if result.decision == Decision.DEFER:
            # runtime.intercept() が既に DEFER をログ済み。ここでは再ログしない。
            # DEFER のログを追加したくなった場合は runtime._log() に一元化すること（デグレ防止）。
            print(f"[AARM] 🔄 自律解決を試みる...")
            resolved = self._resolver.resolve(
                deferred_result=result,
                context_summary=self._runtime.context_summary,
            )
            self._runtime.record_deferred_resolution(resolved)
            result = resolved

        # 1b. STEP_UP（人間承認）処理
        if result.decision == Decision.STEP_UP:
            # runtime.intercept() または record_deferred_resolution() が既に STEP_UP をログ済み。
            # ここでは再ログしない。
            print("[AARM] 👤 人間の承認を待っています...")
            resolved = self._step_up_resolver.resolve(result)
            self._runtime.record_step_up_resolution(resolved)
            result = resolved

        # 2. ALLOW（通常許可）処理
        if result.decision == Decision.ALLOW:
            fn = self._tools.get(tool_name)
            if fn is None:
                raise KeyError(f"Tool '{tool_name}' not registered.")
            output = fn(params)
            self._runtime.record_tool_output(result.action.action_id, output)
            return {
                "decision":        result.decision.value,
                "content":         output,
                "actual_params":   params,
                "modified_params": None,
            }

        # 3. MODIFY（引数書き換え許可）処理
        if result.decision == Decision.MODIFY:
            fn = self._tools.get(tool_name)
            if fn is None:
                raise KeyError(f"Tool '{tool_name}' not registered.")
            actual_params = result.modified_params if result.modified_params is not None else params
            output = fn(actual_params)
            self._runtime.record_tool_output(result.action.action_id, output)
            return {
                "decision":        result.decision.value,
                "content":         output,
                "actual_params":   actual_params,
                "modified_params": result.modified_params,
            }

        # 4. DENY 処理（ブロック例外）
        raise ToolBlocked(result.decision, result.reason)
