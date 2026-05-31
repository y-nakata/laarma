"""
agent.py — エージェントループ

AARM を一切知らない。ツールを呼ぶだけ。
プラットフォーム側から proxy を注入される。
"""

import os
import anthropic
from anthropic import NotFoundError
from aarm import AARMToolProxy, ToolBlocked
from .tools import TOOLS


def run(user_request: str, proxy: AARMToolProxy) -> None:
    """
    エージェントループ。
    proxy を「ツール実行窓口」として使うだけ。
    AARM の存在を知らない。
    """
    client   = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_request}]

    while True:
        model_name = os.getenv("AARM_MODEL", "claude-sonnet-4-6")
        try:
            resp = client.messages.create(
                model=model_name,
                max_tokens=1024,
                tools=TOOLS,
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
            except ToolBlocked as e:
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": str(e), "is_error": True})

        messages.append({"role": "user", "content": results})
