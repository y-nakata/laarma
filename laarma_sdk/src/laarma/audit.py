"""
AARM 監査ログ（JSONL）の receipt_hash 計算・検証。

正規化＋ハッシュ計算は compute_receipt_hash() に一元化されている。
ここに正規化ロジックを再実装しないこと（過去に check_audit_log.py が本体の
ロジックを写経し、本体側の変更に追従できずズレて壊れた実績がある）。

使い方:
    python -m laarma.audit aarm_audit.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys


def compute_receipt_hash(fields: dict, secret: str | None) -> str:
    payload = json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()
    if secret:
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hashlib.sha256(payload).hexdigest()


def _fields_from_entry(entry: dict) -> dict:
    return {
        "receipt_id":          entry["receipt_id"],
        "action":              entry["action"],
        "decision":            entry["decision"],
        "reason":              entry["reason"],
        "modified_params":     entry.get("modified_params"),
        "decision_source":     entry.get("decision_source"),
        "policy_rule_id":      entry.get("policy_rule_id"),
        "deferral_reason":     entry.get("deferral_reason"),
        "proposed_decision":   entry.get("proposed_decision"),
        "resolution_method":   entry.get("resolution_method"),
        "resolution_timestamp": entry.get("resolution_timestamp"),
    }


def verify_audit_log(path: str, secret: str | None, allow_mixed: bool = False) -> bool:
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
            computed = compute_receipt_hash(_fields_from_entry(entry), secret)
            rid      = entry.get("receipt_id", "")[:8]
            decision = entry.get("decision", "")

            matched = (stored == computed)
            # 混在ログ対応: HMAC で不一致なら鍵なし SHA-256 でも試みる
            if not matched and allow_mixed and secret:
                matched = (stored == compute_receipt_hash(_fields_from_entry(entry), None))

            if matched:
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
    parser.add_argument(
        "--allow-mixed", action="store_true",
        help="HMAC 行と鍵なし SHA-256 行が混在するログを許容する（HMAC → SHA-256 の順で試みる）",
    )
    args = parser.parse_args()

    secret = os.getenv("AARM_RECEIPT_SECRET")
    if secret:
        print("検証モード: HMAC-SHA256 (AARM_RECEIPT_SECRET 設定済み)")
    else:
        print("検証モード: SHA-256 (AARM_RECEIPT_SECRET 未設定)")

    sys.exit(0 if verify_audit_log(args.log_file, secret=secret, allow_mixed=args.allow_mixed) else 1)


if __name__ == "__main__":
    main()
