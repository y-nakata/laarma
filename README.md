# AARM プロトタイプ

AARM (Autonomous Action Runtime Management) のシンプルな Python 試作です。
Cloud Security Alliance の [AARM 仕様](https://cloudsecurityalliance.org/research/working-groups/autonomous-action-runtime-management-aarm) に基づき、AI エージェントのアクションを実行前にインターセプト・評価・記録するランタイムを実装します。

## 構成

```
aarm/
├── models.py              # Step 1: データモデルとコア定数
├── context_accumulator.py # Step 2: コンテキスト蓄積
├── policy_engine.py       # Step 3: 静的ポリシー評価
├── intent_alignment.py    # Step 4: Claude による意図整傐性評価
├── runtime.py             # Step 5: 全コンポーネントの統合
├── demo.py                # Step 6: エージェント接続デモ
└── requirements.txt
```

## AARM の処理フロー

```
エージェントがツールを呼び出そうとする
        ↓
  [AARM] intercept()
        ↓
  Context Accumulator に記録
        ↓
  Policy Engine で静的評価
   ║ 引っかかった→ DENY / STEP_UP / DEFER を返す
   ║ 通過↓
  Intent Alignment で Claude が評価
        ↓
  ALLOW / DENY / DEFER / STEP_UP を返す
        ↓
  レシートログに記録
```

## セットアップ

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_api_key
```

## デモの実行

```bash
python demo.py
```

3つのシナリオが順番に実行されます。

| シナリオ | リクエスト | 期待される判断 |
|---|---|---|
| 1 | README.md を読んで summary.md に書き出す | ALLOW |
| 2 | 本番 DB を全部クリア | DENY |
| 3 | 古いログファイルを削除 | STEP_UP |

## 使い方 (コードから使う)

```python
from aarm import AARMRuntime, Decision

runtime = AARMRuntime(user_intent="テストデータを整理してレポートを作る")

result = runtime.intercept("write_file", {"path": "report.md", "content": "..."})

if result.decision == Decision.ALLOW:
    # ツールを実行する
    output = run_tool(...)
    runtime.record_tool_output(result.action.action_id, output)
else:
    print(f"[{result.decision.value}] {result.reason}")
```
