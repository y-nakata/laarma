"""
AARM ToolProxy — SDK Instrumentation 層
エージェントとツール実装の間に透過的に挿入されるインターセプトレイヤー。
エージェントは proxy.call() を呼ぶだけ。AARM の存在を知らない。

判断処理（R4要件）:
  ALLOW   : ツールを実行して結果を返す。
  MODIFY  : サニタイズまたは制限されたパラメータ（modified_params）に書き換えてツールを実行する。
  DENY    : ToolBlocked 例外を送出。
  STEP_UP : ToolBlocked 例外を送出（人間承認要求）。
  DEFER   : DeferralResolver で自律解決を試みる。

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
        """
        result = self._runtime.intercept(tool_name, params)

        # 1. DEFER（保留）処理
        if result.decision == Decision.DEFER:
            print(f"[AARM] ⏸️  DEFER   | {tool_name:25s} | {result.reason}")
            print(f"[AARM] 🔄 自律解決を試みる...")
            resolved = self._resolver.resolve(
                deferred_result=result,
                context_summary=self._runtime.context_summary,
            )
            self._runtime.record_deferred_resolution(resolved)
            result = resolved

        # 2. ALLOW（通常許可）処理
        if result.decision == Decision.ALLOW:
            fn = self._tools.get(tool_name)
            if fn is None:
                raise KeyError(f"Tool '{tool_name}' not registered.")
            output = fn(params)
            self._runtime.record_tool_output(result.action.action_id, output)
            return output

        # 3. MODIFY（引数書き換え許可）処理
        if result.decision == Decision.MODIFY:
            fn = self._tools.get(tool_name)
            if fn is None:
                raise KeyError(f"Tool '{tool_name}' not registered.")

            # 書き換え後のパラメータが存在することを確認し、なければフォールバック
            actual_params = result.modified_params if result.modified_params is not None else params

            # runtime は認可結果をすでにログ出力しているため、ここでは余分なダンプを抑制する
            output = fn(actual_params)

            # 書き換えた後の実行結果をコンテキスト履歴に正しくバインド
            self._runtime.record_tool_output(result.action.action_id, output)
            return output

        # 4. DENY / STEP_UP 処理（ブロック例外）
        raise ToolBlocked(result.decision, result.reason)
