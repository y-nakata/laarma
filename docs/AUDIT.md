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

## receipt の HMAC 署名鍵（AARM_RECEIPT_SECRET）

`receipt_hash`（改ざん検知）は `AARM_RECEIPT_SECRET` の HMAC-SHA256 鍵で保護されます。
未設定時は鍵なし SHA-256 にフォールバックし、警告が出ます。

identity の署名（non-repudiation）は別レイヤーで、HMAC 共有鍵ではなく
**Human/Agent/Service 各主体の Ed25519 鍵**を使う（次節「identity 署名（Ed25519）」参照）。

### 鍵の生成と設定

暗号的にランダムな 32 バイト（64 文字の 16 進）を鍵に使います。

```bash
export AARM_RECEIPT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
# または
export AARM_RECEIPT_SECRET=$(openssl rand -hex 32)
```

**重要な注意点**:
- 鍵は**固定して使い続ける**必要があります。HMAC は鍵に紐づくため、鍵を変えると過去のレシートの `receipt_hash` が検証できなくなります。上記の `$(...)` は実行のたびに別の鍵を生成するため、固定したい場合は生成した値を `.env` 等に保存して使います。
- `.env` ファイルに保存する場合は `.gitignore` に追加してください（公開リポジトリへの漏洩防止）。
- ログ生成途中で `AARM_RECEIPT_SECRET` を設定・変更すると、鍵なし SHA-256 行と HMAC 行が混在します。混在ログの検証は `--allow-mixed` オプションを使用してください。

## identity 署名（Ed25519）

`IdentityContext` は Human（依頼者）/ Agent（実行者）/ Service（調停者）の3主体それぞれの
Ed25519 鍵で署名する（`human_signature` / `agent_signature` / `service_signature`）。
Human・Agent は自分の層のみを個別署名し、Service は3層全体＋`privilege_scope` を束ねた
包括署名を行う。詳細は [docs/design/identity-signing.md](design/identity-signing.md) §3〜§4。

- laarma SDK は秘密鍵を生成・保管しない（検証者であって発行者ではない）。鍵の生成は
  呼び出し側（このプロトタイプでは `my_project/identity_keys.py`）が担う。
- `AARM_IDENTITY_PUBKEY_DIR` に、各主体の公開鍵 PEM を **principal の値そのものをファイル名**
  にして置く（例: `alice@example.com.pub`, `agent-svc@iam.pub`）。`AARMRuntime` がこの値で
  ファイルを探して検証する。
- ディレクトリ未設定、または該当ファイルが無い場合は従来どおり警告のみで処理を続行する
  （deny/flag はしない。これは PR-4 の領分）。
- デモ・ベンチマークでは `my_project/identity_keys.py` の `load_or_create_keypair()` が
  `keys/` 配下に鍵が無ければ自己生成する（第1段階・CA なし）。`keys/` は `.gitignore` 済みで
  コミットされない。

## 改ざんチェック

```bash
# 鍵なし（SHA-256 で検証）
python -m laarma.audit aarm_audit.jsonl

# 鍵あり（HMAC-SHA256 で検証）
AARM_RECEIPT_SECRET=your_secret python -m laarma.audit aarm_audit.jsonl

# 混在ログ（鍵あり行・鍵なし行が混在する場合）
AARM_RECEIPT_SECRET=your_secret python -m laarma.audit --allow-mixed aarm_audit.jsonl
```

各エントリの `receipt_hash` を再計算して一致を検証します（終了コード 1 で不一致報告）。
検証に使うのは `AARM_RECEIPT_SECRET` のみ（identity 署名とは無関係な別レイヤー）。

> **注: `AARM_RECEIPT_SECRET` 未設定時の限界**
> `AARM_RECEIPT_SECRET` が未設定の場合、`receipt_hash` は鍵なし SHA-256 で計算されるため、
> 攻撃者が同じアルゴリズムでハッシュを再計算・差し替えた場合の改ざんは検出できません。
> 本番環境では必ず `AARM_RECEIPT_SECRET` を設定してください。
