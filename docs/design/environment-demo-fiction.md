# 設計メモ: 環境要件 E は汎用仕様化せず、デモフィクションとして踏襲する

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは laarma の**確定した設計方針**を記録する設計メモである。
> 「環境要件を参照するポリシーを laarma がどう扱うか」という設計判断の正典であり、#110 の結論を記録する。
> AARM 仕様が明言していること、laarma の現状（AS IS）、AARM 仕様外の laarma 独自拡張に対する設計判断を区別して記録する。
> 論文が環境 E を評価入力から外していることの読みは `docs/aarm/environment-and-context.md` にあり、本メモはそれを受けた laarma 側の応答を扱う。
>
> **出典・ライセンス**: 本メモが参照・引用・翻訳する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。引用・翻訳は同ライセンスに基づく。

## 方針（要約）

laarma は、環境要件（本番か否か、メンテナンスウィンドウ内外か等）を参照するポリシーを、**汎用の (a, C, E) 仕様として定式化しない**。現行 `policy_engine.py` の環境条件（`EnvironmentContext` 引数、`environment_type` / `not_in_maintenance_window`）は、撤去も汎用化もせず、**デモフィクションとして明示的に踏襲する**。実運用の環境ゲーティングは AARM/laarma の外（インフラ）の領分である。

## 1. AARM 仕様が定めること

AARM のポリシーは π:(a, C)（式3）。環境 E は評価入力ではなく effect の作用先としてのみ形式化され、コンテキスト C にも派生信号 δ にも含まれず、π からも参照されない。詳細な一次資料の読みは [`../aarm/environment-and-context.md`](../aarm/environment-and-context.md) にある。したがって環境要件を参照するポリシーは素の AARM には行き場がなく、それを支えるなら AARM の (a, C) を超える laarma 独自拡張になる。

## 2. laarma の実装（現状 = AS IS）

現行 `laarma_sdk/src/laarma/policy_engine.py` は、環境要件を評価に取り込む拡張を既に実装している。

- `PolicyEngine.evaluate(action, context, context_summary, environment: EnvironmentContext | None)` — `environment` は C（`SessionContext`）とは別の第4引数として渡される。
- `_match_conditions` が次の二条件で E を参照する（いずれも `EnvironmentContext` 由来）:
  - `environment_type` → `EnvironmentContext.environment`
  - `not_in_maintenance_window` → `EnvironmentContext.in_maintenance_window()`
- `evaluate()` の docstring は「式(3)の π として (a, C, E) を評価」と自己記述する。

すなわち laarma は E を out-of-band の第三要素として評価に差し込む拡張を AS IS で行っており、これは AARM の (a, C) からの逸脱＝laarma 独自拡張である。`docs/aarm/environment-and-context.md` が記録した「E は評価入力でない」という論文の読みと噛み合わない部分である。

## 3. この E はデモフィクションである

上記の環境条件は、実運用の権威的な環境読み取りを伴わない。`in_maintenance_window()` 等は、実際の保守窓スケジュールを E から権威的に読むのではなく、注入された `EnvironmentContext` に対する判定にすぎない。これは AARM 論文にあった環境要件の記述（Context-Dependent Defer のメンテナンスウィンドウ例など）を、デモとして体裁だけ体現したものであり、汎用仕様として通用するものではない。

## 4. 設計判断: 汎用仕様化せず、デモフィクションとして踏襲する

### 汎用仕様としての環境要件 E は定式化しない

環境要件は E ごとに固有で、任意の E に通用する有限の信号集合として汎用に定式化できない。特定システムに特化すればその環境要件は定式化可能だが、laarma でそれをやる動機はない。laarma は特定システム向けの環境ゲーティング製品ではなく、AARM の (a, C) 評価を実装するプロトタイプである。

### 撤去もしない

現行の環境条件は撤去しない。AARM 論文にあった環境要件の記述をデモとして示す価値があり、削るとその参照が失われる。

### 「デモフィクション」として明示的にラベルする

撤去も汎用化もせず、現状を**デモフィクション**として明示的にラベルして踏襲する。これにより、AS IS の (a, C, E) が「汎用の環境評価能力」の主張と取り違えられることを防ぐ。AS IS の (a, C, E) は AARM (a, C) からの逸脱として残るが、汎用能力を主張するものではない。

### 実運用の環境ゲーティングはインフラの領分

実運用で環境依存のゲーティングが要るなら、それは AARM/laarma の外（インフラ）で行う。これは `docs/aarm/environment-and-context.md` §6 が読み解いた V.C.4 の admission sentence（環境操作対策は AARM の session-level 制御を超える complementary infrastructure-level protections を要する）と整合する。

## 関連

- `laarma_sdk/src/laarma/policy_engine.py`（`evaluate` の `environment` 引数、`_match_conditions` の `environment_type` / `not_in_maintenance_window`）
- `laarma_sdk/src/laarma/environment.py`（`EnvironmentContext`、`in_maintenance_window()`）
- [`../aarm/environment-and-context.md`](../aarm/environment-and-context.md)（AARM が E を評価入力から外していることの一次資料読み。E 除外が意図的な線引きである可能性も §5 に記録）
- 関連 Issue: #110（本判断を詰めた検討 issue）、#87（起点。not_planned でクローズ）
