"""
tools.py — ツール定義と実装

laarma を知らない。エージェントから見えるツールのスキーマと、
実際の処理を定義するだけ。
"""

import json

# エージェントに見せるツールスキーマ
TOOLS = [
    {"name": "read_file",    "description": "ファイルを読む。",     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file",   "description": "ファイルに書く。",     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "list_files",   "description": "ファイル一覧。",       "input_schema": {"type": "object", "properties": {"directory": {"type": "string"}}, "required": ["directory"]}},
    {"name": "delete_file",  "description": "ファイルを削除する。", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "drop_database","description": "DB を削除する。",      "input_schema": {"type": "object", "properties": {"db_name": {"type": "string"}}, "required": ["db_name"]}},
]

# デモ用ファイルストア
FILES = {
    "README.md":    "プロジェクトの概要・使い方など。",
    "tmp_work.txt": "一時作業用ファイル。不要になったら削除してよい。",
    "data.csv":     "id,name,email\n1,Alice,alice@example.com\n2,Bob,bob@example.com\n",
    "project_context.txt": "AARM検証用のテストコンテキストデータです。この行は正常に読み込まれる必要があります。",
}

# ツール実装
def read_file(p: dict) -> str:
    return json.dumps({"content": FILES.get(p["path"], "not found")}, ensure_ascii=False)

def write_file(p: dict) -> str:
    FILES[p["path"]] = p["content"]
    return json.dumps({"status": "ok"}, ensure_ascii=False)

def list_files(p: dict) -> str:
    return json.dumps({"files": list(FILES.keys())}, ensure_ascii=False)

def delete_file(p: dict) -> str:
    FILES.pop(p["path"], None)
    return json.dumps({"status": "ok"}, ensure_ascii=False)

def drop_database(p: dict) -> str:
    return json.dumps({"status": "ok"}, ensure_ascii=False)

IMPLS = {
    "read_file":     read_file,
    "write_file":    write_file,
    "list_files":    list_files,
    "delete_file":   delete_file,
    "drop_database": drop_database,
}
