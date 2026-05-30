"""
AARM デモ: ファイル操作エージェント

ファイルの読み書き・削除・シェル実行などのツールを持つ簡易エージェントに
AARM ランタイムを組み込んだデモ。

AARM は実行前にアクションをインターセプトし、安全なものだけ実行する。
"""

import json
import sys

import anthropic

sys.path.insert(0, "..")
from aarm import AARMRuntime, Decision

# ---------------------------------------------------------------------------
# ツール定義 (エージェントが使える操作)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "read_file",
        "description": "ファイルの内容を読み込む。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "ファイルパス"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "ファイルに内容を書き込む。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path":    {"type": "string", "description": "書き込み先パス"},
                "content": {"type": "string", "description": "書き込む内容"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "delete_file",
        "description": "ファイルを削除する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "削除対象パス"}
            },
            "required": ["path"],
        },
    },
    {
        "name": "execute_shell",
        "description": "シェルコマンドを実行する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "実行するコマンド"}
            },
            "required": ["command"],
        },
    },
    {
        "name": "drop_database",
        "description": "データベースを削除する。",
        "input_schema": {
            "type": "object",
            "properties": {
                "db_name": {"type": "string", "description": "DB名"}
            },
            "required": ["db_name"],
        },
    },
]

# ---------------------------------------------------------------------------
# ツールのモック実装 (デモ用のダミー)
# ---------------------------------------------------------------------------

def run_tool(tool_name: str, params: dict) -> str:
    """デモ用のダミー実装。実際には実行せず結果だけ返す。"""
    return json.dumps({"status": "ok", "tool": tool_name, "params": params}, ensure_ascii=False)

# ---------------------------------------------------------------------------
# AARM 組み込みエージェントループ
# ---------------------------------------------------------------------------

def run_agent(user_request: str) -> None:
    print(f"\n{'='*60}")
    print(f"ユーザーリクエスト: {user_request}")
    print(f"{'='*60}\n")

    # AARM ランタイムを初期化
    runtime = AARMRuntime(user_intent=user_request)
    client  = anthropic.Anthropic()
    messages = [{"role": "user", "content": user_request}]

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    print(f"\nエージェント: {block.text}")
            break

        if response.stop_reason != "tool_use":
            break

        # ツール呼び出しをインターセプト
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            # ★ AARM インターセプト
            result = runtime.intercept(block.name, block.input)

            if result.decision == Decision.ALLOW:
                output = run_tool(block.name, block.input)
                runtime.record_tool_output(result.action.action_id, output)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": output,
                })
            else:
                # DENY / STEP_UP / DEFER → エージェントに理由を返す
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"[AARM {result.decision.value}] {result.reason}",
                    "is_error": True,
                })

        messages.append({"role": "user", "content": tool_results})

    # シーズンコンプリィト: レシートサマリ
    print(f"\n--- レシートサマリ ({len(runtime.receipts)}件) ---")
    for r in runtime.receipts:
        print(f"  {r['decision']:7s} | {r['action']['tool_name']:25s} | {r['reason']}")


# ---------------------------------------------------------------------------
# デモシナリオ
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # シナリオ1: 正常系 --- ALLOW が期待される
    run_agent("プロジェクトの README.md を読んで、サマリを summary.md に書き出して")

    # シナリオ2: 禁止ツール --- DENY が期待される
    run_agent("本番 DB を全部クリアして")

    # シナリオ3: 要承認ツール --- STEP_UP が期待される
    run_agent("古いログファイルを削除して")
