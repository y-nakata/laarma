# ベンチマーク

[← README に戻る](../README.md)

`my_project/benchmark.py` と `my_project/benchmark_data.jsonl` を使って、各層の挙動を評価できます。

```bash
pip install -e laarma_sdk
export ANTHROPIC_API_KEY=your_api_key
python my_project/benchmark.py
```

3 つのモードで層を独立して評価できます:

| モード | フラグ | LLM | 用途 |
|-------|-------|-----|------|
| `pipeline`（デフォルト） | なし | あり | PolicyEngine + IntentAlignment 結合テスト |
| `policy-engine` | `--mode policy-engine` | なし（高速） | 静的ルールの決定論的回帰テスト |
| `intent-alignment` | `--pure-intent-alignment` | あり | LLM の生の意図判断精度測定（不一致は情報的出力のみ） |

```bash
# モデルを指定
python my_project/benchmark.py --model claude-sonnet-4-6

# 静的ルールのみ（LLM コールなし）
python my_project/benchmark.py --mode policy-engine

# LLM の生判断を測定
python my_project/benchmark.py --pure-intent-alignment
```
