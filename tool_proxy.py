"""
AARM ToolProxy

エージェントとツール実装の間に透過的に挟まるインターセプトレイヤー。
エージェントは AARM の存在を知らず、ToolProxy を通じてツールを実行する。

  エージェント
    → ツールを呼ぼうとする
        ↓
    [AARMToolProxy]  ← エージェントは知らない
        ↓ ALLOW の場合のみ
    実際のツール実装
"""

from __future__ import annotations

from typing import Any, Callable

from .models import Decision
from .runtime import AARMRuntime


class ToolBlocked(Exception):
    """AARM がツール実行をブロックしたときに送出される例外。"""

    def __init__(self, decision: Decision, reason: str) -> None:
        self.decision = decision
        self.reason = reason
        super().__init__(f"[AARM {decision.value}] {reason}")


class AARMToolProxy:
    """
    エージェントから見ると「ただのツール実行窓口」だが、
    内部では AARM Runtime を通じてすべてのアクションをインターセプトする。

    使い方:
        # 実ツールの実装を登録
        proxy = AARMToolProxy(runtime)
        proxy.register("read_file",  lambda p: ...)
        proxy.register("write_file", lambda p: ...)

        # エージェントのツール呼び出し処理でそのまま差し替える
        output = proxy.call(tool_name, params)
    """

    def __init__(self, runtime: AARMRuntime) -> None:
        self._runtime = runtime
        self._tools: dict[str, Callable[[dict], Any]] = {}

    def register(self, tool_name: str, fn: Callable[[dict], Any]) -> None:
        """ツール名と実装関数を登録する。"""
        self._tools[tool_name] = fn

    def call(self, tool_name: str, params: dict[str, Any]) -> str:
        """
        ツールを透過的にインターセプトして実行する。

        - ALLOW  : 実ツール関数を呼び出して結果を返す
        - それ以外: ToolBlocked 例外を送出する (エージェントにはエラーとして見える)
        """
        # AARM インターセプト (エージェントは知らない)
        result = self._runtime.intercept(tool_name, params)

        if result.decision == Decision.ALLOW:
            fn = self._tools.get(tool_name)
            if fn is None:
                raise KeyError(f"ツール '{tool_name}' が登録されていません。")
            output = fn(params)
            self._runtime.record_tool_output(result.action.action_id, output)
            return output

        # DENY / STEP_UP / DEFER はすべて ToolBlocked として伝播
        raise ToolBlocked(result.decision, result.reason)
