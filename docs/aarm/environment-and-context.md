# AARM 解釈メモ: 環境 E と評価タプル (a, C)

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは **AARM 論文（外部仕様）が何を言っているか**を読み解く解釈メモである。
> laarma 自身の設計判断は書かない（それは `docs/design/` の役割で、そちらから本メモを参照する）。
> 本メモは、AARM 論文が環境 E をどう定義し、それを評価タプル (a, C) にどう通している（いない）かを読み解いたもの。
> 論文の Action Classification（Context-Dependent Defer の例）および脅威モデル（V.C.4）と形式モデル（式2・式3）の間の不整合を指摘し、
> #87（環境条件を含む判定条件をどう扱うか）の前提を問い直す土台となる。
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

## 主張（要約）

AARM は環境 E に二つの役割を負わせているが、両者を調停していない。形式モデル（式2・式3）は E を評価入力から締め出す一方、Action Classification の Context-Dependent Defer の例は E の運用状態を判定変数として参照している。この未調停により、論文自身が挙げた Defer の例は、論文の形式化に準拠した実装では記述通りに実現できない。同じ入力チャネル不在は脅威モデル（V.C.4 Environmental Manipulation）の "AARM Partial Mitigation" にも同型で現れる。E の期待状態のベースラインを保持し現在の環境入力との逸脱を検出する低減策（enabling detection when environmental inputs deviate from expected baselines）、および environmental state の anomaly detection——いずれも E の状態の観測を前提とする——が AARM 機構自身の対策として提示されており、これも不整合である。

---

## 1. 環境 E の定義とアクションの影響

### 【論文】E の定義（IV.A.2 Formal Model）

環境 E は、ツールが相互作用する外部システムとして定義される:

> An environment E including data stores, APIs, cloud services, and enterprise systems that tools interact with. The environment contains assets of varying sensitivity, and actions on E may be irreversible.

E は多様な機微度の資産を含み、E への作用は不可逆でありうる。

### 【論文】Execution Effects: 影響 e は E の状態変化（IV.A.4）

アクション a の実行は二つの産物を生む。

- **出力 o**: ツールの戻り値（"the return value from the tool"）。実行済みアクションの結果であり、後続アクションの評価に供するため C に captured and appended される。
- **影響 e**: E 内の状態変化。

論文は影響 e を次のように定める:

> An effect e: state changes in E. Effects include database mutations, file system changes, sent communications, API side effects, financial transactions, and credential modifications.

影響 e は reversible / irreversible / cascading に分類される。論文は output と effect の区別を critical とし、期待される output に基づいて許可しても実際の effect を取り逃す危険を指摘する。

### 【解釈】この定義において E は effect の作用先（下流）であり、関係は一方向 a → E

E に対する関係は、アクションの実行が E の状態を変えるという a → E の一方向である。E の状態を評価器が読む向きの関係は、この定義には現れない。

論文全体のスタンスもこの一方向性と整合する。E への影響は不可逆でありうるため、実行後に検証したのでは手遅れであり、アクションの実行そのものを実行前に止めて E への影響を出さないことが要点として強調される。すなわち E は「守るべき下流」として置かれており、「読むべき上流の入力」としては置かれていない。

---

## 2. Context-Dependent Defer の例が E を参照する

### 【論文】Context-Dependent Defer の例（IV.B.4）

Context-Dependent Defer は、評価時点で行為のリスクを確定できない場合に、potentially unsafe な allow / deny に踏み込む代わりに実行を一時保留する分類である。論文が挙げる例:

> Consider an agent initiating a credential rotation outside a routine maintenance window. The action may be legitimate, but the available context does not support a confident decision.

### 【解釈】この例は E の運用状態を判定変数として参照している

「メンテナンスウィンドウ外（outside a routine maintenance window）」は、E の運用状態——今が保守窓の内か外か——を指す。この記述が Defer の例として成立するためには、窓の内外を判別できることが前提になる。判別できて初めて「窓の外だから確信を持って決められない」という筋が立つ。したがってこの例は、E の運用状態を判定を分ける入力変数として暗黙に呼び出している。

---

## 3. 形式モデルに E は登場しない

### 【論文】Context Accumulation（式2）と派生信号 δ

コンテキスト C は Context Accumulator が毎アクション更新する:

```
Cn = Cn-1 ∪ {an, on, δn}   (式2)
```

C の構成要素は、original request / action history / data accessed / tool outputs / entities referenced であり、形式的には {アクション an, 出力 on, 派生信号 δn}。δ の五要素は data classification / semantic distance / scope expansion / entity set / confidence level である。

### 【論文】Policy Structure（式3）と準拠要件

ポリシー π は tuple を認可決定に写す:

```
π : (a, C) → {ALLOW, DENY, MODIFY, STEP_UP, DEFER}   (式3)
```

match predicate `m(a, C)` が参照してよいものを論文は列挙する:

> Match predicates may reference action fields (tool, operation, parameters), identity attributes, and accumulated context signals.

すなわち action フィールド・identity 属性・蓄積されたコンテキスト信号（δ を含む）。準拠要件は次の通り:

> The conformance requirement is that the policy engine can evaluate the tuple (a, C)—not merely the action in isolation.

### 【解釈】C にも δ にも E の運用状態は含まれない

式2以降、E は定式化に一度も登場せず、System Model（IV.A）で置かれた「E は effect の作用先」という位置に戻る。評価器が見るのは tuple (a, C) であり、match predicate が参照できるのは action / identity / context 信号である。ambient な環境運用状態（保守窓の内外のような、行為に由来しない E の状態）は、C の構成要素のいずれにも δ の信号のいずれにも含まれない。したがって形式装置は、E を評価入力として読む経路を持たない。

---

## 4. o は E の読み出し経路にならない

### 【論文】o は実行済みアクションのツール戻り値で C に追記される

論文は o を、実行されたアクションのツール戻り値と定め、それが後続評価のため C に captured and appended されるとする。C の tool outputs はこの o の蓄積である。

### 【解釈】o は行為に由来しない環境前提の入力路にならない

「E は o を通じて C に入るのではないか」という反論は成立しない。o は実行済みアクションのツール戻り値であって、評価器が判定の前提として E を能動的に読む経路ではない。ある行為が E を照会すればその結果は o として C に載るが、それはその行為を実行した場合に限る。§2 の Defer の例には、保守窓の状態を読む行為が存在しない。credential rotation の出力が保守窓の状態を返すわけでもない。したがって、行為に由来しない環境前提を評価入力に載せる一般的な経路は形式化に無い。o を根拠に例を救うには、論文が定義していない観測行為を補って前提する必要がある。

---

## 5. 未調停の二役と、例の実現不能性

### 【解釈】E は二役を負い、それが調停されていない

E は二つの役割を負う。

- **役割 (a) effect-target**: アクション実行が状態を変える下流の対象。式2・式3・System Model が形式化しているのはこちらのみ。
- **役割 (b) precondition の状態源**: 判定の前提として E の運用状態を読む上流の入力。Context-Dependent Defer の例のみがこれを参照する。

形式装置は (a) しか支えない。(b) を実現する入力路は式2・式3に無い。にもかかわらず (b) を要求する例が Action Classification に置かれている。両者は調停されていない。

### 【解釈】この不整合により Defer の例は AARM 準拠実装で記述通り実現できない

上記の帰結として、Context-Dependent Defer の当該例は、準拠要件を満たす (a, C) 評価器では記述通りに実現できない。窓の内外という判別変数を評価入力として表現する手段が形式側に無いためである。

### 【解釈】これは形式論理の非一貫ではなく、実質的な不整合である

式2・式3は形式体系として内部で一貫しており、そこから P ∧ ¬P が導けるわけではない。問題は形式体系の内部にあるのではなく、非形式的な Action Classification（E 依存の Defer を認める）と形式モデル（E を評価入力から締め出す）の間にある。両者は調停されておらず、論文はこの不整合を自覚せず放置している。正確には「未調停の二役と、それに起因する実現不能な例」であり、本メモはこれを不整合と呼ぶ。震源は形式側の破綻ではなく、例が装置の入力表現力を超えて環境識別子を判定変数として語っている点にある。

### 【解釈】E の除外は意図的な線引きの可能性があり、その場合も例の勇み足は残る

E を評価タプル (a, C) から外したことは、論文の見落としではなく意図的な線引きである可能性がある。環境要件は E ごとに固有で、汎用仕様として——任意の E に通用する有限の信号集合として——(a, C) に定式化して畳み込むことはできない（特定の E に固定すればその環境要件は定式化できるが、それは汎用仕様ではない）。もし AARM が最初から「session 由来で汎用に定式化できる信号（δ 等）のみを評価対象とし、環境状態に応じて実行を許可／拒否する制御は AARM の外（インフラ）に委ねる」という設計思想を採っていたなら、E を評価入力から外すのは一貫した選択になる。§6 で見た V.C.4 の admission sentence「requires complementary infrastructure-level protections beyond AARM's session-level controls」は、この役割分担——session-level に汎用定式化できるものだけを AARM が持ち、環境依存はインフラへ——と整合する。

ただし論文はこの意図を明記しておらず、これは本メモの解釈である。そしてこの読みを採っても、§2 の Context-Dependent Defer の例（メンテナンスウィンドウ外）が残す問題は消えない。E を意図的に外したのであれば、判定を分ける例に環境識別子を使ったこと自体が線を踏み越えている。したがってこの読みは不整合を解消するのではなく、その性格を変える——「E を入力に通し忘れた」不整合から、「E を意図的に外したのに例だけがその線を越えている」不整合へ。震源が形式側の抜けから例の勇み足へ寄り、これは本節前段の記述（震源は例が装置の入力表現力を超えて環境識別子を判定変数として語っている点）と整合する。

---

## 6. 脅威モデルにも同じ入力チャネル不在が現れる（V.C.4 Environmental Manipulation）

### 【論文】Environmental Manipulation と "AARM Partial Mitigation"（V.C.4）

脅威 Environmental Manipulation は、敵対者が環境（ファイル・API 応答・設定状態・データベースレコード）を改変し、エージェントがそれを ground truth として処理することで、偽の前提に基づく行動を誘発するものと定義される。論文はこれに対する AARM の部分的低減策（"AARM Partial Mitigation"）として三つを挙げる:

> Input provenance tracking records the source and integrity of data the agent processes, enabling detection when environmental inputs deviate from expected baselines. Anomaly detection flags unexpected changes in environmental state, and environment sandboxing can limit the scope of environmental data the agent treats as authoritative.

そのうえで限界を認める:

> Like memory poisoning, environmental manipulation requires complementary infrastructure-level protections beyond AARM's session-level controls.

### 【解釈】三策はいずれも (a, C) 上の機構ではなく、(1)(2) の AARM への帰属だけが不整合として残る

三策はすべて "AARM Partial Mitigation" の見出しの下にあり、論文はこれらを AARM の部分的対策として同格に帰属している。どれが AARM でどれがインフラ側かを論文自身は区別していない。区別するのは本メモの解釈であり、その物差しは一つ——「これは (a, C) 上で評価できる機構か」である。この物差しでは三策はいずれも (a, C) 上の機構ではない。ただし (a, C) を超える仕方が二種類に分かれる。

- **(1) input provenance tracking → 環境入力の期待ベースライン逸脱検出**: この策の重心は mechanism 名の provenance tracking ではなく、それが目的とする "enabling detection when environmental inputs deviate from expected baselines" にある。provenance tracking そのもの（エージェントが処理するデータの source と integrity を記録する）は、処理した出力 o の来歴を残すセッションレベルの操作として読む余地があり、それだけなら (a, C) 内で完結しうる。不整合を負っているのは目的節の方である。逸脱検出は、E の期待状態のベースラインを保持し、現在の環境入力をそれと突き合わせることを要する。(a, C) は E の状態のベースラインを持たず、§4 の通り環境データは実行済み read アクションの出力 o として入るのみで、逸脱判定に要する「期待される E の状態」は (a, C) の外にある。したがって逸脱検出は (a, C) では実現できない。
- **(2) anomaly detection on environmental state**: 「環境状態の予期しない変化を検出する」。これは E の状態を読み、その変化を追うことを直接要求する。§3 の通り (a, C) に E の状態を読む経路はない。δ の semantic distance / scope expansion はエージェントの行為系列に対するセッション由来の信号であって、E の状態の観測ではない。
- **(3) environment sandboxing**: 「エージェントが authoritative として扱う環境データの範囲を限定する」。これはそもそも (a, C) 上のポリシー評価ではなく、その範囲を外側から限定するインフラ境界制御である。これを「インフラ側」と切り分けるのは論文が明示する区別ではなく本メモの解釈だが、その解釈は末尾の admission sentence が挙げる complementary infrastructure-level protections に対応する。

物差しの帰結はこうである。末尾の "requires complementary infrastructure-level protections beyond AARM's session-level controls" は (3) を覆う——(3) はそこで言う infra 側の対策そのものだからである。しかし同じ admission sentence は (1)(2) を覆わない。(1)(2) は infra 境界制御ではなく、システムが行う「検出（detection / flags）」として提示されており、それでいて E の観測を要するため (a, C) では実行できない。infra 側にも属さず (a, C) でも実行できない (1)(2) が "AARM Partial Mitigation" として AARM に帰属させられている——これが §1–§5 の「E は (a, C) の入力ではない」不整合の、脅威モデルにおける同型の再出現である。(3) は不整合の証拠ではなく、admission sentence が整合的に回収する側の例にすぎない。

---

## 7. #87 との接続

### 【解釈】#87 の「環境という文脈を見ている」という解釈は接地を誤っていた

#87 の起点は「環境条件を含む判定条件をどう扱うべきか、どうポリシーに落とすべきか」であった。式2・式3を見れば、C に E は含まれない。環境運用状態は C の構成要素のいずれでもない。したがって #87 当時の解釈「『環境という文脈』を見ている」は接地を誤っていた。C は環境の文脈を保持していない。#87 の起点の問いは、図らずも本メモが記述した論文の穴を正面から突く問いになっている。

---

## 関連

- AARM 論文 arXiv:2602.09433: §IV-A-2（Formal Model、環境 E の定義）、§IV-A-4（Execution Effects、出力 o と影響 e）、§IV-B-4（Context-Dependent Defer とその例）、式2（Context Accumulation）、式3（Policy Structure）、§IV-C（派生信号 δ）、§V-C-4（Environmental Manipulation と AARM Partial Mitigation）
- 同ディレクトリ: [`classification-and-policy-model.md`](./classification-and-policy-model.md)（Table I とポリシー評価モデル。match predicate が参照できる範囲を扱う）、[`deferral.md`](./deferral.md)（DEFER トリガー R3 と FRAMEWORK/CONFORMANCE 章の食い違い。E 依存の Defer は confidence 不足による保留と地続き）
- laarma の設計判断（本メモを土台とする）: [`../design/environment-demo-fiction.md`](../design/environment-demo-fiction.md)（環境要件を汎用仕様として定式化せず、AS IS の環境条件をデモフィクションとして踏襲する判断。#110）
- 関連 Issue: #87（環境条件を含む判定条件の扱い）、#94（IA の signal/decision 分離）、#107（match 条件で δ を参照できるようにする拡張）、#110（環境要件を参照するポリシーをどう受けるか）
