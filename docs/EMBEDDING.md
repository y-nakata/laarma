# Embedding モデルの切り替え

[← README に戻る](../README.md)

`AARM_EMBEDDING_MODEL` で sentence-transformers の任意のモデルに切り替えられます。

```bash
export AARM_EMBEDDING_MODEL=paraphrase-multilingual-mpnet-base-v2
python my_project/demo.py
```

## 動作確認済みモデルと比較

以下は日本語の意図文と英語のツール名で測定した semantic distance の比較です（距離 0.0=一致 / 1.0=無関係）。

| 意図文 | ツール | MiniLM-L12-v2 (デフォルト) | mpnet-base-v2 | 正解方向 |
|---|---|---|---|---|
| 不要なファイルを削除して | delete_file | **0.323** | 0.312 | 低いほど良い |
| README を読んで教えて | delete_file | 0.545 | **0.660** | 高いほど良い（意図外検知） |
| ファイルに書き出して | write_file | **0.365** | 0.522 | 低いほど良い |
| README を読んで教えて | read_file | **0.337** | 0.352 | 低いほど良い |
| メールを送って | send_email | **0.296** | 0.391 | 低いほど良い |
| メールを送って | delete_file | **0.919** | 0.823 | 高いほど良い（意図外検知） |

mpnet は意図外操作の検知感度が高い一方、日本語意図文 ↔ 英語ツール名の正方向マッピング精度は MiniLM がやや優勢。デフォルトは MiniLM を維持。
