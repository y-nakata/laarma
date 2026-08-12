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
| `AARM_MODEL` | `claude-sonnet-4-6` | `confidence_llm`/`scope_expansion_llm`/`action_matches_intent_llm` の各 LLM 検出層が使うモデル（`DeferralResolver` は #135 で LLM 呼び出しを除去したため対象外） |
| `AARM_LLM_TIMEOUT` | `30` | LLM 呼び出しタイムアウト（秒） |
| `AARM_LLM_MAX_RETRIES` | `3` | LLM 呼び出し失敗時の最大リトライ回数 |
| `AARM_DISTANCE_CALCULATOR` | `embedding` | `embedding` または `keyword`。詳細は [EMBEDDING.md](EMBEDDING.md) |
| `AARM_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | embedding 使用時のモデル名。日本語の意図文と英語のツール名を言語間で比較するため多言語モデルが必要 |
| `AARM_AUDIT_LOG_PATH` | — | 監査ログ（Receipt）の出力先ファイルパス（省略で永続化なし）。詳細は [AUDIT.md](AUDIT.md) |
| `AARM_RECEIPT_SECRET` | — | receipt_hash の HMAC-SHA256 署名鍵。未設定時は警告のみ（フォールバック: 鍵なし SHA-256）。詳細は [AUDIT.md](AUDIT.md) |
| `AARM_IDENTITY_PUBKEY_DIR` | — | Human/Agent/Service の Ed25519 公開鍵（`{principal}.pub`）を置くディレクトリ。未設定時は identity 署名検証をスキップ。設定時、検証に失敗すると PolicyEngine が DENY する（R6 MUST、#55 PR-4）。詳細は [AUDIT.md](AUDIT.md) |
| `HF_TOKEN` | — | Hugging Face 認証トークン。設定すると HF Hub への認証済みリクエストになり未認証警告が消える（未設定でもダウンロード・動作は可能） |
| `AARM_DEMO_DETERMINISTIC_SAMPLE` | — | `my_project/demo.py` 専用（laarma_sdk 本体には無関係）。`1` を設定すると `confidence_llm`（`SemanticAmbiguityDetector`）を `NullConfidenceLLM` に差し替え、低確率の誤検知による decision の揺れを止める。`my_project/demo_output_sample.txt`（参照出力）の再生成時のみ使う想定で、通常のデモ実行では設定しない |

`ANTHROPIC_API_KEY` は `AARMRuntime` をデフォルト構成（`confidence_llm` 未指定）のまま使う限り実質必須である。confidence の LLM 検出層（`SemanticAmbiguityDetector`, #112 Phase C）は毎アクション LLM を呼ぶ設計のため、`ANTHROPIC_API_KEY` 未設定のまま使うと毎アクションで LLM 呼び出しが失敗し、fail-closed で confidence が常時大きく減点される（`_LLM_PENALTY=0.5`）。結果として STEP_UP/DEFER に倒れやすくなる——これは「LLM 不達時は confidence を下げる」という設計方針どおりの挙動であり、バグではない。
