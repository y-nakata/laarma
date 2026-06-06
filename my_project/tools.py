"""
tools.py — ツール定義と実装

laarma を知らない。エージェントから見えるツールのスキーマと、
実際の処理を定義するだけ。

ただし各ツールの risk_class（laarma SDK のリスク分類）は
ツール実装者が宣言する。これは「このツールが何をするか」という
ツールの本質的属性であり、ツール実装者が最も正確に知っている。
"""

import json

from laarma import ToolRiskClass

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
    "README.md":           "プロジェクトの概要・使い方など。",
    "tmp_work.txt":        "一時作業用ファイル。不要になったら削除してよい。",
    "personal_info.csv":   "id,name,email\n1,Alice,alice@example.com\n2,Bob,bob@example.com\n",
    "project_context.txt": "AARM検証用のテストコンテキストデータです。この行は正常に読み込まれる必要があります。",
    "report_a.txt":        "レポート A。",
    "report_b.txt":        "レポート B。",
    "report_c.txt":        "レポート C。",
    "notes_2024.txt":      "ノート 2024年分。",
    "notes_2025.txt":      "ノート 2025年分。",
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

# ツール実装と risk_class をまとめて宣言
# (fn, risk_class) のタプル。ツール実装者が各ツールのリスク分類を宣言する。
IMPLS = {
    "read_file":     (read_file,     ToolRiskClass.READ_ONLY),
    "write_file":    (write_file,    ToolRiskClass.WRITE),
    "list_files":    (list_files,    ToolRiskClass.READ_ONLY),
    "delete_file":   (delete_file,   ToolRiskClass.DESTRUCTIVE),
    "drop_database": (drop_database, ToolRiskClass.DESTRUCTIVE),
}
