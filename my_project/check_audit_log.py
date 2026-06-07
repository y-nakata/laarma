#!/usr/bin/env python3
"""
AARM 監査ログ（JSONL）の receipt_hash 検証スクリプト。

使い方:
    python my_project/check_audit_log.py aarm_audit.jsonl

注: receipt_hash は鍵なし SHA-256 のため、ハッシュ再計算を伴う意図的な改ざんは検出できない。
    偶発的破損とハッシュアルゴリズムを知らない素朴な改ざんの検出が目的。
"""

import argparse
import hashlib
import json
import sys


def _compute_hash(entry: dict) -> str:
    payload = json.dumps(
        {
            "receipt_id":      entry["receipt_id"],
            "action":          entry["action"],
            "decision":        entry["decision"],
            "reason":          entry["reason"],
            "modified_params": entry.get("modified_params"),
        },
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def check(path: str) -> bool:
    ok = 0
    fail = 0

    with open(path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"[SKIP] Line {lineno}: JSON parse error — {e}")
                continue

            stored   = entry.get("receipt_hash", "")
            computed = _compute_hash(entry)
            rid      = entry.get("receipt_id", "")[:8]
            decision = entry.get("decision", "")

            if stored == computed:
                print(f"[OK]   Line {lineno}: receipt_id={rid}... decision={decision}")
                ok += 1
            else:
                print(f"[FAIL] Line {lineno}: receipt_id={rid}... decision={decision}  ← hash mismatch")
                print(f"         stored  : {stored}")
                print(f"         computed: {computed}")
                fail += 1

    total = ok + fail
    if fail == 0:
        print(f"\n✅ {total} 件すべて正常")
    else:
        print(f"\n❌ {total} 件中 {fail} 件の不一致を検出")

    return fail == 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AARM 監査ログ（JSONL）の receipt_hash を検証する"
    )
    parser.add_argument("log_file", help="検証する JSONL ファイルのパス")
    args = parser.parse_args()

    sys.exit(0 if check(args.log_file) else 1)


if __name__ == "__main__":
    main()
