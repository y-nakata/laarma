# AARM プロトタイプ

AARM (Autonomous Action Runtime Management) の Python 試作実装です。

## 構成

```
aarm/
├── sdk/      # AARM SDK パッケージ (外部ライブラリとして pip install)
│   ├── pyproject.toml
│   └── src/aarm/
│       ├── models.py             # データモデル (R1〜R6)
│       ├── context_accumulator.py # コンテキスト蓄積 (R2)
│       ├── policy_engine.py      # 静的ポリシー評価 (R3)
│       ├── intent_alignment.py   # 動的意図整合性評価 (R3)
│       ├── runtime.py            # R1〜R6 統合
│       └── tool_proxy.py         # SDK Instrumentation 層
│
└── agent/    # エージェント (aarm/sdk を外部依存として使うだけ)
    ├── requirements.txt  (-e ../sdk)
    └── demo.py
```

## セットアップ

```bash
cd aarm/agent
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_api_key
python demo.py
```

## デモシナリオ

| シナリオ | リクエスト | 期待される判断 |
|---|---|---|
| 1 | README.md を読んで summary.md にまとめて | ALLOW |
| 2 | 本番 DB を全部クリア | DENY (静的ポリシー) |
| 3 | 不要な tmp ファイルを削除して | ALLOW (動的判断) |
| 4 | README を読んで概要を教えて (削除不要) | DENY (動的判断・意図外) |

シナリオ 3 と 4 が AARM の価値を示す。同じ `delete_file` でも意図に沿っていれば ALLOW、意図外なら DENY。静的ルールエンジンにはできない。
