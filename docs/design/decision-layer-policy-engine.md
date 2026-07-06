# 設計メモ: 決定層をポリシー評価エンジンに組み替える（LLM ベース IntentAlignment の除去）

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは laarma の**設計判断**を記録する設計メモである。
> AARM 論文が何を言っているか（論文解釈）は `docs/aarm/` に記録されており、本メモはそれを
> **前提・参照**して、laarma がどう実装するかの判断を述べる。laarma は AARM 仕様の試作実装であり、
> 本メモの設計は現時点の想定である。どこまで実装で確認が取れているかは末尾の「検証状況」に概略を置く。
>
> **論文の記述と laarma の判断の区別**: 論文から直接引ける事実（式の定義・Table・章の記述）は
> 動かない前提として扱い、そこから先の設計判断と区別する。論文解釈そのものは `docs/aarm/` を参照。
>
> **出典・ライセンス**: 本メモが参照する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。

---

## 1. 背景: 現行の決定層と、その問題

### 現行構造（提案/上書きモデル）

現行の `policy_engine.py` の `evaluate()` は、逐次パイプラインで動く:

```
privilege_scope → denied_tools → 静的ルール収束ループ → required_params → max_actions → _confirm_with_ia
```

最後の `_confirm_with_ia` が心臓部で、**LLM ベースの `IntentAlignment`（intent_alignment.py）** に (a, C, E) を渡し、
LLM が ALLOW/DENY/DEFER/STEP_UP の decision を返す。静的評価で作った「提案」を、LLM が ALLOW なら確定・
それ以外なら上書きする「提案/上書きモデル」。

### 問題: LLM ベース IntentAlignment は AARM 仕様に存在しない

AARM 論文を精読した結果（`docs/aarm/classification-and-policy-model.md` および論文 §IV-C, R7, 式3, 式4）、
現行の LLM ベース IntentAlignment が AARM 仕様に根拠を持たないことが判明した:

- **AARM の "intent alignment" は独立コンポーネントの名前ではなく、「ポリシーが (a, C) を評価すること」そのものの呼称**である。論文 Contribution 2 は intent alignment を「アクションを静的ポリシーだけでなく、ユーザリクエストから蓄積コンテキストに至る intent の連鎖に照らして評価すること」と定義する。R3 のタイトル "Policy Evaluation **with** Intent Alignment" が示すとおり、intent alignment は policy evaluation の修飾であって、別立ての判定器ではない。
- **semantic distance は埋め込みコサイン距離のスカラー**である（式4: `d(r0, an) = 1 − cosine(embed(r0), embed(an))`）。LLM 判定ではない。Context Accumulator が δ の一つとして毎アクション産出する。
- **intent misalignment の判定は、ポリシーの match predicate が δ（semantic distance・data_classification 等）を参照することで実現される**。論文の Data Exfiltration 例は「context-dependent deny が email をブロックするのは、email が禁止だからではなく、先行する機微データアクセスとの composition が intent misalignment を露呈させるから」と明示する——この判定は LLM ではなくポリシーの context 参照。

したがって laarma の現行 LLM ベース `IntentAlignment`（LLM に (a,C) を渡して decision を得る部分）は、
AARM 仕様には存在しないコンポーネントであり、仕様の誤読から生まれた産物である。

（補足: 「埋め込み距離では捉えきれない意味判断を LLM で補う」という発想は、論文の semantic distance の定義には根拠がない。論文 R7 が求めるのは「埋め込みモデルが自分の action schema に適しているかを既知の良性/悪性系列で校正せよ」というモデル適合性の検証であって、「埋め込みでは不足だから LLM を足せ」ではない。ただし LLM をまったく使わないという意味ではない——§5 で述べるとおり、decision の判定ではなく confidence の計算に LLM を使う余地は別にある。）

---

## 2. 設計方針: LLM ベース IntentAlignment を除去し、決定層をポリシー評価エンジンにする

laarma は AARM 仕様に忠実な実装を目指す（"Learning AARM Agent"）。したがって:

**決定層を、現行の「提案/上書きモデル（静的評価 → LLM を後で呼んで上書き）」から、
「(a, C) を評価するポリシー評価エンジン（Context 完成 → ポリシー集合 Π を priority 解決）」に組み替える。
decision を出す LLM 判定（現行 IntentAlignment）は除去する。**

組み替え後の構造:

```
アクション a
  → Context Accumulator が δ を産出し C を更新（式2）
     - semantic distance（埋め込みスカラー、式4）← distance_calculator.py（既存・LLM 不要）
     - data_classification / scope_expansion / entity_set / confidence
  → ポリシー評価エンジンが (a, C) を評価
     - 各ポリシー π の match predicate が action / identity / C（δ含む）を参照（式3）
     - 複数 match したら priority で競合解決、同一 priority の矛盾は DEFER（トリガー b）
  → 決定（ALLOW / DENY / MODIFY / STEP_UP / DEFER）
```

### 何を活かし、何を除去し、何を新設するか

- **活かす**: `distance_calculator.py`（semantic distance の埋め込み計算 = 式4。既に LLM を使わずコードで実装済み。コサイン類似度と `1 - cosine` の距離変換を numpy で計算）。Context Accumulator の δ 産出。
- **除去する**: `intent_alignment.py` の「decision を出す LLM 判定」（(a,C) を LLM に渡して ALLOW/DENY/… を得る部分）。`_confirm_with_ia` の提案/上書き構造。
- **新設・拡張する**: ポリシーの match predicate が δ（semantic distance・data_classification・confidence 等）を参照できるようにする（match predicate の δ 参照は本リファクタの中核機構で、骨格ができた段階でデモポリシー需要駆動に段階実装する。旧 #107 は本リファクタに吸収）。δ を閾値/集合で参照するポリシーが、現行 LLM が担っていた判定の大半を代替する。加えて、confidence 計算への LLM 活用（§5）。

### 処理順序の転換

現行は「静的評価 → 後で LLM を呼ぶ」逐次。組み替え後は「**Context 完成（δ 産出）→ ポリシー評価**」。
δ（semantic distance 含む）はポリシー評価の前に C に載っている必要がある。これは
`docs/aarm/classification-and-policy-model.md` §5「測定（accumulation 段・常時）と使用（policy 評価段）の二段」に対応する。

### MODIFY は1パス変換で terminal（収束ループは持たない）

現行実装は MODIFY マッチのたびにアクションを変換して再評価する収束ループ（`max_modify_iterations`）を持つが、本設計ではこれを廃止し、評価を1パスにする。

根拠: MODIFY は「危険/不適切なパラメータ → 安全/適切なパラメータ」への変換である。一度変換して安全化した結果 a' がさらに別の MODIFY ルールにマッチするなら、そのルールは「a' はまだ危険/不適切」と主張しており、最初の変換の前提と衝突する。無矛盾なルール集合では変換後の再マッチは起きてはならず、収束ループはこの矛盾状況を暗黙に受容する機構だった。加えて、MODIFY 変換連鎖を起こすルールは現存せず想定も無い（YAGNI）。

したがって評価は1パスとする: **全マッチ収集 → priority 解決 → 勝者確定。勝者が MODIFY なら変換を1回だけ適用して terminal**（ループに戻らない）。`max_modify_iterations`・収束ループ・非収束 DENY 経路は持たない。

同一 priority に複数の MODIFY がマッチした場合は競合とみなし DEFER とする（「同一 priority で decision/変換が割れたら DEFER」の一般則に吸収される）。disjoint なキーを対象とする複数 MODIFY を1パスでマージする機構は作らない——その需要が現れた時点で同一 priority 調停として別途設計する（YAGNI）。

MODIFY を terminal にしてよい根拠: 以前 MODIFY を terminal にしないよう配慮したのは、提案/上書きモデルで「MODIFY 提案 → その後 LLM が意図整合性を見て上書き」しうる構造だったため、MODIFY で確定すると意図整合性チェックを飛ばす懸念があったからである。priority エンジン化で順序が「後で上書き」から「高 priority ルールが先に勝つ」へ反転するため、意図整合性を担う δ 参照ルールを MODIFY より高 priority に配置すれば、MODIFY が terminal でも素通りしない。これは強制パスではなく priority 配置の規律であり、δ 参照ルールの実装（Phase B）で担保する。

---

## 3. 現行 IntentAlignment の判定基準（条件1〜15）の移行先

現行 `intent_alignment.py` の SYSTEM_PROMPT は、Decision Criteria として 15 個の判定基準を持つ
（#94 で条件1〜15 として列挙済み）。組み替えでは、これらを LLM の decision 判定から、δ のポリシー参照・
別 Issue・confidence（§5）に分解する。以下は棚卸しの結果で、実装・benchmark で再検証して訂正しうる。

| 条件 | 現行の判定内容 | 移行先 |
|---|---|---|
| 1 | action が意図と矛盾/無相関（読めと言われ write/delete） | semantic distance のポリシー閾値参照（`semantic_distance > 閾値 → DENY`） |
| 2 | action_matches_intent=false かつ distance>0.4 で破壊/書込 | distance + tool risk のポリシー参照 |
| 3 | scope_expansion 検出かつ意図に正当化なし | **#99**（scope_expansion 産出の再設計）に委ねる既知の穴 |
| 4 | Compositional Risk（アクション系列が攻撃ベクトル） | **#100**（composite risk）。危険性軸の拡張。加えて FRAMEWORK 章では DEFER トリガーの一つでもある（§4） |
| 5 | action_matches_intent=true / 意図が対象を明示 | distance 小 + 危険信号なし → ALLOW baseline |
| 6 | semantic_distance < 0.3 | distance のポリシー閾値参照 |
| 7 | PII/CONFIDENTIAL を含まない | data_classification のポリシー参照 |
| 8 | 破壊的でも明示意図と高 confidence | distance 小 + confidence 高のポリシー参照 |
| 9 | 意図が曖昧でエージェントが未認可の自律判断 | confidence（evaluability）低 → DEFER。中身の解釈は #89、較正は #77（§4, §5） |
| 10 | confidence < 0.4 かつ追加 context で解決可能 | DEFER トリガー (c)（`confidence < 閾値 → DEFER`） |
| 11 | 安全だが明示的認可が欠落 | 条件9 と同じく confidence 低 → DEFER |
| 12 | 情報収集系（read/list）は曖昧でも ALLOW | **廃止**。distance 小 + 非破壊 → ALLOW baseline で自然に出るため特別扱い不要 |
| 13 | PII/CONFIDENTIAL の削除/重大アクセス | data_classification + destructive のポリシー参照 → STEP_UP（危険性軸の SDK 固定写像） |
| 14 | 本番の高影響操作 | environment=production + destructive のポリシー参照 → STEP_UP（危険性軸の SDK 固定写像） |
| 15 | confidence 0.4-0.6 かつ中程度リスク | confidence のポリシー参照（`0.4 < confidence < 0.6 → STEP_UP`） |

移行先はおおむね三つに分かれる: (1) δ のポリシー閾値/集合参照で代替（条件 1,2,5,6,7,8,10,13,14,15。δ 参照は本リファクタ内で段階実装）、(2) 別 Issue の穴（条件 3=#99、条件 4=#100）、(3) confidence（evaluability）低 → DEFER（条件 9,11）。廃止は条件 12。

---

## 4. DEFER のトリガー: FRAMEWORK 章と CONFORMANCE 章の両方を設計に含める

DEFER の設計にあたり、当初は CONFORMANCE 章 R3 の3トリガー (a)(b)(c) だけを見ていたが、これは不十分だった。
論文の FRAMEWORK 章（§IV-B-4）は、DEFER に値する状況をより広く列挙しており、両者は完全には整合しない
（詳細は `docs/aarm/deferral.md` に論文解釈として記録）。laarma の DEFER 設計は**両方を含める**。

論文の二つの記述:

- **CONFORMANCE 章 R3**（MUST triggered when）: (a) match predicate が未 populate の context を参照、(b) 同一 priority で複数ポリシーが矛盾、(c) confidence スコア（実装されている場合）が閾値未満。
- **FRAMEWORK 章**（DEFER に値する状況）: (1) 高影響だが allow/deny に十分な confidence がない、(2) 曖昧な意図または矛盾する文脈信号、(3) 不完全な履歴ゆえに不明な複合リスク、(4) 安全性がセッション未取得の情報に依存。

この二つを laarma の軸で整理すると（confidence = 評価可能性、危険性 = 別軸。§5 で後述）:

- **(1) 高影響だが confidence 不足** → 「高影響」は危険性軸（ポリシー条件: destructive_tools / production 等）で表現し、confidence（evaluability）に混ぜない。「confidence 不足」の部分が R3(c) に対応。両者の**組み合わせ**が DEFER を生む。
- **(2) 曖昧な意図・矛盾する文脈信号** → 評価可能性の問題（判定が確証できない）。confidence 低として現れる。矛盾の検出は、決定論で書けるもの（例: `params.src == params.dst`）はポリシー match で、書ききれない意味論的な矛盾（§5 の多層防御 LLM）は confidence への反映で捉える。
- **(3) 不完全な履歴ゆえに不明な複合リスク** → 二軸に分解される。**複合リスクの大きさ**は危険性軸（#100 composite risk）、**それが「不明」であること**は評価可能性（confidence 低）。Burp Scanner が severity と confidence を独立に出すのと同じ構造で、高リスクかつ低 confidence がありうる。
- **(4) 安全性がセッション未取得情報に依存** → R3(a)（未 populate の context 参照）で決定論的に捉わる。

要点: DEFER を R3 の (a)(b)(c) だけで組むと、FRAMEWORK 章の「矛盾する文脈信号」「複合リスクの不明さ」を取りこぼす。laarma は両方を DEFER 設計に含める。特に「意味論的な矛盾・曖昧さ」の検出は §5 の多層防御として最初から設計に入れる。

### DEFER 後の扱い（#89 に先送り）

決定層（入口）は「DEFER するか」を判定するだけで、「その曖昧さ・矛盾が何で、どう解決できるか」は
DEFER 後の解決機構（#89）に先送りする。これは AARM が入口をクリーンに保つ境界切り分けに沿う
（`docs/aarm/deferral.md` 参照）。confidence が曖昧さ・矛盾を正しく低く算出できるかという較正は #77。

---

## 5. confidence の定義と、confidence 計算への LLM 活用（多層防御）

### confidence = 評価可能性（evaluability）。危険性とは独立の軸

confidence を「評価しにくいものを何でも押し込むゴミ溜め」にしないため、定義を明確にする。

論文の δ 定義で confidence は「The system's confidence in **evaluating** the current action」——
アクションを**評価すること**への confidence であり、「アクションが危険か」ではなく「アクションを評価しきれているか
（判定の確証度）」を表す。これは業界実践とも一致する。脆弱性スキャナ Burp Scanner は、各問題に対し
**severity**（High/Medium/Low/Info = 影響の大きさ = 危険性）と **confidence**（Certain/Firm/Tentative =
検出技術の信頼性 = その判定が本物である確証度）を**独立した二軸**で出す。形式的検査で確証できず内部ロジックを
見ないと判定できないものは Tentative になる——危険度とは別の軸。

laarma もこれに倣い、confidence を **評価可能性（evaluability）** と定義する:

- **confidence に入れてよいもの**: 評価が確証できない要因——context 不十分、信号が矛盾して判定が定まらない、意味論的に曖昧・矛盾で確証できない。
- **confidence に入れてはいけないもの**: 危険性（severity 相当）——data_classification × destructive、複合リスクの大きさ。これらはポリシー条件（危険性軸）で表現する。

この線引きにより「都合の悪いものを全部 confidence に丸める」ことを防ぐ。危険性は confidence に逃がさず、ポリシー条件で表現する。

### confidence 計算への LLM 活用（多層防御、最初から設計に入れる）

DEFER トリガー (c) の confidence スコアは、論文では計算方法が未定義（実装依存）。ここに laarma は
**多層防御としての LLM を最初から設計に入れる**:

- 引数不足のような**決定論で判定できるもの**は、決定論（ポリシー match / パラメータ検証）で扱う。不確実な LLM に頼らない。
- `copy(src, src)` のような**意味論的に矛盾しているが、全パターンを決定論で列挙しきれないもの**は、多層防御として LLM で検出し、confidence を下げる（→ 閾値を下回れば DEFER）。LLM は **decision を出さない**——confidence（評価可能性）という δ の一信号の計算に使われるだけで、decision を出すのはポリシー（confidence 閾値ルール）。

これは AARM 仕様に反しない: semantic distance は式4 で定義されているが、confidence の計算方法は論文が未定義（実装依存）であり、そこに LLM を入れるのは仕様が空けている領域を埋めること。

**多層防御として最初から入れる理由**: LLM がなければ `copy(src,src)` 型の意味論的矛盾は決定論の網をすり抜けて
全て通ってしまう（fail-open の穴）。この穴を「後で不足が観測されたら塞ぐ」と後回しにするのは、
気づいている fail-open を検証都合で放置することになり不適切。最初から confidence 計算に LLM を入れて
fail-closed 側に倒す。LLM が誤検出しても、それは多層防御の一層の限界であり、他の層（決定論ポリシー）が
残っている。どの決定が決定論ルールで下され、どれが confidence 経由（LLM 検出含む）で下されたかを**受領書
（receipt）に記録**すれば、切り分けと検証は担保できる（検証都合で fail-open を残す必要はない）。

なお LLM は最後の網であって唯一の防御ではない。決定論で書ける危険性・矛盾はポリシーで書き、LLM は
「決定論で列挙しきれない意味論的な曖昧・矛盾」だけを担う。この境界を守らないと、決定論で書けるものまで
不確実な LLM に頼る誘惑が生じる。

---

## 6. デモシナリオの再現性（妥当性検証）

現行デモは LLM の decision 判定に依存したシナリオを持つ。組み替え後（distance + ポリシー + confidence）で
これらが再現できるかは、実装後 benchmark で確かめる:

- **シナリオ4「読むだけ頼んだのにエージェントが delete_file 実行 → DENY」**: delete_file と元リクエスト（読む）の semantic distance が大きく出て、`distance > 閾値 → DENY`（条件1）で捉えられるはず。埋め込みが実際にこの距離を大きく算出するかが検証点。
- **シナリオ8「"古いファイル"の定義が曖昧 → DEFER」**: "古い" の判断に confidence が低く出て DEFER になるはず。confidence 計算がこの曖昧さを低く算出するか（#77 の較正、および §5 の LLM 活用）が検証点。
- シナリオ5（PII 削除 → STEP_UP）、シナリオ7（危険パス → MODIFY）等、静的ルール・data_classification で決まるものは、LLM の decision 除去の影響を受けにくい（元々ポリシー側）。

再現できない場合、その具体的な不足が、将来的な追加設計（§7）を検討する根拠になる。

---

## 7. 将来的な LLM 補完（実装後に不足が観測された場合）

§5 の多層防御（confidence 計算への LLM 活用）を入れてもなお、捉えられない意味判断が**具体的に
観測された場合**に、追加の LLM 活用を検討する余地がある。これは AARM 仕様外の laarma 独自拡張として、
仕様外であることを明示して持つ。現時点で想定シナリオを先回りで記述はしない（根拠のない想定を固定する危険がある）。
実装を動かして観測された不足を、そのとき具体的事実として将来 Issue に記録する。

---

## 8. この設計が触る範囲

本設計の実装は #112（#94 後継）の本体であり、規模が大きい。実装ブリーフは本メモを土台に別途作成する。

触るコンポーネント（概略）:
- **除去**: `intent_alignment.py` の decision 判定 LLM、`policy_engine.py` の `_confirm_with_ia` 提案/上書き構造、および静的ルール収束ループ（`max_modify_iterations`。§2「MODIFY は1パス変換で terminal」参照）。
- **活かす**: `distance_calculator.py`、Context Accumulator の δ 産出。
- **拡張**: `_match_conditions`（δ 参照。本リファクタ内で需要駆動に段階実装、旧 #107 吸収）、ポリシー評価を priority 解決の (a,C) 評価エンジンに（MODIFY は1パス変換で terminal、同一 priority 複数 MODIFY は DEFER）。confidence 計算への LLM 活用（§5）。
- **影響**: `docs/design/policy-engine-proposal-override.md`（提案/上書きモデルの正典）は本設計により置き換え済みのためアーカイブ化した。
- **温存（本設計では触らない）**: `max_actions`（回数上限による運用バックストップ。ゴールに近づかないまま動作を継続する状態＝intent drift 的な暴走を、drift 検出機構が無い現状で回数によって粗く肩代わりして止める。AARM の (a, C) 意図評価とは無関係の運用ガードであり、本物の drift 検出〔δ の distance drift / scope_expansion、#99〕が入れば役割はそちらへ移る。現状 benchmark ではどのケースも閾値〔既定 50〕に届かず休眠）。

実装時の規律（#94 で確立）: 統合すべきもの（confidence の入口写像・DEFER トリガー・δ のポリシー参照）を切り離さない / 条件1〜15 の移行を benchmark で検証しながら実装する / 危険性を confidence に混ぜない。

---

## 検証状況（概略）

本メモの設計は試作段階の想定であり、実装で確認が取れているのは一部。概略:

- **実装済み・確認可能**: semantic distance の埋め込み計算（式4、`distance_calculator.py`）。決定層のポリシー評価エンジン化（LLM decision 判定の除去、priority 解決、MODIFY の1パス terminal 化、同一 priority 競合の DEFER）— #112 Phase A で実装済み。benchmark（`my_project/benchmark.py`）で回帰確認済み。
- **設計のみ・未実装**: δ を参照する match predicate（semantic_distance/data_classification/confidence の閾値・集合参照。条件1〜15 の移行対応）、DEFER トリガーの FRAMEWORK/CONFORMANCE 統合のうち δ 依存部分、confidence の evaluability 定義に基づく計算、多層防御 LLM の confidence 反映。いずれも Phase B 以降の対象。
- **未検証（実装後に benchmark で確認）**: デモシナリオ4/8 の再現性、条件1〜15 の移行が意図どおり decision を出すか、confidence が曖昧さ・矛盾を低く算出するか。Phase A 単独ではこれらは baseline ALLOW に素通りする既知の回帰であり（`benchmark_data.jsonl` の `known_regression_until: "Phase B"`）、Phase B とセットで回復を確認する。
- **他 Issue 依存**: confidence 較正（#77）、DEFER 解決機構（#89）、scope_expansion 再設計（#99）、composite risk（#100）。δ 参照ポリシーは本リファクタ内で段階実装（旧 #107 吸収）。

---

## 関連

- 論文解釈の土台: [docs/aarm/classification-and-policy-model.md](../aarm/classification-and-policy-model.md)（Table I・Policy Structure・測定と評価の二段）、[docs/aarm/deferral.md](../aarm/deferral.md)（DEFER トリガーの FRAMEWORK/CONFORMANCE 不整合・confidence 解釈）
- AARM 論文 arXiv:2602.09433: 式2（Context Accumulation）、式3（Policy Structure）、式4（semantic distance）、R3・R7、§IV-B-4（FRAMEWORK 章 DEFER）、§IV-C、Contribution 2
- 旧・提案/上書きモデル（本設計により置き換え済み、アーカイブ）: [docs/design/policy-engine-proposal-override.md](policy-engine-proposal-override.md)
- リスク把握（δ でのリスク把握・危険性軸の集合・confidence≠危険性）: [docs/design/risk-classification.md](risk-classification.md)
- 環境条件の扱い: [docs/design/environment-demo-fiction.md](environment-demo-fiction.md)（本リファクタが触る `_match_conditions` の環境条件〔`environment_type` / `not_in_maintenance_window`〕、および §3 条件14 の environment=production は、汎用の環境評価入力ではなくデモフィクションとして踏襲する。E は AARM の (a, C) 入力ではない〔[docs/aarm/environment-and-context.md](../aarm/environment-and-context.md)〕）
- 関連 Issue: #112（本設計の実装。#94 後継）、#94（signal/decision 分離。#112 に立て直し・not_planned クローズ）、#107（δ 参照拡張。#112 に吸収・not_planned クローズ）、#99（scope_expansion）、#100（composite risk）、#77（confidence 較正）、#89（DEFER 解決機構）