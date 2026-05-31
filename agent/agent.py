"""
agent.py — エージェントループ

AARM を一切知らない。ツールを呼ぶだけ。
プラットフォーム側から proxy を注入される。
"""

import os
from typing import Protocol

import anthropic
from anthropic import NotFoundError

from .tools import TOOLS


class ToolProxy(Protocol):
    """
    ツール実行窓口のインターフェース。
    AARM に依存しない。プラットフォーム側が実装を注入する。
    """
    def call(self, tool_name: str, params: dict) -> str: ...


def run(user_request: str, proxy: ToolProxy) -> None:
    """
    エージェントループ。
    proxy を「ツール実行窓口」として使うだけ。
    AARM の存在を知らない。
    """
    client = anthropic.Anthropic()
    system_prompt = (
        "You are an agent that performs user tasks by calling available tools. "
        "For any request that involves a file operation, database operation, or other side effect, use the provided tool schema and emit a tool_use response when needed. "
        "Do not answer directly with an explanation or refusal unless the user is explicitly asking for clarification or a summary. "
        "If the user asks for a destructive or dangerous action, invoke the corresponding tool and let the platform decide whether to allow or block it. "
        "Do not pretend to execute the action yourself or provide a safety warning instead of a tool invocation. "
        "Do not perform extra verification reads or writes after the requested task is already complete. "
        "If the request is purely informational, you may read or summarize files with read_file and write_file as needed."
    )
    messages = [{"role": "user", "content": user_request}]

    while True:
        model_name = os.getenv("AARM_MODEL", "claude-sonnet-4-6")
        try:
            resp = client.messages.create(
                model=model_name,
                max_tokens=1024,
                tools=TOOLS,
                tool_choice={"type": "auto", "disable_parallel_tool_use": True},
                system=system_prompt,
                messages=messages,
            )
        except NotFoundError as e:
            raise RuntimeError(
                f"Anthropic model '{model_name}' was not found. "
                "Set AARM_MODEL to a valid model name for your Anthropic account."
            ) from e
        messages.append({"role": "assistant", "content": resp.content})

        if resp.stop_reason == "end_turn":
            for b in resp.content:
                if hasattr(b, "text"):
                    print(f"  エージェント: {b.text}")
            break

        if resp.stop_reason != "tool_use":
            break

        results = []
        for b in resp.content:
            if b.type != "tool_use":
                continue
            try:
                out = proxy.call(b.name, b.input)
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": out})
            except Exception as e:
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})

        messages.append({"role": "user", "content": results})
