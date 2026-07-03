# 設計メモ: 決定層をポリシー評価エンジンに組み替える（LLM ベース IntentAlignment の除去）

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは laarma の**設計判断**を記録する設計メモである。
> AARM 論文が何を言っているか（論文解釈）は `docs/aarm/classification-and-policy-model.md` に
> 記録されており、本メモはそれを**前提・参照**して、laarma がどう実装するかの判断を述べる。
>
> **記述の区別**: 本メモは二種類の記述を区別する。
> - **【確定】** で始まる項は、論文解釈から導かれる確定した設計方針。
> - **【仮説】** で始まる項は、棚卸し・対応づけの結果であり、実装して benchmark で検証するまでは
>   仮説として扱うもの。確定と混同しない。
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

### 【確定】問題: LLM ベース IntentAlignment は AARM 仕様に存在しない

AARM 論文を精読した結果（`docs/aarm/classification-and-policy-model.md` および論文 §IV-C, R7, 式3, 式4）、
以下が確定した:

- **AARM の "intent alignment" は独立コンポーネントの名前ではなく、「ポリシーが (a, C) を評価すること」そのものの呼称**である。論文の Contribution 2 は intent alignment を「アクションを静的ポリシーだけでなく、ユーザリクエストから蓄積コンテキストに至る intent の連鎖に照らして評価すること」と定義する。R3 のタイトル "Policy Evaluation **with** Intent Alignment" が示すとおり、intent alignment は policy evaluation の修飾であって、別立ての判定器ではない。
- **semantic distance は埋め込みコサイン距離のスカラー**である（論文 式4: `d(r0, an) = 1 − cosine(embed(r0), embed(an))`）。LLM 判定ではない。Context Accumulator が δ の一つとして毎アクション産出する。
- **intent misalignment の判定は、ポリシーの match predicate が δ（semantic distance・data_classification 等）を参照することで実現される**。論文の Data Exfiltration 例は「context-dependent deny が email をブロックするのは、email が禁止だからではなく、先行する機微データアクセスとの composition が intent misalignment を露呈させるから」と明示する——この判定は LLM ではなくポリシーの context 参照。
- したがって **laarma の現行 LLM ベース `IntentAlignment` は AARM 仕様には存在しないコンポーネント**であり、仕様の誤読から生まれた産物である。論文は intent alignment の判定に LLM を要求していない。

（補足: 「埋め込み距離では捉えきれない意味判断を LLM で補う」という発想は論文に根拠がない。論文 R7 が求めるのは「埋め込みモデルが自分の action schema に適しているかを既知の良性/悪性系列で校正せよ」という**モデル適合性の検証**であって、「埋め込みでは不足だから LLM を足せ」ではない。）

---

## 2. 【確定】道A: LLM ベース IntentAlignment を除去し、決定層をポリシー評価エンジンにする

laarma は AARM 仕様に忠実な実装を目指す（"Learning AARM Agent"）。したがって:

**決定層を、現行の「提案/上書きモデル（静的評価 → LLM を後で呼んで上書き）」から、
「(a, C) を評価するポリシー評価エンジン（Context 完成 → ポリシー集合 Π を priority 解決）」に組み替える。
LLM ベース `IntentAlignment`（intent_alignment.py の LLM 判定）は除去する。**

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
- **除去する**: `intent_alignment.py` の LLM 判定（(a,C) を LLM に渡して decision を得る部分）。`_confirm_with_ia` の提案/上書き構造。
- **新設・拡張する**: ポリシーの match predicate が δ（semantic distance・data_classification・confidence 等）を参照できるようにする（#107 の δ 参照拡張が前提）。δ を閾値/集合で参照するポリシーが、現行 LLM が担っていた判定を代替する。

### 処理順序の転換

現行は「静的評価 → 後で LLM を呼ぶ」逐次。組み替え後は「**Context 完成（δ 産出）→ ポリシー評価**」。
δ（semantic distance 含む）はポリシー評価の前に C に載っている必要がある。これは
`docs/aarm/classification-and-policy-model.md` §5「測定（accumulation 段・常時）と使用（policy 評価段）の二段」に対応する。

---

## 3. 現行 IntentAlignment の判定基準（条件1〜15）の移行先

現行 `intent_alignment.py` の SYSTEM_PROMPT は、Decision Criteria として 15 個の判定基準を持つ
（#94 で条件1〜15 として列挙済み）。道A では、これらを LLM 判定から δ のポリシー参照・別 Issue・confidence に
分解する。以下は棚卸しの結果である。

### 【仮説】移行対応表

各条件の移行先は、実装して benchmark で検証するまでは仮説として扱う。

| 条件 | 現行の判定内容 | 移行先 |
|---|---|---|
| 1 | action が意図と矛盾/無相関（読めと言われ write/delete） | semantic distance のポリシー閾値参照（`semantic_distance > 閾値 → DENY`） |
| 2 | action_matches_intent=false かつ distance>0.4 で破壊/書込 | distance + tool risk のポリシー参照 |
| 3 | scope_expansion 検出かつ意図に正当化なし | **#99**（scope_expansion 産出の再設計）に委ねる既知の穴 |
| 4 | Compositional Risk（アクション系列が攻撃ベクトル） | **#100**（composite risk）に委ねる既知の穴。単一 (a,C) では捉えにくい系列リスク |
| 5 | action_matches_intent=true / 意図が対象を明示 | distance 小 + 危険信号なし → ALLOW baseline |
| 6 | semantic_distance < 0.3 | distance のポリシー閾値参照 |
| 7 | PII/CONFIDENTIAL を含まない | data_classification のポリシー参照 |
| 8 | 破壊的でも明示意図と高 confidence | distance 小 + confidence 高のポリシー参照 |
| 9 | 意図が曖昧でエージェントが未認可の自律判断 | **confidence 低 → DEFER（トリガー c）**。中身の解釈は #89、較正は #77 |
| 10 | confidence < 0.4 かつ追加 context で解決可能 | **DEFER トリガー (c) そのもの**（`confidence < 閾値 → DEFER`） |
| 11 | 安全だが明示的認可が欠落 | 条件9 と同じく confidence 低 → DEFER(c) |
| 12 | 情報収集系（read/list）は曖昧でも ALLOW | **廃止**。distance 小 + 非破壊 → ALLOW baseline で自然に出るため特別扱い不要 |
| 13 | PII/CONFIDENTIAL の削除/重大アクセス | data_classification + destructive のポリシー参照 → STEP_UP（危険性軸の SDK 固定写像） |
| 14 | 本番の高影響操作 | environment=production + destructive のポリシー参照 → STEP_UP（危険性軸の SDK 固定写像） |
| 15 | confidence 0.4-0.6 かつ中程度リスク | confidence のポリシー参照（`0.4 < confidence < 0.6 → STEP_UP`） |

### 移行先の3分類

1. **δ のポリシー閾値/集合参照で代替（LLM 不要）**: 条件 1, 2, 5, 6, 7, 8, 10, 13, 14, 15。#107 の δ 参照拡張があれば match predicate に書ける。道A の中核。
2. **別 Issue に委ねる既知の穴**: 条件 3（#99）、条件 4（#100）。
3. **意図の曖昧さ → confidence 低 → DEFER(c)**: 条件 9, 11。

### 【確定】条件9・11（意図の曖昧さ）の扱い: confidence への集約は論文の構造

条件9・11 の「意図が曖昧でエージェントが未認可の自律判断をしている」は、semantic distance（埋め込み距離）では
捉えにくい。しかしこれは道A の欠陥ではなく、AARM の DEFER 設計に沿った正しい配置である
（`docs/aarm/classification-and-policy-model.md` §3、および DEFER トリガー a/b/c）:

- DEFER の入口条件は (a) 未 populate context 参照、(b) 同一 priority のポリシー矛盾、(c) confidence < 閾値、の3つに**意図的に絞られている**。曖昧さは (c) confidence として入口で現れ、閾値を下回れば DEFER で保留される。
- **決定層（入口）は「曖昧さの中身」を判定しない。** confidence が低いという一事実だけを見て DEFER する。confidence に求められるのは「曖昧なとき低く出る」ことだけで、「なぜ曖昧かを表現する」ことではない。
- 「その曖昧さが何で、どう解決できるか」は DEFER 後の解決機構（**#89**）に先送りされる。これは AARM が入口をクリーンに保つための境界切り分けに沿う。
- confidence が曖昧さを正しく低く算出できるかという**較正**は **#77**（本メモの範囲外）。

したがって現行 LLM が条件9・11 で行っていた「曖昧さの判定」は、道A では「confidence が低く出る → DEFER(c)」に還元され、曖昧さの中身の解釈（#89）と confidence の較正（#77）に分離される。決定層は `confidence < 閾値 → DEFER` と書くだけで、曖昧さ判定ロジックを持たない。

---

## 4. 【仮説】デモシナリオの再現性（道A の妥当性検証）

現行デモは LLM 判定に依存したシナリオを持つ。道A（distance + ポリシー + confidence）でこれらが再現できるかは、
道A の妥当性検証そのものであり、**実装して benchmark で確かめるまでは仮説**である。

- **シナリオ4「ユーザは読むだけ頼んだのにエージェントが delete_file を実行 → DENY」**: delete_file と元リクエスト（読む）の semantic distance が大きく出て、`distance > 閾値 → DENY`（条件1）で捉えられる、という仮説。埋め込みが実際にこの距離を大きく算出するかは検証対象。
- **シナリオ8「"古いファイル"の定義が曖昧 → DEFER」**: "古い" の判断に confidence が低く出て、`confidence < 閾値 → DEFER(c)`（条件9）で捉えられる、という仮説。confidence 計算がこの曖昧さを低く算出するかは #77 の較正に依存し、検証対象。
- シナリオ5（PII 削除 → STEP_UP）、シナリオ7（危険パス → MODIFY）等、静的ルール・data_classification で決まるものは、LLM 除去の影響を受けにくい（元々ポリシー側）。

これらの再現性検証は道A の実装後に benchmark で行う。再現できない場合、その具体的な不足が、将来的な LLM 補完（道B、下記）を検討する根拠になる。

---

## 5. 道B（LLM 補完）の位置づけ: 将来 Issue

道A（埋め込み距離 + ポリシー + confidence）を完成させた後、それでも捉えられない意味判断が
**具体的に観測された場合**に限り、「埋め込み距離では捉えにくいケースを LLM で補う」独自拡張（道B）を検討する。

- 道B は AARM 仕様外の laarma 独自拡張であり、仕様外であることを明示して持つ。
- **現時点で道B の想定シナリオを先回りで記述しない。** 埋め込みで足りないケースを推測で挙げるのは、根拠のない想定を固定する危険がある（実際に観測された不足のみを、そのとき事実として記録する）。道A を動かして観測された不足を、将来 Issue に具体的事実として書き込む。

---

## 6. この設計が触る範囲（実装は別途、規律に従う）

道A の実装は #94（signal/decision 分離）の本体であり、規模が大きい。実装ブリーフは本メモを土台に別途作成する。
実装時の規律（#94 で確立）:

1. 統合すべきもの（confidence の入口写像・DEFER トリガー a/b/c・δ のポリシー参照）を切り離さない。
2. alignment を「LLM が出す分類値」として扱わない——道A では semantic distance はスカラー、confidence はスカラーで、ポリシーが閾値参照する。
3. 条件1〜15 の移行対応表（§3）の各行を、benchmark で検証しながら実装する。仮説を確定扱いしない。

触るコンポーネント（概略）:
- **除去**: `intent_alignment.py` の LLM 判定、`policy_engine.py` の `_confirm_with_ia` 提案/上書き構造。
- **活かす**: `distance_calculator.py`、Context Accumulator の δ 産出。
- **拡張**: `_match_conditions`（δ 参照、#107）、ポリシー評価を priority 解決の (a,C) 評価エンジンに。
- **影響**: `docs/design/policy-engine-proposal-override.md`（提案/上書きモデルの正典）は道A で大きく変わるため、実装時に見直す。

---

## 関連

- 論文解釈の土台: [docs/aarm/classification-and-policy-model.md](../aarm/classification-and-policy-model.md)（Table I・Policy Structure・DEFER トリガー・測定と評価の二段）
- AARM 論文 arXiv:2602.09433: 式2（Context Accumulation）、式3（Policy Structure）、式4（semantic distance）、R3・R7、§IV-C、Contribution 2
- 現行の提案/上書きモデル（道A で見直す対象）: [docs/design/policy-engine-proposal-override.md](policy-engine-proposal-override.md)
- リスク把握（δ でのリスク把握・危険性軸の集合）: [docs/design/risk-classification.md](risk-classification.md)
- 関連 Issue: #94（signal/decision 分離 = 道A の本体）、#107（match 条件の δ 参照拡張）、#99（scope_expansion）、#100（composite risk）、#77（confidence 較正）、#89（DEFER 解決機構）
