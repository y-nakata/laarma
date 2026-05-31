"""
agent.py — エージェントループ

AARM を一切知らない。ツールを呼ぶだけ。
プラットフォーム側から proxy を注入される。
"""

import anthropic
from aarm import AARMToolProxy, ToolBlocked
from tools import TOOLS


def run(user_request: str, proxy: AARMToolProxy) -> None:
    """
    エージェントループ。
    proxy を「ツール実行窓口」として使うだけ。
    AARM の存在を知らない。
    """
    client   = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_request}]

    while True:
        resp = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            tools=TOOLS,
            messages=messages,
        )
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
