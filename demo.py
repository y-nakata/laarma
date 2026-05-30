"""
AARM デモ: ファイル操作エージェント

エージェントは AARM の存在を知らない。
AARMToolProxy がツールとエージェントの間に透過的に挟まり、
すべてのアクションをインターセプトする。

構造:
    エージェント
      → proxy.call(tool_name, params)  # ただのツール実行に見える
          ↓
      [AARMToolProxy]                  # エージェントは知らない
          ↓ ALLOW の場合のみ
      実際のツール実装
"""

import json
import sys

import anthropic

sys.path.insert(0, "..")
from aarm import AARMRuntime
from aarm.tool_proxy import AARMToolProxy, ToolBlocked

# ---------------------------------------------------------------------------
# ツール定義 (エージェントに見せるスキーマ)
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
# ツールの実装 (デモ用ダミー)
# エージェントからは直接呼ばれない。AARMToolProxy 経由でのみ実行される。
# ---------------------------------------------------------------------------

def _impl_read_file(p: dict) -> str:
    return json.dumps({"content": f"(ダミー) {p['path']} の内容"}, ensure_ascii=False)

def _impl_write_file(p: dict) -> str:
    return json.dumps({"status": "ok", "path": p["path"]}, ensure_ascii=False)

def _impl_delete_file(p: dict) -> str:
    return json.dumps({"status": "ok", "path": p["path"]}, ensure_ascii=False)

def _impl_execute_shell(p: dict) -> str:
    return json.dumps({"stdout": f"(ダミー) {p['command']} の実行結果"}, ensure_ascii=False)

def _impl_drop_database(p: dict) -> str:
    return json.dumps({"status": "ok", "db": p["db_name"]}, ensure_ascii=False)

# ---------------------------------------------------------------------------
# エージェントループ
# エージェントは proxy.call() を呼ぶだけ。AARM を一切知らない。
# ---------------------------------------------------------------------------

def run_agent(user_request: str) -> None:
    print(f"\n{'='*60}")
    print(f"ユーザーリクエスト: {user_request}")
    print(f"{'='*60}\n")

    # --- AARM セットアップ (エージェントの外側で行う) ---
    runtime = AARMRuntime(user_intent=user_request)
    proxy   = AARMToolProxy(runtime)
    proxy.register("read_file",     _impl_read_file)
    proxy.register("write_file",    _impl_write_file)
    proxy.register("delete_file",   _impl_delete_file)
    proxy.register("execute_shell", _impl_execute_shell)
    proxy.register("drop_database", _impl_drop_database)

    # --- エージェントループ (proxy 以外に AARM への言及なし) ---
    client   = anthropic.Anthropic()
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

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            try:
                # エージェントからは「ただのツール実行」に見える
                # 内部では AARM が透過的にインターセプトしている
                output = proxy.call(block.name, block.input)
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     output,
                })
            except ToolBlocked as e:
                # DENY / STEP_UP / DEFER はエラーとしてエージェントに伝わる
                tool_results.append({
                    "type":        "tool_result",
                    "tool_use_id": block.id,
                    "content":     str(e),
                    "is_error":    True,
                })

        messages.append({"role": "user", "content": tool_results})

    # レシートサマリ
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
