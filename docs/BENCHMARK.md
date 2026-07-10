# ベンチマーク

[← README に戻る](../README.md)

`my_project/benchmark.py` と `my_project/benchmark_data.jsonl` を使って、`PolicyEngine` の挙動を評価できます。

`PolicyEngine.evaluate()` は LLM を呼ばない決定論的な評価エンジンのため（#112 Phase A で LLM ベースの決定判定コンポーネントを除去済み）、API キーは不要です。

```bash
pip install -e laarma_sdk
python my_project/benchmark.py
```

```bash
# 詳細出力（各ケースの semantic_distance / confidence / data_classifications も表示）
python my_project/benchmark.py --verbose
```

## known_regression_until（既知の回帰の追跡）

一部のケースは、意図整合性判定（旧 LLM ベース IntentAlignment）が担っていた判断を検証する意図で書かれており、その判断は δ(semantic_distance・data_classification・confidence) を参照するポリシー条件が実装されるまで(#112 Phase B)再現されない。これらのケースには `known_regression_until` フィールドが立っており、`expected_decision` とのミスマッチは fail ではなく informational として扱われる（サマリの `informational` に加算され、末尾に `actual` 付きで一覧化される）。

なぜこの基盤（benchmark.py のシナリオ追加）でテストするか、という設計判断は [docs/design/laarma-testing-infrastructure.md](design/laarma-testing-infrastructure.md) を参照。
