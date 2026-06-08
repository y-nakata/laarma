# 監査ログ（Receipt）の永続化と改ざんチェック

[← README に戻る](../README.md)

## 永続化

`AARM_AUDIT_LOG_PATH` を設定すると、全インターセプト結果を JSONL 形式でアペンド保存します。

```bash
export AARM_AUDIT_LOG_PATH=./aarm_audit.jsonl
python my_project/demo.py
```

各行は `AuthorizationResult.to_dict()` のシリアライズ結果です:

```json
{
  "receipt_id": "...",
  "receipt_hash": "sha256...",
  "session_id": "sess_demo",
  "decision": "DENY",
  "reason": "意図外の削除操作のため遮断。",
  "action": {"tool_name": "delete_file", "parameters": {"path": "tmp.txt"}, "...": "..."},
  "modified_params": null,
  "timestamp": "2026-06-07T12:00:00+00:00",
  "resolution_method": null
}
```

`resolution_method` の値:

| 値 | 意味 |
|---|---|
| `null` | 直接判断（DEFER/STEP_UP 経由なし） |
| `"autonomous"` | DeferralResolver が自律解決（ALLOW/DENY） |
| `"step_up"` | DeferralResolver が STEP_UP へ格上げ |
| `"human_approved"` | StepUpResolver で人間が承認 |
| `"human_denied"` | StepUpResolver で人間が拒否 |

メモリ内のレシートは `runtime.receipts`（`list[dict]`）で参照できます。

## HMAC 署名鍵（AARM_HMAC_SECRET）

`receipt_hash` と `identity_token` は、`AARM_HMAC_SECRET` が設定されていれば HMAC-SHA256 で計算されます。未設定時は鍵なし SHA-256 にフォールバックし、警告が出ます。

### 鍵の生成

暗号的にランダムな 32 バイト（64 文字の 16 進）を鍵に使います。

```bash
# どちらか
openssl rand -hex 32
python -c "import secrets; print(secrets.token_hex(32))"
```

### 設定

```bash
export AARM_HMAC_SECRET=<生成した64文字>
python my_project/demo.py
```

> **鍵は固定して使い続けること。** HMAC は鍵に紐づくため、鍵を変えると、それ以前に生成したレシートのハッシュは検証できなくなります。`export AARM_HMAC_SECRET=$(openssl rand -hex 32)` のようにコマンド置換で都度生成すると、ターミナルを開き直すたびに別の鍵になる点に注意。固定したい場合は、生成した値を `.env` 等に保存して使います。

> **`.env` に書く場合は `.gitignore` 対象であることを確認してください。** 本リポジトリは public のため、鍵をコミットすると漏洩します。

> **生成途中での鍵設定に注意。** 鍵を設定する前後で監査ログを生成すると、鍵なし SHA-256 の行と HMAC の行が混在します。検証時は同じ鍵を設定した状態で行ってください。

## 改ざんチェック

```bash
python my_project/check_audit_log.py aarm_audit.jsonl
```

各エントリの `receipt_hash` を再計算して一致を検証します（終了コード 1 で不一致報告）。

> **注: `AARM_HMAC_SECRET` 未設定時の限界**
> `AARM_HMAC_SECRET` が未設定の場合、`receipt_hash` は鍵なし SHA-256 で計算されるため、
> 攻撃者が同じアルゴリズムでハッシュを再計算・差し替えた場合の改ざんは検出できません。
> 本番環境では必ず `AARM_HMAC_SECRET` を設定してください。
