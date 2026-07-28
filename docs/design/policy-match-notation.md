# 設計メモ: ポリシー match 記法の選択（Phase B の δ 参照記法）

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは laarma の**設計判断**を記録する設計メモである。#112 Phase B で
> match predicate に δ（semantic_distance・data_classification・confidence）参照を足すにあたり、
> その記法を AARM 論文・aarm.dev 公式ガイド・laarma 現行のどれに、どこまで寄せるかを決める。
>
> **論文の記述と laarma の判断の区別**: 論文・公式ガイドが実際にどう書いているか（記法の事実）は
> 引用・要約として示し、そこから先の「laarma がどの記法を採るか」の判断と区別する。論文の記法解釈で
> 恒久的な正典に属する部分は [docs/aarm/classification-and-policy-model.md](../aarm/classification-and-policy-model.md)
> の Policy Structure（式3）を参照する。
>
> **出典・ライセンス**: AARM 論文（Autonomous Action Runtime Management, Herman Errico,
> Cloud Security Alliance, 2026, arXiv:2602.09433）は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。
> aarm.dev 公式ドキュメント（github.com/aarm-dev/docs）は参考として参照する。

---

## 1. 目的

#112 Phase A で決定層を priority 解決エンジンに組み替えたが、match predicate が参照するのは
現状 `tool` / `environment_type` / `not_in_maintenance_window` / `param_matches` に限られる。
Phase B では、意図整合性の判定を担う δ（semantic_distance・data_classification・confidence）を
match predicate が参照できるようにする。その際の**記法**を、独自に決める前に、AARM 論文と
aarm.dev 公式ガイドの既存記法と対照し、寄せられるところは寄せる（車輪の再発明とエコシステム乖離を避ける）。

なお **match の意味論**（複数条件の結合）は laarma 現行の AND 連言をそのまま踏襲する。本メモが選ぶのは
「δ をどの区画にどう書くか」という記法であって、意味論の変更ではない。

---

## 2. 三者対照

### 【論文】δ の定義（式2）と match 記法（規範）

まず δ の定義を確認する。論文 IV. PROBLEM FORMALIZATION の式(2) は、Context Accumulator が保つ
コンテキスト C を `Cn = Cn−1 ∪ {an, on, δn}` と定め、δ を5つの派生シグナルの集合とする:

- **Data classification**: アクセスした情報の機微レベル（PUBLIC / INTERNAL / CONFIDENTIAL / PII）
- **Semantic distance**: 現在のアクションが元リクエストからどれだけドリフトしたか
- **Scope expansion**: 想定スコープ外のリソースにアクセスしているか
- **Entity set**: セッションで参照されたユーザ・アカウント・リソース
- **Confidence level**: 現在のアクションを評価することへのシステムの confidence（allow/deny/defer 決定に用いる）

**要点: confidence_level は δ の一員であり、data_classification・semantic_distance・scope_expansion・
entity_set と同格**である。「計算されたスコア」と「セッション文脈」という区別は δ の内部には無く、5つとも
等しく δ のメンバーである。

そして論文の Policy Structure（式3: π:(a,C)）の具体例は、`action.*` と `context.*` を比較演算子と `AND` で
連ねた述語として示す。C は δ を含む（式2）ので、δ の参照は `context.` の下に現れる。context-dependent deny の例:

```
policy: block_external_after_pii
match:
  action.tool == "email"
  AND action.params.to NOT IN internal_domains
  AND context.data_classification CONTAINS "PII"
decision: DENY
priority: 100
reason: "External email after PII access"
```

forbidden（コンテキスト評価を要さない）の例:

```
policy: block_drop_database
match:
  action.tool == "database"
  AND action.operation == "execute"
  AND action.params.query MATCHES "DROP\s+DATABASE"
decision: DENY
priority: 1000
reason: "Forbidden: DROP DATABASE"
```

論文記法から読み取れる規範的な点:

- **δ は C の一部（式2）であり、match では `context.` の下に参照される**（`context.data_classification CONTAINS "PII"`）。5つの δ メンバーはいずれも `context.<signal>` として現れる。
- **参照対象は `action.*`（tool / operation / params）と `context.*`（δ）** に分かれる。
- **演算子は `==` / `NOT IN` / `CONTAINS` / `MATCHES`** など。集合には `CONTAINS`、正規表現には `MATCHES`。
- **`priority` は第一級フィールド**。forbidden に大きな値（1000）、context-dependent に中程度（100）。
- 結合は **`AND`（連言）**。
- フィールドは `policy`（id）/ `match` / `decision` / `priority` / `reason`。

### 公式ガイド（aarm.dev/docs）の match 記法（構造化 YAML 実装）

公式ガイド（guides/first-policy.mdx）は、論文の式を構造化 YAML に落とした方言である。`match` の下を
領域別ブロックに分ける:

- `tool` / `operation`（論文の `action.tool` / `action.operation`）。
- `parameters`: パラメータ値の述語。`{ external: true }` `{ contains: "URGENT" }` のような述語オブジェクト。
- `context`: セッション文脈（δ）。`data_classification: [PII, PHI]`、`prior_actions: { contains: "db.query" }`。
- `risk_signals`: 計算されたリスクスコアの閾値比較。`injection_score: { gt: 0.8 }` `anomaly_score: { gt: 0.7 }`。

演算子は値の位置に `{ 演算子: 値 }` を置く述語オブジェクト方式（`{ gt: 0.8 }` / `{ contains: ... }` /
`{ external: true }`）。decision は `action:` キー（`ALLOW` / `DENY` / `MODIFY` / `STEP_UP`）。この他に
`modifications`（MODIFY 変換先）、`approvers` / `timeout` / `timeout_action`（STEP_UP）、`constraints`
（allowlist・rate limit）を持つ。

注意: 公式の `risk_signals`（`injection_score` / `anomaly_score`）は **δ の5メンバーには含まれない別物**
（injection 検知・異常スコアという危険性寄りのシグナル）で、laarma はまだ持たない。δ を `context` に置くのは
論文式(2)・公式ともに一致するが、`risk_signals` は δ とは別レイヤーである。

### laarma 現行の match 記法

laarma 現行（`policy.yaml` / `_match_conditions`）は、公式にさらに近い構造化だが区画が少ない:

- `tool`（`operation` は分離していない）。
- `param_matches`: パラメータ値の**正規表現マッチ**（公式の `parameters: { matches: ... }` に相当するが正規表現固定）。
- `environment_type` / `not_in_maintenance_window`: 環境条件（デモフィクション。[environment-demo-fiction.md](environment-demo-fiction.md)）。
- `any_of` / `none_of`: 条件のグルーピング。
- `priority`（#112 Phase A で追加、論文と整合）。

δ を参照する `context` 区画は**まだ無い**。これが Phase B で足す対象（式2 の δ 5メンバーを `context.` 配下で参照できるようにする）。

### 対照表

| 観点 | 論文（規範） | 公式ガイド | laarma 現行 |
|---|---|---|---|
| tool / operation | `action.tool` / `action.operation` | `tool` / `operation` | `tool` のみ |
| パラメータ述語 | `action.params.X == / NOT IN / MATCHES` | `parameters: { external / contains / ... }` | `param_matches`（正規表現） |
| δ 参照（式2 の5メンバー） | `context.<signal>`（例に出るのは `context.data_classification`。5メンバーは全て C の一部＝式2） | `context: { data_classification: [...] }`（δ は `context` 配下） | **無し（Phase B で `context.` 配下に追加）** |
| risk_signals（δ 外の危険性スコア） | （実例なし） | `risk_signals: { injection_score: { gt } }`（δ とは別レイヤー） | 無し（laarma の δ には使わない） |
| priority | 第一級（100 / 1000） | （例では未使用） | 第一級（Phase A で追加） |
| 結合 | `AND`（連言） | ブロックの AND | 条件の AND |
| decision キー | `decision` | `action` | `decision` |
| MODIFY 変換 | （実例なし） | `modifications`（**固定値のみ**） | `modify_transform`（**関数変換**） |
| 同一 priority 競合 | （実例なし） | （扱いなし） | **競合 → DEFER（R3(b)）** |

---

## 3. 公式ガイドの限界

公式ガイドは入門用で、laarma が #112 で既に踏み込んだ深さをカバーしていない。規範性は論文が上である。

- **関数変換 MODIFY を表現できない**。公式の `modifications: { parameters: { limit: 100 } }` は変換先を
  静的な固定値で書く方式で、laarma の `basename`（path サニタイズ）のような関数変換を表現できない。
- **同一 priority 競合 → DEFER（R3(b)）を扱っていない**。公式の例は priority すら使っておらず、
  複数ルールがマッチしたときの解決を示さない。laarma・論文が中心に据えた R3(b) が公式には無い。
- **δ の一員 confidence_level を扱っていない**。公式の `context` 例（data_classification・prior_actions）にも
  `risk_signals` 例（injection_score・anomaly_score）にも confidence_level は現れない。式2 では
  confidence_level は δ の一員なので、公式の例は δ を網羅していない。なお公式の `risk_signals` は δ 外の
  危険性寄りスコアであり、laarma の δ（confidence を含む）をそこに載せる話ではない（§4 参照）。

---

## 4. laarma の選択

**論文を規範とし、公式ガイドをその構造化 YAML 実装として参照する。** 公式の `context` 配下への δ 参照
（論文式2 と一致）と、述語オブジェクト `{ 演算子: 値 }` は借りるが、公式が扱えていない laarma の深さ
（関数変換 MODIFY・1パス terminal・競合 DEFER）は laarma の拡張として維持する。そのうえで Phase B の
δ 参照記法を次のように定める。

### (a) δ は部分踏襲——δ 参照だけ公式風に足し、既存 `param_matches` は温存

既存の `param_matches`（正規表現）は温存し、δ 参照（`context.` 配下）だけを新設する。記法全体を公式準拠に
作り直す（`param_matches` → `parameters: { matches: }` 等への移行、`operation` 分離）ことは Phase B の
スコープに含めず、**別 Issue（#121）** とする。Phase B のスコープを「δ 追加」に保つ。

### (b) δ は全て `context.` の下に置く（式2 の帰結）

論文式(2) は δ の5メンバー（data_classification・semantic_distance・scope_expansion・entity_set・
confidence_level）を等しく C の一部とし、match ではそれらを `context.` の下に参照する
（`context.data_classification CONTAINS "PII"`）。したがって laarma も δ を全て `context.` 配下に置く。
**data_classification や semantic_distance だけを `context` に置き、confidence を別区画に出す、という
分割はしない**——5つとも同格の δ なので、区画は `context` 一つで足りる。

- `context.data_classification`（集合参照、`CONTAINS` 相当。論文・公式一致。回帰 `step_up_pii_delete` の回復対象）
- `context.semantic_distance`（閾値参照 `{ gt: 0.4 }` 相当。回帰 `deny_intent_mismatch_destructive` の回復対象）
- `context.scope_expansion`（真偽/閾値参照）
- `context.confidence_level`（閾値参照 `{ lt: 0.4 }` 相当。回帰 `deny_ambiguous_delete_intent_mismatch`（旧 `defer_dynamic_ambiguous_delete`。条件2 実装後は confidence_level に到達する前に DENY で確定する）の回復対象）

### (c) confidence を危険性区画（`risk_signals`）に入れない——別区画を作るのではなく、δ として context に置く

以前の検討で「confidence を公式の `risk_signals` に入れず中立の別区画に置く」としたが、これは誤りだった。
式(2) に照らせば、confidence_level は δ の一員なので、他の δ と同じく `context.confidence_level` に置くのが
素直な帰結で、**そもそも `risk_signals` のような別区画を laarma の δ に用いる必要がない**。

confidence=評価可能性（危険性とは独立、§5 / [risk-classification.md](risk-classification.md)）という線引きは、
区画を分けることではなく、**δ を式2 通り素直に `context` に置く**ことで自然に保たれる。危険性寄りの
`risk_signals`（injection_score 等）は δ 外の別レイヤーであり、laarma がそれを導入するかは別の話（δ 参照とは
無関係）。

具体的な演算子表現（`{ gt: 0.4 }` を採るか、既存の条件記法に合わせるか）、`context.<signal>` の各値の型、
未 populate 時の R3(a) 扱いは、共通機構の設計（`_match_conditions` への C 配線）と合わせて Phase B 共通機構
ブリーフで確定する。本メモは「δ は全て `context.` 配下」「confidence を危険性区画に混ぜない」までを定める。

---

## 5. 決定事項

- 記法は**論文を規範・公式を構造化参照**として寄せる。意味論は現行の AND 連言を踏襲。
- **δ 部分踏襲**: δ 参照（`context.` 配下）だけ新設、既存 `param_matches` 温存。記法全体の公式準拠リファクタは**別 Issue（#121）**。
- **δ は全て `context.` の下に置く**（式2 の帰結）。data_classification・semantic_distance・scope_expansion・confidence_level を同格の δ として `context.<signal>` で参照する。
- **confidence は別区画を作らず `context.confidence_level` に置く**。危険性区画（`risk_signals` 等）には入れない（そもそも δ に別区画は不要）。危険性寄りの `risk_signals` は δ 外の別レイヤーで、導入可否は δ 参照と無関係。
- 演算子表現・各値の型・未 populate 時の R3(a) 扱いは Phase B 共通機構ブリーフで確定する。

### 別 Issue 送り（本メモのスコープ外）

- 記法全体の公式準拠リファクタ（`param_matches` → 述語オブジェクト、`operation` 分離、`constraints` /
  `approvers` / `timeout` 等の公式構造の導入）: **#121**。
- forbidden の扱いの論文差分: 論文は forbidden を priority 1000 として**同じ priority 空間**で表現するが、
  laarma は denied_tools を priority システムの**外側**の独立チェックとしている（#112 Phase A の設計判断）:
  **#122**。

---

## 関連

- 論文解釈の土台: [docs/aarm/classification-and-policy-model.md](../aarm/classification-and-policy-model.md)（Policy Structure・式3・Table I）、および式2（δ の定義）
- Phase B の実装設計: [decision-layer-policy-engine.md](decision-layer-policy-engine.md)（§2 組み替え後の構造・§3 条件1〜15 の移行表・§5 confidence=評価可能性）
- confidence ≠ 危険性: [risk-classification.md](risk-classification.md)
- 環境条件（デモフィクション）: [environment-demo-fiction.md](environment-demo-fiction.md)
- 参照: AARM 論文 arXiv:2602.09433（IV. PROBLEM FORMALIZATION 式2 の δ 定義、Policy Structure の実例）、aarm.dev 公式ドキュメント github.com/aarm-dev/docs（guides/first-policy.mdx の match 記法）
- 関連 Issue: #112（Phase B で δ 参照 match predicate を実装）、#121（記法全体の公式準拠リファクタ）、#122（forbidden の priority 思想差）、#77（confidence 較正）、#100（composite risk = 危険性軸）
