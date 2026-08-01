# AARM 解釈メモ: 分類フレームワーク（Table I）とポリシー評価モデル

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは **AARM 論文（外部仕様）が何を言っているか**を読み解く解釈メモである。
> laarma 自身の設計判断は書かない（それは `docs/design/` の役割で、そちらから本メモを参照する）。
> 本メモは、AARM 論文の分類フレームワーク（Table I）とポリシー構造（式3）を、
> 「ポリシー評価エンジン」という一つの機構として読み解いたもの。#94（signal/decision 分離）の
> 決定層設計の土台となる。
>
> **記述の区別**: 本メモは二種類の記述を**恒久的に区別**する。
> - **【論文】** で始まる節・段落は、AARM 論文が明示的に述べていること（引用・要約・翻訳）。
> - **【解釈】** で始まる節・段落は、論文が明示していない構造を解釈者が読み解いたもの、
>   または論文の記述の曖昧さ・不整合を指摘したもの。根拠を添える。
>
> この区別は一時的なマーカーではなく、本メモの恒久的な構成である。将来 `docs/aarm/` を参照する者が
> 「論文の事実」と「laarma 側の読み」を取り違えないための構造。
>
> **出典・ライセンス**: 本メモが参照・引用・翻訳する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。引用・翻訳は同ライセンスに基づく。

---

## 1. 出発点: AARM のポリシーは (a, C) を評価する

### 【論文】ポリシーの定式化（式3）

AARM のポリシー π は、アクションとコンテキストのペアを認可決定に写す関数である（論文 式3）:

```
π : (a, C) → {ALLOW, DENY, MODIFY, STEP_UP, DEFER}
```

各ポリシー π は次の要素からなる:

- **match predicate** `m(a, C) → {true, false}`: そのポリシーが当該のアクションとコンテキストに適用されるかを判定する述語
- **decision** `d`: 5 種の認可決定のいずれか
- **priority** `p ∈ ℕ`: 複数のポリシーが match したときの競合解決に使う優先度
- **optional modification function** `f(a) → a'`: `d = MODIFY` のときに適用される変換関数

そして match predicate が参照してよいものを、論文は明示的に列挙している:

> Match predicates may reference action fields (tool, operation, parameters), identity attributes, and accumulated context signals.

すなわち match predicate は **(1) action フィールド（tool / operation / parameters）、(2) identity 属性、(3) 蓄積されたコンテキスト信号（δ を含む）** を参照してよい。

### 【論文】コンテキスト蓄積（式2）とポリシー評価の関係

コンテキスト C は、Context Accumulator が毎アクション更新する（論文 式2）:

```
Cn = Cn-1 ∪ {an, on, δn}
```

ここで `an` はアクション、`on` はその出力、`δn` は派生信号（data classification / semantic distance / scope expansion / entity set / confidence level）。論文は「ポリシーエンジンは、静的ルールに対する action `a` だけでなく、**それに先行するすべてを文脈とした tuple `(a, C)` を評価する**」と述べる。

さらに準拠要件として、論文は次を明記する:

> The conformance requirement is that the policy engine can evaluate the tuple (a, C)—not merely the action in isolation.

AARM は特定のポリシー言語を強制しない（OPA / Cedar / 独自 DSL いずれも可）。唯一の準拠要件は、**ポリシーエンジンが (a, C) を評価できること**——action だけを孤立して評価するのでは不足、という点である。

### 【解釈】Table I は「ポリシー評価エンジンの結果分類」であって「意図整合値の写像表」ではない

このメモの中心的な読みを最初に述べる。**Table I（次節）は、ポリシー集合 Π を (a, C) で評価した結果を分類したものであり、「意図整合性の判定値（aligned / misaligned など）を認可決定に写す変換表」ではない。**

この読みの根拠は式3 と match predicate の参照範囲にある。決定を出すのは「意図整合値を写像するテーブル」ではなく、「match predicate が (a, C) を評価し、priority で競合解決するポリシー評価エンジン」である。意図整合性の判定結果（後述の semantic distance / alignment 信号）は、その match predicate が参照しうる **context 信号の一つ**にすぎない。決定層が保持するのは写像テーブルではなく、ポリシー評価の機構である。

（この読みは laarma の決定層設計に直接影響する。決定層を「意図整合値→決定の写像テーブル」として作るのか「(a,C) を評価するポリシーエンジン」として作るのかは設計判断であり、それは `docs/design/` で扱う。本メモはあくまで「論文の Table I はポリシー評価エンジンの結果分類と読むのが式3 と整合する」という解釈を記録する。）

---

## 2. 分類フレームワーク（Table I）

### 【論文】Table I: Action Classification Framework

| Category | Policy Baseline | Context Evaluation | Runtime Decision |
|---|---|---|---|
| Forbidden | N/A (hard limit) | Ignored | DENY |
| Context-Dependent Deny | ALLOW | Misalignment detected | DENY |
| Context-Dependent Allow | DENY | Alignment confirmed | STEP UP / ALLOW |
| Context-Dependent Defer | ALLOW or DENY | Insufficient or conflicting signals | DEFER |
| Standard Allow | ALLOW | No signals | ALLOW |
| Standard Deny | DENY | No alignment | DENY |

論文本文（Classification の節）は、このうち **4 分類（Forbidden / Context-Dependent Deny / Context-Dependent Allow / Context-Dependent Defer）のみを説明**している。R3・Security Objective 4・Contributions の記述もすべて 4 分類を列挙する。**Standard Allow / Standard Deny の 2 行は Table I にのみ現れ、本文に説明がない。**

### 【論文】各分類の説明（本文が説明する 4 つ）

- **Forbidden**: 静的ポリシーにマッチしたら即座に DENY。「A forbidden action policy requires no context evaluation」——コンテキスト評価を要しない。例は DROP DATABASE、`rm -rf /`、既知の悪性 IP への接続、セキュリティ制御の無効化など、文脈によらず常に禁止すべきカタストロフィックな操作。
- **Context-Dependent Deny**: ポリシーのベースラインは ALLOW だが、コンテキストが「misalignment」を検出したら DENY に覆す。論文の例は「PII にアクセスした後の外部メール送信」（`block_external_after_pii`）——個々の操作は許可されているが、その **組み合わせ（composition）が潜在的な情報漏洩を構成する**。
- **Context-Dependent Allow**: ポリシーのベースラインは DENY だが、コンテキストが「alignment confirmed（明確な整合）」を示したら STEP UP または ALLOW に緩める。「denied by default but permitted when context demonstrates clear alignment」。
- **Context-Dependent Defer**: リスクが評価時点で確定できない。利用可能なコンテキストが不十分・曖昧・内部矛盾している場合、potentially unsafe な allow/deny に committing するのではなく、実行を一時保留する。論文の評価規則は「Policy outcome is indeterminate under current context → DEFER」。

### 【解釈】Forbidden と Standard/Context-Dependent の境界は「match predicate が context を参照するか否か」

Table I は Forbidden の Policy Baseline を「N/A (hard limit)」、Context Evaluation を「Ignored」と書く。この "hard limit" が何を意味するかは、Table I の字面からは曖昧だが、Policy Structure の 2 つの具体例が境界を明らかにする。

論文の forbidden 例（`block_drop_database`）の match predicate は **action フィールドのみ**を参照する:

```
match: action.tool == "database"
   AND action.operation == "execute"
   AND action.params.query MATCHES "DROP\s+DATABASE"
priority: 1000
```

一方 context-dependent deny 例（`block_external_after_pii`）の match predicate は **context を参照する**:

```
match: action.tool == "email"
   AND action.params.to NOT IN internal_domains
   AND context.data_classification CONTAINS "PII"
priority: 100
```

したがって、Forbidden と context 依存の分類の構造的な差は **「match predicate が context (C) を参照するか、action (a) だけを見るか」** である。Forbidden は action のみを見る（だから "context evaluation を要しない" = "Ignored"）。context 依存の各分類は context を見る。priority も差を示唆する（forbidden の例は 1000、ctx-deny の例は 100 と、forbidden 帯が高い）。

### 【解釈】`block_external_after_pii` の match predicate は informative な例示であり、field 名・累積性を normative に規定しない

`context.data_classification CONTAINS "PII"` という記法は、この節（§IV PROBLEM FORMALIZATION）の informative な例示の一部である。`docs/aarm/deferral.md` が確立した読み方（FRAMEWORK 章のような narrative な記述は informative、CONFORMANCE 章 R3 のような検証可能な記述が normative——ISO/IEC Directives Part 2・W3C QA Framework に基づく標準的な二層構造）に照らすと、§IV の具体例も同じ扱いで読むのが一貫している。laarma が準拠すべき MUST 要件は「CSA版」の R1〜R9（R2: `Cn = Cn-1 ∪ {an, on, δn}` の維持、など）であり、`context.data_classification` というフィールド名や、その値がセッション累積かどうかという実装の詳細は、この1つの例示が規定するものではない。

上記の「Forbidden と context 依存の境界」という解釈（match predicate が context を参照するか否か）はこの区別と独立に成り立つ——参照する対象が何であれ「context を参照している」という構造自体が論点だからである。したがってこの解釈は影響を受けない。影響を受けるのは、`context.data_classification` というフィールドの**中身**（当該アクション時点の値か、セッション累積か）を実装する際に、この例示を根拠に一意に決められると考えることである。laarma の実装（`derived_signals()` の signal 設計）は、この例示を参考にはするが、それ自体を規定根拠にはしない（詳細は [decision-layer-policy-engine.md](../design/decision-layer-policy-engine.md)）。

### 【解釈】「DENY を書くと Forbidden になる」は誤り——DENY baseline は明示ポリシー

過去の laarma の議論で「静的ポリシーで DENY を書くと、それは Forbidden ルールになってしまう。したがって Context-Dependent Allow の "Policy Baseline: DENY" は、明示的な DENY ポリシーではなく、ALLOW ポリシーにマッチしない裏側の暗黙のデフォルト DENY 状態だ」という解釈があった。**これは誤りであり、本メモで覆す。**

論文の Context-Dependent Allow の説明は「denied by default but permitted when context demonstrates clear alignment」であり、ここでの "denied by default" は **明示的な DENY ポリシーがベースラインとして存在する**ことを指す。暗黙の裏状態ではない。

「DENY を書く = Forbidden になる」という一対一の思い込みが誤りの根源だった。同じ DENY decision でも:

- match predicate が **context を参照せず**（action のみ）、高 priority で覆されないなら → **Forbidden 的**
- match predicate が context を参照する、あるいは他の context 依存ポリシーによって priority で覆されうるなら → **Context-Dependent の baseline**

decision が DENY であることと、それが Forbidden であることは別。何が Forbidden で何が context 依存の DENY baseline かは、**match predicate が context を見るか・priority で覆されうるか**で決まる。DENY baseline を「暗黙の裏デフォルト」として捻り出す必要はない。

### 【解釈】Standard Allow / Standard Deny の読み（論文に説明がないため解釈で補う）

Standard Allow / Standard Deny は Table I にのみ現れ本文の説明がないため、Table I の記述と全体構造から読み解くしかない。

Table I の記述:
- Standard Allow: Policy Baseline = ALLOW ／ Context Evaluation = **No signals** ／ → ALLOW
- Standard Deny: Policy Baseline = DENY ／ Context Evaluation = **No alignment** ／ → DENY

読み: **アクションだけを見て ALLOW / DENY を出す（低 priority の）ベースラインのポリシーがあり、それを覆す「(a, C) を参照して異なる判定を出す（高 priority の）ポリシー」がマッチしなかった**ケース。すなわち context 依存ポリシーが何も発火せず、ベースラインがそのまま Runtime Decision になる。

Context Evaluation 列の "No signals"（Standard Allow）と "No alignment"（Standard Deny）は、この「覆すものがなかった」を Allow 側・Deny 側それぞれの語り口で書いたもの:
- Standard Allow の "No signals" = ベースライン ALLOW を DENY/STEP_UP に覆すべき危険信号（misalignment 等）が何も検出されなかった。
- Standard Deny の "No alignment" = ベースライン DENY を ALLOW/STEP_UP に緩めるべき整合（alignment）を示すものが何もなかった。

この読みは Context-Dependent Deny / Allow が「ベースラインを context が覆す」構造であることと対称的で、Standard 2 行は「覆しが起きなかったデフォルト経路」にあたる。

---

## 3. 複数ポリシーの競合解決と DEFER トリガー

### 【論文】priority による競合解決

Policy Structure は priority `p ∈ ℕ` を「複数のポリシーが match したときの競合解決」に使うと定める。複数の π が同時に match しうるため、priority で採用するポリシーを決める。

### 【論文】DEFER の 3 トリガー（R3）

R3 は DEFER が発火する条件を MUST として 3 つ挙げる:

> deferral MUST be triggered when: (a) a policy rule's match predicate references context fields that are not yet populated in the session, (b) multiple applicable policies produce conflicting decisions at the same priority level, or (c) a confidence score (if implemented) falls below a deployment-configured threshold.

- **(a)** match predicate が、まだセッションに populate されていないコンテキストフィールドを参照している
- **(b)** 複数の適用可能なポリシーが、**同一の priority レベルで矛盾する決定**を出す
- **(c)** confidence スコア（実装されている場合）が、デプロイ設定の閾値を下回る

そして「DEFER をトリガーする条件は文書化され監査可能でなければならない（MUST）」。

### 【解釈】priority を「層」として使う

DEFER トリガー (b) が「同一 priority での矛盾 → DEFER」であることは、priority を単なる数値ではなく **層（band）** として設計に使えることを示唆する。priority 帯を役割ごとに分けて割り当てれば:

- Forbidden 帯（最高 priority、例: 1000〜）: action のみ参照、常に DENY
- 意図整合・危険性による上書き帯（Forbidden と同等かその下）: context を参照して baseline を覆す
- ベースライン帯（低 priority）: action のみで ALLOW/DENY を出すデフォルト

このように帯を分ければ、高 priority のポリシーが低 priority のベースラインを priority 解決で覆せる。後述（§5）の「alignment チェックを各 Allow ルールの述語に書かず独立させる」設計は、この priority 帯として実現できる（あるいはコードの独立層として——これは設計判断で `docs/design/` の領分）。

---

## 4. intent alignment の語の二義性（論文の曖昧さ）

### 【解釈】「意図整合」が二つの異なる意味で使われている

論文は "intent alignment" / "alignment" / "misalignment" の語を、**二つの異なる対象**に対して使っており、区別されていない。これは論文の概念上の曖昧さであり、laarma がそれを実装に落とす際に混同を生みうるため、ここで明示的に指摘する。

**意味 A: ユーザ意図との整合**
semantic distance、intent drift、「does this action make sense given what the user asked for」——これは **ユーザの元リクエストと現在のアクションの整合**を指す。エージェントの行動が元の要求から徐々に逸れる（drift）、あるいはプロンプトインジェクションで乗っ取られる（hijack）のを捉えるのがこの軸。

**意味 B: 組織ポリシーとの整合**
Context-Dependent Deny の例（PII アクセス後の外部メール送信）は、Table I では「Misalignment detected」と分類される。しかし——**この操作はユーザ意図には沿っているかもしれない**（ユーザが「この顧客データをパートナーに送って」と頼んだ場合、PII 外部送信はユーザ意図と整合している）。整合していないのは「PII を外部に出すな」という**組織のコンプライアンス規則**である。論文自身この例を「permitted capability used in suspicious sequence」「composition constitutes a potential breach」と説明しており、これは意味 A（ユーザ意図逸脱）ではなく意味 B（組織規則違反）。

**問題**: Table I の「Misalignment detected」列は意味 A と意味 B を同じ "misalignment" の語で束ねている。だが両者は別物である:
- 意味 A（ユーザ意図逸脱）は、ユーザの元リクエストと照らして測るもの（semantic distance / drift / hijack 検出）。
- 意味 B（組織規則違反）は、ユーザ意図がどうであれ組織のルールに反するかを見るもの。

この二義性を区別せずに「intent alignment を判定する」コンポーネントを作ると、そのコンポーネントが「ユーザ意図逸脱の検出」と「組織規則違反の判定」の両方を背負うことになる。両者を分離するか統合するかは laarma の設計判断（`docs/design/`）だが、**論文の段階で intent alignment の語が二義的であること自体は、論文の事実として記録しておく必要がある**。

---

## 5. 測定と評価の二段構造、および alignment チェックの集約

### 【論文】alignment 測定は Context Accumulator が毎アクション産出する δ

semantic distance は δ の一員であり（式2 の δn に含まれる）、Context Accumulator が**毎アクション**算出する。論文は semantic distance を「how far the current action has drifted from the original request」を測るものとし、「High semantic distance warrants additional scrutiny, step-up authorization, or deferral」と述べる。すなわち alignment の測定結果は、ポリシー評価に先立って C に載っている。

### 【解釈】測定（常時）と使用（ポリシー評価段）は別の段

alignment に関する処理は二段に分かれる:

1. **測定**: ユーザの元リクエストと現在のアクションの整合（semantic distance / alignment 信号）を測る。これは Context Accumulator が δ を産出する段で、**ポリシー評価とは独立に、毎アクション常時**行われる。
2. **使用**: 測った alignment 信号を条件に、decision を出す。これはポリシー評価の段で、match predicate が alignment 信号を参照する（または後述の独立層が参照する）。

この二段の分離が重要な理由: プロンプトインジェクション・ゴールハイジャック・意図ドリフトの検出は、**全アクションで常時 alignment を測り続けて**初めて可能になる。もし「特定のポリシーが match したときだけ alignment を測る」構造だと、そのポリシーに当たらないアクションは測られず、drift/hijack がすり抜ける。測定 (1) はポリシーの match と無関係に常時走らねばならない。論文が semantic distance を δ（毎アクション産出）に置いているのは、この常時測定と整合する。

### 【解釈】alignment チェックは各 Allow ルールの述語に書かず、独立させる

「alignment 信号を match predicate が参照する」を素朴に実装すると、「ALLOW を出すあらゆるポリシーに `AND context.alignment == confirmed` を付ける」ことになりかねない。これは誤りである。理由:

- SQL の WHERE 句すべてに `AND 1=1` を書くような冗長さを生む。
- 「alignment が崩れていたら止める」という防御の本体が、個々の Allow ルールの付帯条件に埋没する。
- 付け忘れた Allow ルールが一つでもあれば、そこは alignment を見ずに通る穴になる。

正しい構造: **alignment の崩れ（drift / injection / hijack）による DENY/STEP_UP は、個々の Allow ルールの述語に書くのではなく、それを覆す独立した層に集約する。** Table I の Context-Dependent Deny が「ベースライン ALLOW を misalignment が覆す」構造であることも、この読みと整合する——alignment チェックは Allow ルールの内部条件ではなく、ベースラインを覆しうる独立の評価である。

この独立層は、実装形態として二通りありうる（どちらを採るかは設計判断で `docs/design/`）:
- **コード化**: 決定層の独立した一段として、accumulation 段で測った alignment 信号を見て baseline を覆すロジックを書く。
- **組み込みポリシー化**: alignment 崩れによる DENY/STEP_UP のルールを、priority を層別に割り当て（§3 の priority 帯）、Forbidden 帯と同等かそれより高い番号に置く。そうすれば低 priority のベースライン Allow を priority 解決で覆せ、全アクションに一箇所で効く。

いずれの形でも「全 Allow ルールに alignment 述語を書き回る」ことは避けられ、alignment チェックは一箇所に集約される。

---

## 6. まとめ: この解釈が示す機構

【解釈】本メモの読みを一つの機構として要約する:

1. アクション `a` が来ると、Context Accumulator が δ（semantic distance / data classification / confidence 等）を産出し、コンテキスト `C` を更新する（式2）。alignment の測定はこの段で常時行われる。
2. ポリシー評価エンジンが、`(a, C)` に対してポリシー集合 Π を評価する。各ポリシー π の match predicate は action / identity / context（δ 含む）を参照できる（式3）。
3. 複数の π が match したら priority で競合解決する。同一 priority で矛盾したら DEFER（トリガー b）。未 populate の context を参照していたら DEFER（トリガー a）。confidence が閾値未満なら DEFER（トリガー c）。
4. Table I の 6 分類は、この評価の結果を分類したもの——「どんな match 結果（context 参照の有無・baseline・覆しの有無）から、どの Runtime Decision が出るか」の分類であって、意図整合値を写す変換表ではない。
5. alignment の崩れによる DENY/STEP_UP は、各 Allow ルールの述語ではなく、独立した層（コードの一段、または高 priority 帯の組み込みポリシー）に集約される。

この機構を laarma でどう実装するか（決定層をポリシー評価エンジンとして作る、IA をユーザ意図整合に限定し組織規則整合はポリシーが担う、privilege_scope や destructive_tools をどこまでポリシーに落とすか、組み込みルールを何にするか、処理順序をどう組むか）は、すべて laarma の設計判断であり、`docs/design/` で本メモを参照しつつ扱う。

---

## 関連

- AARM 論文 arXiv:2602.09433: 式2（Context Accumulation）、式3（Policy Structure）、Table I（Action Classification Framework）、R3（Policy Evaluation with Intent Alignment、DEFER トリガー a/b/c）、R4（5 種の認可決定）、§IV-C（派生信号 δ）、Security Objective 4（分類ベースの決定）
- laarma の設計判断（本メモを土台とする）: `docs/design/`（決定層のポリシーエンジン化、IA の意図整合限定、組み込みルール等）
- 関連 Issue: #94（IA の signal/decision 分離）、#107（match 条件で δ を参照できるようにする拡張）
