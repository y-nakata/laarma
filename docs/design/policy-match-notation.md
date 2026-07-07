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

### 【論文】AARM 論文の match 記法（規範）

論文は Policy Structure（式3: π:(a,C)）の具体例を、`action.*` と `context.*` を比較演算子と `AND` で
連ねた述語として示す。context-dependent deny の例:

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

- **参照対象は `action.*`（tool / operation / params）と `context.*`（data_classification 等）** に分かれる。
- **演算子は `==` / `NOT IN` / `CONTAINS` / `MATCHES`** など。集合には `CONTAINS`、正規表現には `MATCHES`。
- **`priority` は第一級フィールド**。forbidden に大きな値（1000）、context-dependent に中程度（100）。
- 結合は **`AND`（連言）**。
- フィールドは `policy`（id）/ `match` / `decision` / `priority` / `reason`。

### 公式ガイド（aarm.dev/docs）の match 記法（構造化 YAML 実装）

公式ガイド（guides/first-policy.mdx）は、論文の式を構造化 YAML に落とした方言である。`match` の下を
領域別ブロックに分ける:

- `tool` / `operation`（論文の `action.tool` / `action.operation`）。
- `parameters`: パラメータ値の述語。`{ external: true }` `{ contains: "URGENT" }` のような述語オブジェクト。
- `context`: セッション文脈。`data_classification: [PII, PHI]`、`prior_actions: { contains: "db.query" }`。
- `risk_signals`: 計算されたリスクスコアの閾値比較。`injection_score: { gt: 0.8 }` `anomaly_score: { gt: 0.7 }`。

演算子は値の位置に `{ 演算子: 値 }` を置く述語オブジェクト方式（`{ gt: 0.8 }` / `{ contains: ... }` /
`{ external: true }`）。decision は `action:` キー（`ALLOW` / `DENY` / `MODIFY` / `STEP_UP`）。この他に
`modifications`（MODIFY 変換先）、`approvers` / `timeout` / `timeout_action`（STEP_UP）、`constraints`
（allowlist・rate limit）を持つ。

### laarma 現行の match 記法

laarma 現行（`policy.yaml` / `_match_conditions`）は、公式にさらに近い構造化だが区画が少ない:

- `tool`（`operation` は分離していない）。
- `param_matches`: パラメータ値の**正規表現マッチ**（公式の `parameters: { matches: ... }` に相当するが正規表現固定）。
- `environment_type` / `not_in_maintenance_window`: 環境条件（デモフィクション。[environment-demo-fiction.md](environment-demo-fiction.md)）。
- `any_of` / `none_of`: 条件のグルーピング。
- `priority`（#112 Phase A で追加、論文と整合）。

`context`（δ 参照）区画と、計算スコアの閾値比較区画は**まだ無い**。これが Phase B で足す対象。

### 対照表

| 観点 | 論文（規範） | 公式ガイド | laarma 現行 |
|---|---|---|---|
| tool / operation | `action.tool` / `action.operation` | `tool` / `operation` | `tool` のみ |
| パラメータ述語 | `action.params.X == / NOT IN / MATCHES` | `parameters: { external / contains / ... }` | `param_matches`（正規表現） |
| セッション文脈 δ | `context.data_classification CONTAINS` | `context: { data_classification: [...] }` | **無し（Phase B で追加）** |
| 計算スコア δ | （実例に明示なし） | `risk_signals: { injection_score: { gt } }` | **無し（Phase B で追加）** |
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
- **confidence を含まない**。公式の計算スコア区画 `risk_signals` は `injection_score` / `anomaly_score`
  という**危険性寄り**のスコアで、laarma が §5 で「評価可能性（危険性とは独立）」と定義した confidence を
  含まない。したがって **confidence を `risk_signals` に入れることは公式互換にはならない**——公式に無い
  ものを危険性寄りの名前の下にぶら下げ、意味論的に誤った `risk_signals` 拡張を足すだけになる。

---

## 4. laarma の選択

**論文を規範とし、公式ガイドをその構造化 YAML 実装として参照する。** 公式の区画分け（`context` と
計算スコア区画の切り分け、述語オブジェクト `{ 演算子: 値 }`）は借りるが、公式が扱えていない laarma の
深さ（関数変換 MODIFY・1パス terminal・競合 DEFER）は laarma の拡張として維持する。そのうえで
Phase B の δ 参照記法を次のように定める。

### (a) δ は部分踏襲——δ 参照だけ公式風に足し、既存 `param_matches` は温存

既存の `param_matches`（正規表現）は温存し、δ 参照区画だけを新設する。記法全体を公式準拠に作り直す
（`param_matches` → `parameters: { matches: }` 等への移行、`operation` 分離）ことは Phase B のスコープに
含めず、**別 Issue** とする。Phase B のスコープを「δ 追加」に保つ。

### (b) data_classification は `context` 区画（論文・公式一致）

論文の `context.data_classification CONTAINS "PII"`、公式の `context: { data_classification: [PII] }` は
一致する。laarma もこれに合わせ、セッション文脈由来の δ（data_classification 等）は **`context` 区画**に
集合表現で置く。回帰 `step_up_pii_delete` の回復対象。

### (c) semantic_distance / confidence は計算スコアの閾値比較。ただし confidence は中立区画

semantic_distance と confidence は「計算されたスコアの閾値比較」で、公式の `risk_signals` 区画の形
（`{ gt: 0.4 }` / `{ lt: 0.4 }`）が素直。ただし §3 の通り **confidence を `risk_signals`（危険性寄りの名前）に
入れない**。confidence=評価可能性という §5 の線引きを記法でも保つため、**中立名の別区画**に置く。

- semantic_distance は「意図からのドリフト」で危険性寄りの解釈が可能なため、`risk_signals` 相当の区画に
  置く余地がある（回帰 `deny_dynamic_delete_intent_mismatch` の回復対象）。
- confidence は評価可能性軸なので、危険性区画とは分けた中立区画に置く（回帰 `defer_dynamic_ambiguous_delete`
  の回復対象）。

具体的な区画名（`risk_signals` を採るか laarma 独自の中立名にするか、confidence 区画を何と呼ぶか）は、
共通機構の設計（`_match_conditions` への C 配線・演算子表現・未 populate 時の R3(a) 扱い）と合わせて
Phase B 共通機構ブリーフで確定する。本メモは「confidence を危険性区画に混ぜない」という制約までを定める。

---

## 5. 決定事項

- 記法は**論文を規範・公式を構造化参照**として寄せる。意味論は現行の AND 連言を踏襲。
- **δ 部分踏襲**: δ 参照区画だけ新設、既存 `param_matches` 温存。記法全体の公式準拠リファクタは**別 Issue**。
- **data_classification は `context` 区画**（論文・公式一致、集合表現）。
- **confidence は危険性区画（`risk_signals` 等）に入れない**。中立区画に置く（評価可能性軸の保持）。
- 区画名・演算子表現・未 populate 時の R3(a) 扱いは Phase B 共通機構ブリーフで確定する。

### 別 Issue 送り（本メモのスコープ外）

- 記法全体の公式準拠リファクタ（`param_matches` → 述語オブジェクト、`operation` 分離、`constraints` /
  `approvers` / `timeout` 等の公式構造の導入）。
- forbidden の扱いの論文差分: 論文は forbidden を priority 1000 として**同じ priority 空間**で表現するが、
  laarma は denied_tools を priority システムの**外側**の独立チェックとしている（#112 Phase A の設計判断）。
  この思想差を将来見直すか否かは別途。

---

## 関連

- 論文解釈の土台: [docs/aarm/classification-and-policy-model.md](../aarm/classification-and-policy-model.md)（Policy Structure・式3・Table I）
- Phase B の実装設計: [decision-layer-policy-engine.md](decision-layer-policy-engine.md)（§2 組み替え後の構造・§3 条件1〜15 の移行表・§5 confidence=評価可能性）
- confidence ≠ 危険性: [risk-classification.md](risk-classification.md)
- 環境条件（デモフィクション）: [environment-demo-fiction.md](environment-demo-fiction.md)
- 参照: AARM 論文 arXiv:2602.09433（Policy Structure の実例）、aarm.dev 公式ドキュメント github.com/aarm-dev/docs（guides/first-policy.mdx の match 記法）
- 関連 Issue: #112（Phase B で δ 参照 match predicate を実装）、#77（confidence 較正）、#100（composite risk = 危険性軸）
