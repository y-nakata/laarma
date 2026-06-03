"""
AARM ToolProxy — SDK Instrumentation 層
エージェントとツール実装の間に透過的に挿入されるインターセプトレイヤー。
エージェントは proxy.call() を呼ぶだけ。AARM の存在を知らない。

DEFER の処理:
  DEFER は他のブロック判断と異なり、「保留→追加コンテキスト収集→再評価」のワークフローを起動する。
  DeferralResolver が自律解決を試み、できなければ STEP_UP に格上げする。
"""

from __future__ import annotations

from typing import Any, Callable

from .deferral import DeferralResolver
from .models import Decision
from .runtime import AARMRuntime


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
    ) -> None:
        """
        Args:
            runtime:           AARM ランタイム
            deferral_resolver: DEFER の自律解決ハンドラ。
                               None の場合はデフォルト実装を使用。
        """
        self._runtime  = runtime
        self._resolver = deferral_resolver or DeferralResolver()
        self._tools: dict[str, Callable[[dict], Any]] = {}

    def register(self, tool_name: str, fn: Callable[[dict], Any]) -> None:
        self._tools[tool_name] = fn

    def call(self, tool_name: str, params: dict[str, Any]) -> str:
        """
        ツールを透過的にインターセプトして実行する。

        判断別の処理:
          ALLOW   : ツールを実行して結果を返す
          DENY    : ToolBlocked 例外を送出
          STEP_UP : ToolBlocked 例外を送出（人間承認要求）
          DEFER   : DeferralResolver で自律解決を試み、
                    解決後の判断を適用する
        """
        result = self._runtime.intercept(tool_name, params)

        if result.decision == Decision.DEFER:
            print(f"[AARM] ⏸️  DEFER   | {tool_name:25s} | {result.reason}")
            print(f"[AARM] 🔄 自律解決を試みる...")
            resolved = self._resolver.resolve(
                deferred_result=result,
                context_summary=self._runtime.context_summary,
            )
            self._runtime.record_deferred_resolution(resolved)
            result = resolved

        if result.decision == Decision.ALLOW:
            fn = self._tools.get(tool_name)
            if fn is None:
                raise KeyError(f"Tool '{tool_name}' not registered.")
            output = fn(params)
            self._runtime.record_tool_output(result.action.action_id, output)
            return output

        raise ToolBlocked(result.decision, result.reason)
