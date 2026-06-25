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

## 安定性計測（--repeat）

pipeline モードでは、ケースごとに IntentAlignment（LLM）が実際に呼ばれたかをベンチマーク側で計測し、呼ばれたケースのみ `--repeat`（デフォルト3）回繰り返し実行します。IntentAlignment を呼ばずに確定するケース（denied_tools / privilege_scope / 静的 DENY ルールで終端するもの）は1回のみ実行され、他モードの挙動も変わりません。

```bash
# 繰り返し回数を変更
python my_project/benchmark.py --repeat 5
```

各ケースは繰り返し実行の結果に応じて次のいずれかに分類されます:

- **stable_pass**: 全回 pass。`pass` に加算。
- **stable_fail**: 全回 fail。`fail` に加算（informational 該当時を除く）。
- **mixed（不安定）**: pass/fail が混在。`unstable` に加算し、`fail` とは区別する（揺れは期待値の誤りと同一視しない。終了コードにも影響しない）。サマリ末尾の「Unstable cases」に `pass_n/total_n` 付きで列挙されます。

informational 扱い（fail に数えないが実際の decision は表示するもの）も2系統に分けて表示されます:

- **PolicyEngine pass-through**: policy-engine モードで ALLOW（pass-through）が返ったが期待値が DENY/STEP_UP/DEFER のケース。IntentAlignment が担うべき判断であり、PolicyEngine の正常動作。
- **pipeline_informational cases**: `expected_decision` の検証が policy-engine モードを主とするケース（例: `defer_production_delete`）。pipeline での不一致は実際の decision（`actual=...`）付きで一覧化される。

なぜこの基盤（benchmark.py のシナリオ追加）でテストするか、という設計判断は [docs/design/laarma-testing-infrastructure.md](design/laarma-testing-infrastructure.md) を参照。
