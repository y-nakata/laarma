# セットアップ

[← README に戻る](../README.md)

```bash
pip install -e laarma_sdk
export ANTHROPIC_API_KEY=your_api_key
python my_project/demo.py
```

## 環境変数

| 変数 | デフォルト | 説明 |
|------|---------|------|
| `ANTHROPIC_API_KEY` | — | 必須 |
| `AARM_MODEL` | `claude-sonnet-4-6` | IntentAlignment / DeferralResolver が使うモデル |
| `AARM_LLM_TIMEOUT` | `30` | LLM 呼び出しタイムアウト（秒） |
| `AARM_LLM_MAX_RETRIES` | `3` | LLM 呼び出し失敗時の最大リトライ回数 |
| `AARM_DISTANCE_CALCULATOR` | `embedding` | `embedding` または `keyword`。詳細は [EMBEDDING.md](EMBEDDING.md) |
| `AARM_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | embedding 使用時のモデル名。日本語の意図文と英語のツール名を言語間で比較するため多言語モデルが必要 |
| `AARM_AUDIT_LOG_PATH` | — | 監査ログ（Receipt）の出力先ファイルパス（省略で永続化なし）。詳細は [AUDIT.md](AUDIT.md) |
| `AARM_RECEIPT_SECRET` | — | receipt_hash の HMAC-SHA256 署名鍵。未設定時は警告のみ（フォールバック: 鍵なし SHA-256）。詳細は [AUDIT.md](AUDIT.md) |
| `AARM_IDENTITY_SECRET` | — | identity_token の HMAC-SHA256 署名鍵。未設定時は identity 検証をスキップ（警告のみ）。詳細は [AUDIT.md](AUDIT.md) |
| `HF_TOKEN` | — | Hugging Face 認証トークン。設定すると HF Hub への認証済みリクエストになり未認証警告が消える（未設定でもダウンロード・動作は可能） |
