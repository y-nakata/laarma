"""
AARM ToolProxy — SDK Instrumentation 層
エージェントとツール実装の間に透過的に挿入されるインターセプトレイヤー。
エージェントは proxy.call() を呼ぶだけ。AARM の存在を知らない。
"""

from __future__ import annotations

from typing import Any, Callable

from .models import Decision
from .runtime import AARMRuntime


class ToolBlocked(Exception):
    def __init__(self, decision: Decision, reason: str) -> None:
        self.decision = decision
        self.reason   = reason
        super().__init__(f"[AARM {decision.value}] {reason}")


class AARMToolProxy:
    def __init__(self, runtime: AARMRuntime) -> None:
        self._runtime = runtime
        self._tools: dict[str, Callable[[dict], Any]] = {}

    def register(self, tool_name: str, fn: Callable[[dict], Any]) -> None:
        self._tools[tool_name] = fn

    def call(self, tool_name: str, params: dict[str, Any]) -> str:
        result = self._runtime.intercept(tool_name, params)
        if result.decision == Decision.ALLOW:
            fn = self._tools.get(tool_name)
            if fn is None:
                raise KeyError(f"Tool '{tool_name}' not registered.")
            output = fn(params)
            self._runtime.record_tool_output(result.action.action_id, output)
            return output
        raise ToolBlocked(result.decision, result.reason)
