# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

**Laarma** は [CSA AARM 仕様](https://aarm.dev/spec) の Python プロトタイプ実装。AI エージェントのツール呼び出しを実行前にインターセプト・評価・記録する。

> **設計方針の正典は `docs/design/` の設計メモ**。本ファイル（CLAUDE.md）の記述と設計メモが食い違う場合は、**設計メモを優先**し、その相違を報告すること。本ファイルは設計メモの内容を実装作業向けに要約・参照するものであり、方針転換の直後などに一時的に古くなっている可能性がある。

## セットアップ

```bash
pip install -e laarma_sdk
export ANTHROPIC_API_KEY=your_api_key
python my_project/demo.py        # 9シナリオのデモ実行
python my_project/benchmark.py   # ベンチマーク実行
```

`benchmark.py` のフラグ: `--model <model_id>`, `--mode <pipeline|policy-engine|intent-alignment>`

## ディレクトリ構成の意図

| レイヤー | ファイル | AARM 認知度 |
|---------|---------|------------|
| SDK | `laarma_sdk/src/laarma/*.py` | AARM の主体 |
| エージェント | `my_project/agent.py` | **AARM を知らない**（意図的）|
| ツール定義 | `my_project/tools.py` | ツールスキーマと実装のみ（リスク分類などの AARM 概念は持たない）|
| エントリーポイント | `my_project/demo.py` | AARM を組み立てて注入する |
| ポリシーファイル | `my_project/policies/policy.yaml` | PAP — 静的ポリシー定義 |

## 処理フロー

```
agent.proxy.call(tool, params)
  → AARMToolProxy.call()
  → AARMRuntime.intercept()
      → PolicyEngine.evaluate(a, C, E)   # 式(3)の π を実現する単一の評価関数
          # 内部で静的ルールを収束まで評価し、必要に応じて IntentAlignment に確認する
          # （IntentAlignment は PolicyEngine の内部協力者。runtime からは見えない）
  → ALLOW/DENY/MODIFY/DEFER/STEP_UP   # evaluate() は常に terminal な結果を返す
  → DEFER の場合: DeferralResolver.resolve() で自律再評価（ALLOW/DENY/STEP_UP に収束）
  → STEP_UP の場合: StepUpResolver で人間承認（承認: ALLOW / 拒否: DENY）
  → DENY/STEP_UP 拒否の場合: ToolBlocked 例外を送出
```

## 主要モジュール

- `models.py` — Decision, Action, IdentityContext, SessionContext, AuthorizationResult
- `policy_engine.py` — 式(3)の π。静的ルール評価 + 内部協力者 IntentAlignment による意図確認（提案/上書きモデル）
- `policy_loader.py` — PAP: YAML/JSON ポリシーファイルを `Policy` に変換する
- `context_accumulator.py` — R2 コンテキスト蓄積と派生シグナル (δ) の計算（data_classification / semantic_distance / scope_expansion / entity_set / confidence_level）
- `intent_alignment.py` — Claude LLM による (a, C, E) 評価
- `deferral.py` — DEFER 解決ワークフロー（追加コンテキスト収集 → 再評価）
- `step_up_resolver.py` — STEP_UP 人間承認ワークフロー
- `distance_calculator.py` — セマンティック距離計算（embedding / keyword の戦略パターン）
- `environment.py` — EnvironmentContext / MaintenanceWindow（環境・タイミング条件）
- `runtime.py` — R1–R6 統合オーケストレーション
- `tool_proxy.py` — エージェントとツール実装の間に挟まる透過的インターセプタ

## 設計上の重要な注意点

**リスク把握はデータ分類シグナル（δ）で行う。静的なツールリスク等級の型は持たない**
かつて存在した `ToolRiskClass`（READ_ONLY/WRITE/DESTRUCTIVE の enum）は**除去済み**。現在、アクションの危険性の把握は次の2つが担う:
- **`data_classification`**（`context_accumulator.py` の `_classify_data`）— アクセスしたデータの機密レベル（PII / CONFIDENTIAL / SENSITIVE_TOOL / PUBLIC）を、ツール名とパラメータの文字列から動的にラベル付けする。これは AARM §IV-C の派生シグナル δ の一つであり**仕様準拠**。
- **`destructive_tools` / `sensitive_tools`**（`context_accumulator.py` のデフォルト frozenset、policy で上書き可能）— ツール名の集合。データ分類とスコープ判定の補助に使う設定値であって、enum 型のリスク等級ではない。

つまり「ツールに固定のリスク等級を持たせる」のではなく、「アクセスしたデータと文脈からリスクを動的に把握する」方向に寄せてある。新たに静的なツールリスク型を再導入しないこと。

**`PolicyEngine` は R3・式(3) の π そのもの（提案/上書きモデル）**
`PolicyEngine.evaluate(a, C, E)` は式(3) `π:(a,C)→{ALLOW,DENY,MODIFY,STEP_UP,DEFER}` を完全に実現する単一の関数であり、常に terminal な `AuthorizationResult` を返す。`IntentAlignment` は別レイヤーではなく **`PolicyEngine` の内部協力者**（コンストラクタ注入）。`runtime.intercept()` は `evaluate()` を呼ぶだけで、`IntentAlignment` を直接は知らない。

内部ロジック（詳細は `docs/design/policy-engine-modify.md`）:
- 静的ルールを**マッチするルールが無くなるまで収束評価**する（MODIFY なら変換して再評価、`max_modify_iterations` で上限・到達時 DENY）。
- **`decision == DENY` のみ terminal**（IntentAlignment 不要）。それ以外（ALLOW/MODIFY/DEFER/STEP_UP・暗黙 ALLOW）は「提案」として IntentAlignment に確認し、ALLOW なら確定・それ以外なら上書き（`proposed_decision` に元の提案を記録）。
- IntentAlignment に渡すアクションは `modified_params` の有無で決める（変換済みなら a'、なければ a）。

> この方針は設計メモ `docs/design/policy-engine-modify.md` で確定済み。`PolicyEngine` 周辺を変更するときは、まず同メモを参照すること。

**PAP の使い方**
```python
from laarma import load_policy
policy = load_policy("my_project/policies/policy.yaml")
runtime = AARMRuntime(user_intent=..., policy=policy)
```

`AARMRuntime(policy=None)` の場合は `policy_engine.py` 内の `DEFAULT_POLICY` にフォールバックする。

## テストの方針

**回帰・シナリオテストは `my_project/benchmark.py` のシナリオ追加で行う（新たに pytest 等のテストファイルを作らない）。**

理由と背景:
- laarma の回帰検証は「ある (user_intent, action, environment) に対して期待する decision が出るか」という形をしており、これは `benchmark_data.jsonl` へのケース追加 + `benchmark.py` の実行で表現される。
- 意図整合性の検証は LLM 呼び出しを伴う（`pipeline_only` ケース）。純粋な単体テストの枠組みより、`benchmark.py` のモード分け（`pipeline` / `policy-engine` / `intent-alignment`）に乗せる方が、この設計と整合する。別のテスト基盤を立てると二重管理になる。
- 新しい回帰ケースを追加するときは、`benchmark_data.jsonl` にケースを足し、LLM 判断が必須なものには `pipeline_only: true` を付ける。

**クラス・関数レベルの単体テスト（pytest 等）は現時点では導入しない。** ただし将来的な導入の余地は残す。判断基準:
- 現状はプロトタイプ段階で、AARM 仕様の精査が完了しておらず、`PolicyEngine` の大規模リファクタリングのような変更が今後も発生しうる。この段階でクラス・関数レベルの単体テストを実装すると、ソース変更のたびにテスト改修コストが乗り、変更を重くする。そのコストを正当化するだけのメリット（デグレ防止の確実性）が、まだ無い。
- 単体テスト・カバレッジ計測・リファクタリング用テストハーネスの構築は、**コードが安定し、かつ本番リリース後でデグレによる不具合を絶対に避けたいという要件が出てきた段階**で初めてコストが正当化される。そうなったら、SDK 内部の純粋ロジック（収束ループ、`_match_conditions`、変換レジストリなど LLM 非依存の部分）から pytest を導入するのが妥当。
- それまでは benchmark.py に一本化する。**新しいテストフレームワークを導入したくなったら、実装に入る前に相談すること**（プロトタイプ段階でテスト基盤を分散させない）。

## 環境変数

| 変数 | デフォルト | 説明 |
|------|---------|------|
| `ANTHROPIC_API_KEY` | — | 必須 |
| `AARM_MODEL` | `claude-sonnet-4-6` | IntentAlignment / DeferralResolver が使うモデル |
| `AARM_DISTANCE_CALCULATOR` | `embedding` | `embedding` または `keyword` |
| `AARM_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | embedding 使用時のモデル名（日本語意図文 ↔ 英語ツール名の言語間比較に多言語モデルが必要） |
| `AARM_HMAC_SECRET` | — | レシートの tamper-evidence と identity 署名に使う HMAC 鍵。セッション間で固定すること（再生成すると過去レシートの検証が壊れる）。`.env` で管理し gitignore する |
| `HF_TOKEN` | — | Hugging Face 認証トークン。設定すると HF Hub への認証済みリクエストになり未認証警告が消える |
