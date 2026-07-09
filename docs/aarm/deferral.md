# AARM 解釈メモ: DEFER のトリガー条件と confidence

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは **AARM 論文（外部仕様）が DEFER について何を言っているか**を
> 読み解く解釈メモである。laarma 自身の設計判断は書かない（それは `docs/design/` の役割）。
> 分類フレームワーク全体の解釈は [classification-and-policy-model.md](classification-and-policy-model.md) にあり、
> 本メモはそのうち DEFER に焦点を当てて深掘りしたもの。#89（DEFER 解決機構）の土台にもなる。
>
> **記述の区別**（本メモの恒久的な構成）:
> - **【論文】** は AARM 論文が明示的に述べていること（引用・要約・翻訳）。
> - **【解釈】** は論文が明示していない構造の読み解き、または論文の曖昧さ・不整合の指摘。根拠を添える。
>
> **出典・ライセンス**: 参照・引用・翻訳する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。

---

## 1. 論文には DEFER のトリガーが二箇所にあり、抽象度が異なる

### 【論文】FRAMEWORK 章（§IV-B-4）の DEFER 記述

FRAMEWORK 章は Context-Dependent Defer を「評価時点でリスクが確定できないアクション。利用可能な
コンテキストが不十分・曖昧・内部矛盾しているとき、potentially unsafe な allow/deny に committing する
のでなく実行を一時保留する」と説明し、具体例として「ルーチンのメンテナンス窓の外での認証情報ローテーション」
（正当かもしれないが、ユーザ要求が曖昧・先行アクションが明確なワークフローを確立していない・タイミングが非典型）
を挙げる。そして DEFER に値する状況を4つ列挙する:

1. High-impact action with insufficient confidence for allow or deny（高影響だが allow/deny に十分な confidence がない）
2. Ambiguous intent or conflicting contextual signals（曖昧な意図、または矛盾する文脈信号）
3. Composite risk that is unclear given incomplete action history（不完全なアクション履歴ゆえに不明な複合リスク）
4. Actions whose safety depends on information not yet available in the session（安全性がセッション未取得の情報に依存するアクション）

### 【論文】CONFORMANCE 章（R3）の DEFER トリガー

R3 は deferral が MUST triggered となる条件を3つ挙げる:

- (a) a policy rule's match predicate references context fields that are not yet populated in the session（match predicate が未 populate の context フィールドを参照）
- (b) multiple applicable policies produce conflicting decisions at the same priority level（同一 priority で複数ポリシーが矛盾する決定）
- (c) a confidence score (if implemented) falls below a deployment-configured threshold（confidence スコア〔実装されている場合〕が閾値未満）

さらに「The conditions triggering deferral MUST be documented and auditable（DEFER をトリガーする条件は文書化され監査可能でなければならない）」。

### 【解釈】二つの記述は抽象度が異なる（矛盾ではなく informative / normative の二層）

FRAMEWORK 章の4項目と CONFORMANCE 章の (a)(b)(c) を対応させると、素直に対応しない部分がある:

| FRAMEWORK 章（状況・why） | CONFORMANCE 章（機構・how, MUST） |
|---|---|
| 1. 高影響だが confidence 不足 | (c) confidence < 閾値（「高影響」の部分は対応先なし） |
| 2. 曖昧な意図 or 矛盾する文脈信号 | 直接対応なし（(c) に押し込めるか、(b) に近いが (b) は「ポリシー矛盾」で「文脈信号の矛盾」とは別） |
| 3. 不完全な履歴ゆえの複合リスク | 直接対応なし |
| 4. 安全性がセッション未取得情報に依存 | (a) 未 populate context 参照 |
| （対応する FRAMEWORK 項目なし） | (b) 同一 priority のポリシー矛盾 |

- **1 ↔ (c)**、**4 ↔ (a)** は対応する。
- **2（矛盾する文脈信号）と 3（複合リスクの不明さ）は、(a)(b)(c) に素直に対応しない**。特に 3 は (a)(b)(c) のどれでもない。2 の「conflicting contextual signals」は (b)「ポリシー矛盾」と紛らわしいが、**文脈信号（δ）の矛盾**と**ポリシー設計の矛盾**は別物である。
- 逆に **(b)（同一 priority のポリシー矛盾）は FRAMEWORK 章の4項目に対応がない**。(b) は文脈側の問題ではなくポリシー設計側の問題で、FRAMEWORK の「状況」リストには現れない。

**これは論文の欠陥・矛盾ではなく、規格文書の標準的な二層構造である。** FRAMEWORK 章は DEFER に値する状況を**ナラティブ・抽象的**に描く informative な記述、CONFORMANCE 章 R3 は適合性を判定するための**客観的に検証可能**な normative な記述で、両者は抽象度が異なる。規格起草のドクトリンはこの二層を意図的に分ける——ISO/IEC Directives Part 2 は要件を「客観的に検証可能な基準」と定義して検証可能なものだけを規範条項に含めよと定め、W3C QA Framework は「informative なテキストは適合の合否を決めない／各 MUST 要件からテスト表明を導け」とする。すなわち **informative（ナラティブ）が normative（検証可能条項）より広い射程を持つのは、よく設計された規格では正常であり、適合性は検証可能条項に対してのみ判定される**。要求工学ではこれをゴール（抽象・宣言的）の operationalize（検証可能要件への具体化）と呼び（goal-oriented requirements engineering）、形式手法では抽象レベルの振る舞いの一部だけを具体レベルが捉える構造を retrenchment と呼ぶ。R3 が §IV-B-4 を部分的にしか掬わないのは、この意味での under-specification（informative over-reach）であって、矛盾ではない。

**適合性の帰結**: したがって、適合性（conformance）は normative な R3(a)(b)(c) に対してのみ判定される。FRAMEWORK 章の informative な記述のうち R3 に対応しないもの（#2「矛盾する文脈信号」・#3「複合リスクの不明さ」）は、適合性の要件ではなく、それを追加で実装しなくても AARM に conformant である。むしろ informative の記述を根拠に「これも満たすべき要件だ」と読み取ることは、informative に規範的効力を持たせることであり、規格の読み方として誤りである。実装が FRAMEWORK 章まで捉えたい場合、それは AARM の適合要件だからではなく、実装側の**独自の設計選択**として行う（laarma がそうするかは [../design/decision-layer-policy-engine.md](../design/decision-layer-policy-engine.md) の領分。本メモ＝論文の読みとしては「適合性としては R3 で足りる」までを述べる）。なお #3「不完全な履歴ゆえの複合リスク」が (a)(b)(c) に対応しないのは、有限のプレフィックス（それまでの履歴）からは複合リスクを確定できない——ランタイム検証でいう monitorable でない性質＝判定保留（inconclusive）——という側面もある（[research/](research/) 参照）。

### 【解釈】FRAMEWORK は未知の未知まで含みうるが、DEFER が扱えるのは既知の未知（未知の未知は DENY）

FRAMEWORK 章の抽象的記述、特に #4「安全性がセッション未取得の情報に依存する」は、**何を見るべきかすら特定しない広さ**を持ち、読みようによっては *未知の未知*（関連性がそもそもポリシーに表現できない情報）まで含む。一方 CONFORMANCE 章 R3(a) は具体的で、「match predicate が参照する context フィールドが未 populate」——参照先はポリシーに**書けている（何を見るべきかは既知）**が値が未確定、という *既知の未知* に限定される。しかも R3(a) の「未 populate を検知して DEFER する」主体は**ルールを評価する runtime システム**であって、ルールは参照するだけである（ルールが自分の参照先の欠落を表明するのではない）。

この既知/未知の未知の区別は、DEFER という動作の性質から導かれる。**DEFER（＝特定された情報が揃うまで実行を保留し、追加取得を待つ）が意味を持つのは、待つべき情報が特定できる既知の未知に限られる。** 決定理論はこれを裏付ける: value of information は**既に表現された状態空間の中**の不確実性を解消する価値としてのみ定義され（Howard 1966）、標準的な状態空間モデルは unawareness を表現できず（Dekel–Lipman–Rustichini 1998）、状態空間を拡張する価値（value of awareness）と空間内の情報価値（value of information）は別物である（Quiggin 2016）。すなわち「情報を待って解決する」動作は、待つべき対象が状態空間に表現されていること＝既知の未知を前提とする。

**未知の未知——参照先をルールに書けず、待つべき対象が特定できないもの——は、DEFER の対象にならない。** 待つべき具体的対象が無いため保留しても解決の見込みが無く、fail-closed の原則に従って DENY に落ちる。これは AARM の fail-closed 姿勢（R4 の「timeout は DENY、fail-open は許されない」）とも、laarma の実装（予期しない例外は DENY）とも整合する。

**注意（用語の混同を避ける）**: AARM の DEFER は「特定情報を待つ保留」という具体的動作であって、「棄権（abstention）一般」ではない。機械学習の reject option では、分布外・未知の入力に棄権する *novelty rejection* が正当な棄権として認められるが、それは AARM の語彙では DEFER ではなく DENY／エスカレート側に対応する。DEFER を「棄権一般」と読み替えて「未知の未知にも DEFER しうる」と結論するのは、指す動作の異なるものを同一視するカテゴリ錯誤である。

### 【解釈】(c) は任意実装なので (a)(b)(c) は MECE ではない

R3 の (c) は「confidence score (**if implemented**)」——任意実装である。(a)(b) は MUST だが (c) は
実装されないこともあり、(c) を除いてもシステムは DEFER を出せなければならない。一方で、FRAMEWORK 章の
「曖昧な意図」「矛盾する文脈信号」を confidence の減点計算に反映する実装を採れば、それらは (c) でも捉えられ、
決定論で書けば (b) 的にも捉えられる。すなわち **(a)(b)(c) は排他的な MECE な分割ではなく、同じ状況が
複数のトリガーで捉えられうる**。confidence（(c)）は、他のトリガーで捉えられる曖昧さ・矛盾も含めて
反映されうる、広い受け皿の性格を持つ。

---

## 2. confidence とは何か

### 【論文】confidence の定義

論文の δ 定義（§IV-C）で confidence level は「The system's confidence in **evaluating** the current
action, informing allow/deny/defer decisions」——アクションを**評価すること**へのシステムの confidence。
「アクションが危険か」ではなく「アクションを評価しきれているか」。計算方法は論文では未定義（R3(c) が
「if implemented」「deployment-configured threshold」と述べるとおり、実装依存・デプロイ設定）。

### 【解釈】confidence = 評価可能性（evaluability）、危険性とは独立の軸

論文の定義「confidence in evaluating」は、confidence が**評価可能性（evaluability）**——判定をどれだけ
確証できるか——を表すことを示す。これは危険性（アクションがどれだけ危険か）とは独立の軸である。

この二軸の分離は業界実践にも見られる。脆弱性スキャナ **Burp Scanner** は、検出した各問題に対し二つの
独立した軸を出す:

- **Severity**（High / Medium / Low / Information）: 典型的な組織にとっての影響の大きさ（likely impact）。= 危険性。
- **Confidence**（Certain / Firm / Tentative）: その問題を特定した技術の信頼性、すなわち「本物の脆弱性である確証度」。形式的検査で確証できず内部ロジックを見ないと判定できないものは Tentative になる。= 評価可能性。

severity と confidence は独立で、高 severity かつ低 confidence（危険だが確証しきれない）もありうる。
この分離は、confidence を「評価しにくいものを何でも押し込むゴミ溜め」にしないための線引きを与える:

- confidence（evaluability）が表すのは「評価が確証できるか」——context 不十分、信号の矛盾で判定が定まらない、意味論的な曖昧・矛盾で確証できない。
- 危険性（severity 相当）は confidence とは別軸——data classification × 破壊性、複合リスクの大きさ。

（laarma がこの二軸をどう実装に落とすか——confidence をどう計算し、危険性をどうポリシー条件で表現するか——は
設計判断であり `docs/design/` で扱う。本メモは「論文の confidence 定義は evaluability と読め、危険性とは
独立の軸である」という解釈を記録する。laarma 側の既存整理は `docs/design/risk-classification.md` の
「confidence ≠ 危険性」とも一致する。）

### 【解釈】FRAMEWORK 章4項目の軸への帰属

上記の二軸（評価可能性 / 危険性）で FRAMEWORK 章の4項目を分けると:

- **1 高影響だが confidence 不足**: 「高影響」は危険性軸、「confidence 不足」は評価可能性軸。両者の組み合わせ。
- **2 曖昧な意図・矛盾する文脈信号**: 評価可能性軸（判定が確証できない）。
- **3 複合リスクの不明さ**: 二軸に分解。**複合リスクの大きさ**は危険性軸、**それが「不明」であること**は評価可能性軸。高リスクかつ低 confidence（危険だが評価しきれない）がありうる。
- **4 未取得情報依存**: 評価可能性軸だが、参照先がポリシーに書けている既知の未知に限り CONFORMANCE (a)（未 populate context 参照）で捉わる（未知の未知は §1 の通り DEFER の対象外で DENY）。

このうち「危険性」に属する部分（1 の高影響、3 の複合リスクの大きさ）は confidence に混ぜず、危険性軸として
扱うべき、というのが二軸分離から導かれる読みである。

---

## 3. DEFER 後の扱い（入口と解決の分離）

### 【論文】DEFER 後の要件（R4）

R4 は DEFER 後の扱いを定める:
- 十分な context が集まる・追加検証が行われる・安全な制約が適用されるまで実行を保留（MUST）。
- deferred action を追跡し、他操作との実行順序を維持（MUST）。
- 自動または人間支援による解決の機構を提供（SHOULD）。
- **high-risk operation の premature execution を避ける**（MUST）。
- 設定可能なタイムアウトを強制、タイムアウト時は DENY がデフォルト（MUST）、fail-open は許されない（MUST NOT）。
- deferred action が依存アクションをブロックする場合、依存側も defer（MUST）。独立アクションは進行してよい（SHOULD）。
- cascading deferral は有界（設定上限を超えたら以降を DENY、MUST）。
- deferred action は receipt に deferral reason を記録、解決/タイムアウトは follow-up receipt を生成（MUST）。

### 【解釈】入口（DEFER するか）と解決（どう解決するか）の分離

R3（トリガー）と R4（DEFER 後）を合わせると、DEFER は二段に分かれて読める:

- **入口**: 決定層が「DEFER するか」を (a)(b)(c) ＋ FRAMEWORK 章の状況で判定する。ここでは「曖昧さ・矛盾の中身」までは判定しない——DEFER に落とすかどうかだけ。
- **解決**: DEFER 後に、追加情報・制約・人間監督で解決する。「曖昧さ・矛盾が何で、どう解決するか」「high-risk なら premature execution を避ける」はここで扱う。

論文が R3（入口の最小トリガー）と R4（解決の要件）を分けて規定していることから、この二段構造が読み取れる。
「入口で δ による危険性の細分をせず、解決フェーズに委ねる」という設計は、この分離に沿う
（[classification-and-policy-model.md](classification-and-policy-model.md) §5 の「測定と評価の二段」とも整合）。

### 【解釈】論文は解決機構を規定しておらず、「解決の一手ごとに DEFER を返す」ことを禁じない

R4 が定めるのは DEFER **後**の要件（十分な context が集まるまで保留・追跡・タイムアウト → DENY・cascading の有界化・receipt）であって、**解決を内部でどう進めるか（解決機構）は規定していない**。R4 は SHOULD で「自動または人間支援による解決の機構を提供」とするだけで、その機構が一手でどう判定を出すかは論文の規定外である。

ここから次の短絡を避ける必要がある。**R4 が列挙する解決経路（十分なコンテキスト収集／追加検証／safe constraints の適用 → 実行、または timeout → DENY）に DEFER が現れないことをもって、「解決先に DEFER を含めてはならない（DEFER→DEFER 禁止）」と読むことはできない。** 論文は解決先を {ALLOW, DENY, STEP_UP} 等へ明示的に限定列挙しておらず、列挙の沈黙を禁止と読むのは短絡である。

反例で示せる。解決機構が「追加コンテキストを集めて再評価する」ポーリング型で、再評価してもまだ確定できなければもう一度 DEFER を返して待つ——この実装は R4 の「十分な context が集まるまで保留」「タイムアウトまで待つ」と整合し、正当である。「DEFER→DEFER 禁止」と読むと、この正当なリトライ型実装を仕様違反にしてしまう。

R4 から言えるのは**有界性**まで——cascading deferral は設定上限で DENY、タイムアウトで DENY——であり、「DEFER は無限には続かない」。これと「解決の一手ごとに DEFER を返してはならない」は別物で、前者は論文にあるが後者は導けない。したがって laarma がどの解決型（一発解決型／リトライ型）を採るかは、論文が縛らない**設計判断**であり、`docs/design/`・#89 の領分である。

---

## 関連

- 分類フレームワーク全体の解釈: [classification-and-policy-model.md](classification-and-policy-model.md)
- 本メモの外部理論の裏付け調査: [research/](research/)（規格の informative/normative 二層・既知/未知の未知・monitorability・value of information 等の学術的裏付けと非存在の整理）
- laarma の設計判断（本メモを土台とする）: [../design/decision-layer-policy-engine.md](../design/decision-layer-policy-engine.md)（DEFER トリガーの統合・confidence 計算・多層防御 LLM）、[../design/risk-classification.md](../design/risk-classification.md)（confidence ≠ 危険性）
- AARM 論文 arXiv:2602.09433: §IV-B-4（FRAMEWORK 章 DEFER）、R3（DEFER トリガー a/b/c）、R4（DEFER 後の要件）、§IV-C（δ 定義・confidence）
- 参照した外部理論（詳細と出典は research/）: 規格の informative/normative 二層（ISO/IEC Directives Part 2、W3C QA Framework）、ゴール指向要求工学、retrenchment（Banach & Poppleton 1998）、value of information と unawareness（Howard 1966、Dekel–Lipman–Rustichini 1998、Quiggin 2016）、monitorability（Bauer–Leucker–Schallhart 2011）、reject option（Hendrickx et al. 2024＝DEFER と棄権一般の混同を避ける文脈で参照）
- 参照した業界実践: Burp Scanner の severity × confidence 二軸分類（PortSwigger）
- 関連 Issue: #89（DEFER 解決機構）、#77（confidence 較正）、#100（composite risk = 危険性軸）、#94（signal/decision 分離）
