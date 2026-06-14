# 設計メモ: リスク把握はデータ分類シグナル（δ）で行う

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは laarma の**確定した設計方針**を記録する設計メモである。
> 「アクションの危険性をどう把握するか」という設計判断の正典。AARM 仕様が明言していること、
> laarma の現状、仕様の空白部分に対する laarma の設計判断を区別して記録する。
>
> **出典・ライセンス**: 本メモが参照・引用・翻訳する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。引用・翻訳は同ライセンスに基づく。

## 方針（要約）

laarma は、アクションの危険性を**固定のツールリスク等級型**として持たない。代わりに、**アクセスしたデータと文脈から動的に把握する**。これを担うのは次の2つである。

1. **`data_classification`**（派生シグナル δ の一つ） — アクセスしたデータの機密レベルを動的にラベル付けする。仕様準拠。
2. **`destructive_tools` / `sensitive_tools`**（policy 上書き可能な集合） — データ分類とスコープ判定を補助するツール名の集合。

## 1. AARM 仕様が定めること（§IV-C: 派生シグナル δ）

AARM の R2 は、コンテキスト蓄積 `Cn = Cn-1 ∪ {an, on, δn}` を要求し、δ（derived signals）に含まれるべき項目を §IV-C で挙げている。laarma が実装する δ は次の通り（`context_accumulator.py`）:

- **`data_classification`** — アクセスしたデータの機密レベル
- `semantic_distance` — 元の意図からのドリフト度
- `scope_expansion` — 想定スコープ外へのアクセス
- `entity_set` — セッション中に参照されたリソース
- `confidence_level` — 現在のアクション評価の確信度（DEFER 判断の主要トリガー）

このうち「アクションの危険性の把握」に直接寄与するのが **`data_classification`** である。仕様は「アクションが触れるデータの機密性をシグナルとして蓄積する」ことを求めており、これは**ツールに固定の危険度ラベルを貼ること**とは異なる。同じツールでも、触れるデータによって機密レベルは変わる。

## 2. laarma の実装（現状）

### data_classification: データの機密レベルを動的にラベル付け

`context_accumulator.py` の `_classify_data()` が、ツール名とパラメータの文字列から機密レベルを判定し、次のいずれか（複数可）のラベルを付ける:

- **`PII`** — 個人情報を示すキーワード（email / phone / address / ssn / customer / personal など）にマッチ
- **`CONFIDENTIAL`** — 機密を示すキーワード（secret / token / key / credential / private / internal / config など）にマッチ
- **`SENSITIVE_TOOL`** — ツール名が `sensitive_tools` 集合に含まれる
- **`PUBLIC`** — 上記いずれにも該当しない（デフォルト）

判定は**アクションごとに動的**に行われ、結果は δ として蓄積され、IntentAlignment / DeferralResolver の評価材料になる。

### destructive_tools / sensitive_tools: policy 上書き可能な補助集合

`context_accumulator.py` はツール名の集合を2つ持つ:

- **`destructive_tools`** — 破壊的操作を行うツール名（デフォルト: `delete_file` / `drop_database` / `delete_all_records` / `execute_shell`）
- **`sensitive_tools`** — 機密性の高い操作を行うツール名（デフォルト: `database` / `db` / `execute_shell` / `execute_sql`）

これらは **policy で上書き可能**である（`policy.destructive_tools` / `policy.sensitive_tools` が指定されればそれを使い、無ければデフォルト集合）。`sensitive_tools` は data_classification の `SENSITIVE_TOOL` ラベル付けに使われる。

これらは「enum 型のリスク等級」ではなく、**データ分類とスコープ判定を補助する設定値**である点が重要。固定の3段階等級ではなく、運用ごとに調整できる集合として持つ。

### confidence は「危険度」ではない（混同しないこと）

`confidence_level`（`_compute_confidence()`）は「**(a, C) を自信を持って評価できる度合い**」であり、**アクションの危険度ではない**（AARM 仕様 §IV-C）。危険度の把握は data_classification シグナルと、それを受けた IntentAlignment（STEP_UP / DENY）が担う。confidence は DEFER 判断（評価しきれないので保留）の主要トリガーであって、「危険だから低い」という性質のものではない。この区別は `context_accumulator.py` の `_compute_confidence()` の docstring にも明記されている。

## 3. 設計判断: なぜ「固定のツールリスク等級型」を持たないか

laarma は、ツールごとに `READ_ONLY` / `WRITE` / `DESTRUCTIVE` のような**静的なリスク等級を割り当てる型を持たない**。理由は次の通り。

- **ツール名から危険度が自明であり、等級型を設けて設定する意味が薄い。** `read_file` / `write_file` / `delete_file` / `drop_database` といったツール名は、それ自体が操作の性質（読み取りか、書き込みか、破壊的か）を表している。これらに改めて `READ_ONLY` / `WRITE` / `DESTRUCTIVE` のような等級を付与しても、ツール名から読み取れる情報を二重に持つだけになる。
- **等級型は二重管理と設定ミスを生む。** ツールに等級を貼ると、ツールが増えるたびに等級も付与せねばならず、付け忘れ・誤付与という失敗モードが生まれる。破壊的操作の把握が必要な場面は `destructive_tools` 集合（policy 上書き可）で足り、ツール定義側に等級メタデータを持たせる必要がない。
- **リスク等級の用途は、より適切な仕組みに分解できる。** 「破壊的か」は `destructive_tools` 集合、「機密データに触れるか」は data_classification の動的ラベル、「意図に沿うか」は IntentAlignment、と関心ごとに分かれている。単一の等級型に押し込めるより、関心の分離が保たれる。また危険性は文脈にも依存する（同じツールでも触れるデータが PII か public かで変わる）ため、固定等級だけでは AARM の文脈依存評価（R3）を表現しきれない。

したがって laarma の現在の設計は、「ツールに固定の等級型を貼る」のではなく、「ツール名・補助集合・データ分類・意図整合性」に役割を分けてリスクを把握する方向に寄せてある。

### 補足: AARM 仕様が MAY とする `risk_levels` について

なお、上記の「ツールごとの等級型を持たない」という判断は、AARM 仕様が参照を**任意（MAY）**としている `risk_levels`（リスクレベル定義）を**否定する趣旨ではない**。`risk_levels` は仕様上は採用してよい補助概念だが、laarma では**まだ詳細に検討できておらず、導入していない**だけである。将来、文脈依存評価（data_classification / IntentAlignment）を補完する形で `risk_levels` を導入する余地は残されている。導入を検討する際は、本メモの「等級型は二重管理と設定ミスを生む」という観点との整合を取ること。

## 関連

- `laarma_sdk/src/laarma/context_accumulator.py` の `_classify_data()`、`_DEFAULT_*` 集合、`_compute_confidence()`
- `laarma_sdk/src/laarma/models.py` の `Policy`（`destructive_tools` / `sensitive_tools` / `pii_keywords` / `confidential_keywords` の上書きフィールド）
- 提案/上書きモデル（PolicyEngine と IntentAlignment の関係）: [policy-engine-proposal-override.md](policy-engine-proposal-override.md)
- README の仕様準拠状況: R2（コンテキスト蓄積）
