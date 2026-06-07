# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**Laarma** は [CSA AARM 仕様](https://aarm.dev/spec) の Python プロトタイプ実装。AI エージェントのツール呼び出しを実行前にインターセプト・評価・記録する。

## セットアップ

```bash
pip install -e laarma_sdk
export ANTHROPIC_API_KEY=your_api_key
python my_project/demo.py        # 8シナリオのデモ実行
python my_project/benchmark.py   # ベンチマーク実行
```

`benchmark.py` のフラグ: `--model <model_id>`, `--pure-intent-alignment`

## ディレクトリ構成の意図

| レイヤー | ファイル | AARM 認知度 |
|---------|---------|------------|
| SDK | `laarma_sdk/src/laarma/*.py` | AARM の主体 |
| エージェント | `my_project/agent.py` | **AARM を知らない**（意図的）|
| ツール定義 | `my_project/tools.py` | `ToolRiskClass` の宣言のみ |
| エントリーポイント | `my_project/demo.py` | AARM を組み立てて注入する |
| ポリシーファイル | `my_project/policies/policy.yaml` | PAP — 静的ポリシー定義 |

## 処理フロー

```
agent.proxy.call(tool, params)
  → AARMToolProxy.call()
  → AARMRuntime.intercept()
      → PolicyEngine.evaluate()       # 静的ゲート（絶対禁止・必須パラメータ）
      → IntentAlignment.evaluate()    # LLM による動的判断 (action, C, E)
  → ALLOW/DENY/MODIFY/DEFER/STEP_UP
  → DEFER の場合: DeferralResolver.resolve() で自律再評価
  → DENY/STEP_UP の場合: ToolBlocked 例外を送出
```

## 主要モジュール

- `models.py` — Decision, ToolRiskClass, Action, SessionContext, AuthorizationResult
- `policy_engine.py` — 静的ゲート。`Policy` dataclass と `load_policy()` の入力スキーマ
- `policy_loader.py` — PAP: YAML/JSON ポリシーファイルを `Policy` に変換する
- `context_accumulator.py` — R2 コンテキスト蓄積と派生シグナル (δ) の計算
- `intent_alignment.py` — Claude LLM による (a, C, E) 評価
- `deferral.py` — DEFER 解決ワークフロー（追加コンテキスト収集 → 再評価）
- `distance_calculator.py` — セマンティック距離計算（embedding / keyword の戦略パターン）
- `runtime.py` — R1–R6 統合オーケストレーション
- `tool_proxy.py` — エージェントとツール実装の間に挟まる透過的インターセプタ

## 設計上の重要な注意点

**`ToolRiskClass` は AARM 仕様外の妥協**  
READ_ONLY/WRITE/DESTRUCTIVE による静的ツール分類は AARM 仕様に存在しない。距離計算精度が向上するまでのフォールバックとして存在する。将来的には除去される。

**`PolicyEngine` の責務は最小限**  
絶対禁止ツールのブロック・必須パラメータ検証・アクション数上限のみ。MODIFY や DEFER の判断の多くは `IntentAlignment` が担う。`PolicyEngine` が None を返した場合にのみ `IntentAlignment` へ委譲される。

**PAP の使い方**  
```python
from laarma import load_policy
policy = load_policy("my_project/policies/policy.yaml")
runtime = AARMRuntime(user_intent=..., policy=policy)
```

`AARMRuntime(policy=None)` の場合は `policy_engine.py` 内の `DEFAULT_POLICY` にフォールバックする。

## 環境変数

| 変数 | デフォルト | 説明 |
|------|---------|------|
| `ANTHROPIC_API_KEY` | — | 必須 |
| `AARM_MODEL` | `claude-sonnet-4-6` | IntentAlignment / DeferralResolver が使うモデル |
| `AARM_DISTANCE_CALCULATOR` | `embedding` | `embedding` または `keyword` |
| `AARM_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | embedding 使用時のモデル名（日本語意図文 ↔ 英語ツール名の言語間比較に多言語モデルが必要） |
