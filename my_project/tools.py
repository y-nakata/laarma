"""
tools.py — ツール定義と実装

laarma を知らない。エージェントから見えるツールのスキーマと、
実際の処理を定義するだけ。
"""

import json

# エージェントに見せるツールスキーマ。
# policy.yaml の tool_classification（destructive_tools/sensitive_tools/external_tools）・
# denied_tools が参照するツール名は、実装が存在しない状態を残さずここで全て定義する
# （実装を持たないツール名を policy が参照していると、policy が実際に評価しうる範囲を
# デモ上で検証できない）。危険系（execute_shell・delete_all_records・exfiltrate_data・
# disable_logging）は policy の denied_tools/destructive_tools 側で実行前にブロックされる
# 想定であり、実装内容自体は状態を変えないダミーで足りる。
TOOLS = [
    {"name": "read_file",    "description": "ファイルを読む。",     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "write_file",   "description": "ファイルに書く。",     "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    {"name": "list_files",   "description": "ファイル一覧。",       "input_schema": {"type": "object", "properties": {"directory": {"type": "string"}}, "required": ["directory"]}},
    {"name": "delete_file",  "description": "ファイルを削除する。", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    {"name": "drop_database","description": "DB を削除する。",      "input_schema": {"type": "object", "properties": {"db_name": {"type": "string"}}, "required": ["db_name"]}},
    # destructive_tools（drop_database と同様、危険操作。denied_tools/destructive_tools 経由で
    # 実行前にブロックされる想定）
    {"name": "delete_all_records", "description": "テーブルの全レコードを削除する。", "input_schema": {"type": "object", "properties": {"table": {"type": "string"}}, "required": ["table"]}},
    {"name": "execute_shell",      "description": "シェルコマンドを実行する。",       "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    # denied_tools 専用（exfiltrate_data・disable_logging は destructive_tools/sensitive_tools
    # のいずれにも属さず、denied_tools のみで絶対禁止される）
    {"name": "exfiltrate_data",  "description": "データを外部に持ち出す。", "input_schema": {"type": "object", "properties": {"destination": {"type": "string"}}, "required": ["destination"]}},
    {"name": "disable_logging",  "description": "監査ログを無効化する。", "input_schema": {"type": "object", "properties": {}, "required": []}},
    # sensitive_tools（機密性の高い操作。data_classification の SENSITIVE_TOOL ラベルに使われる）
    {"name": "database",    "description": "データベースにクエリを実行する。", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "db",           "description": "database の別名。",             "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    {"name": "execute_sql",  "description": "SQL を実行する。",              "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    # external_tools（外部送信。scope_expansion 判定の対象）
    {"name": "send_email",     "description": "メールを送信する。",           "input_schema": {"type": "object", "properties": {"to": {"type": "string"}, "body": {"type": "string"}}, "required": ["to", "body"]}},
    {"name": "http_request",   "description": "外部 HTTP リクエストを送る。", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "webhook",        "description": "webhook を呼び出す。",        "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    {"name": "slack_message",  "description": "Slack にメッセージを送る。",  "input_schema": {"type": "object", "properties": {"channel": {"type": "string"}, "text": {"type": "string"}}, "required": ["channel", "text"]}},
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
    "app.db":              "本番データベースファイル。",
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

def delete_all_records(p: dict) -> str:
    return json.dumps({"status": "ok"}, ensure_ascii=False)

def execute_shell(p: dict) -> str:
    return json.dumps({"status": "ok", "output": "(simulated)"}, ensure_ascii=False)

def exfiltrate_data(p: dict) -> str:
    return json.dumps({"status": "ok"}, ensure_ascii=False)

def disable_logging(p: dict) -> str:
    return json.dumps({"status": "ok"}, ensure_ascii=False)

def database(p: dict) -> str:
    return json.dumps({"status": "ok", "rows": []}, ensure_ascii=False)

def db(p: dict) -> str:
    return database(p)

def execute_sql(p: dict) -> str:
    return json.dumps({"status": "ok", "rows": []}, ensure_ascii=False)

def send_email(p: dict) -> str:
    return json.dumps({"status": "ok"}, ensure_ascii=False)

def http_request(p: dict) -> str:
    return json.dumps({"status": "ok"}, ensure_ascii=False)

def webhook(p: dict) -> str:
    return json.dumps({"status": "ok"}, ensure_ascii=False)

def slack_message(p: dict) -> str:
    return json.dumps({"status": "ok"}, ensure_ascii=False)

IMPLS = {
    "read_file":         read_file,
    "write_file":        write_file,
    "list_files":        list_files,
    "delete_file":       delete_file,
    "drop_database":     drop_database,
    "delete_all_records": delete_all_records,
    "execute_shell":     execute_shell,
    "exfiltrate_data":   exfiltrate_data,
    "disable_logging":   disable_logging,
    "database":          database,
    "db":                db,
    "execute_sql":       execute_sql,
    "send_email":        send_email,
    "http_request":      http_request,
    "webhook":           webhook,
    "slack_message":     slack_message,
}
