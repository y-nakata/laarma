# 調査メモ: 意図整合性判定と confidence の二軸設計の裏付け（先行研究・業界実践）

[← README に戻る](../../../README.md)

> **この文書の位置づけ**: これは laarma の**設計構想を外部の先行研究・業界実践で裏取りした調査記録**である。
> `docs/aarm/research/`（AARM 論文の読みを深める調査）と対をなし、そちらが「論文が何を言っているか」の
> 掘り下げであるのに対し、本文書は「laarma の設計構想が外部の研究・実務に照らして妥当か」の裏付けを扱う。
>
> **裏付けに徹し、判断は置かない**: 本文書は「先行研究・業界実践が何を言っているか、実務に載るか」までを
> 記録する。「だから laarma はこう設計する」という設計判断の確定は、`docs/design/` 本体および関連 Issue
> （#128 意図整合性ルール本体設計 / #77 confidence 較正 / #129 priority 体系化 / #135 DEFER 解決機構）に置く。
>
> **調査の背景**: #128（semantic_distance 単独では意図逸脱と正当な情報収集ステップを分離できない）を受け、
> 意図整合性判定に confidence（評価可能性）を組み合わせる構想が出た。その構想——距離と confidence をどう
> 組み合わせるか——を確定する前に、外部の先行研究で裏取りした。調査は web 検索ベースで、網羅的な文献
> サーベイではない。

---

## 1. 危険性と評価可能性を別軸で扱う分離原則

**要点**: 「危険性（そのアクションが本質的に危険か）」と「評価可能性（判定しきれているか、追加情報で
定まるか）」を別々の軸として扱う設計は、複数分野で確立している。laarma の「危険性を confidence に
混ぜない」（#112）・「confidence = evaluability」（#77）は、この分離原則に対応する。

不確実性を二種に分ける議論が繰り返し現れる: **aleatoric**（データ固有のノイズ・環境の確率性に由来、
情報を集めても減らない）と **epistemic**（モデルの知識不足に由来、情報を集めれば減らせる）。これらは
「意思決定のために分離すべき」とされる。model-based RL の研究は「不確実性の分離は、データ駆動の
安全性クリティカルな制御でうまくやるために不可欠」「epistemic を aleatoric から切り離すことで、意味的に
異なる目的を別々に最適化できる」と述べる。オフライン RL でも、epistemic への risk-aversion が分布シフトを
防ぎ、aleatoric への risk-aversion が環境の確率性ゆえの危険を抑える、と両者を別技術で別々に扱う。

laarma への対応: 危険性軸（data_classification × destructive、複合リスク）は「本質的な危険」で aleatoric 寄り
（情報を集めても消えない）。confidence = evaluability は「評価しきれているか」で epistemic 寄り（情報を
集めれば減らせる）。両者を別軸に保つのは、これらの分野が「別々に扱うべき」と結論しているのと同じ構造。
業界実践でも、脆弱性スキャナ Burp Scanner が severity（影響の大きさ = 危険性）と confidence（検出の確証度）を
独立した二軸で出す（#77 で既出）。

参照:
- Depeweg et al. 2018, Decomposition of Uncertainty in Bayesian Deep Learning: https://arxiv.org/pdf/1710.07283
- 1R2R (NeurIPS 2023), risk-averse offline RL: https://arxiv.org/pdf/2212.00124
- PETSUS, Mind the Uncertainty (model-based RL, separation of uncertainties): https://arxiv.org/pdf/2309.05582

---

## 2. 二段階 abstention と、証拠ベースの救済

**要点**: 二つの閾値・二段階で abstention（棄却/保留）を組む枠組みは既存の確立した設計。そして「棄却
しそうな判定を救う」際、確立した手法は confidence の自己申告水増しでなく、**追加の証拠・情報を実際に
取得して不確実性を減らす**形をとる。

二軸で組む例: dual-threshold conformal prediction は、一方の閾値で予測集合の妥当性を保証し、もう一方の
閾値で abstention を判定する。株式ランカーの研究は、最も不確実な予測を reject しつつ、accept した集合内では
confidence で重み付けした行動をとる hybrid rule を、戦略レベルとポジションレベルの二粒度で同時に実装する。

救済の作法（重要）: selective prediction は過剰に abstain しがちなので、それを減らす手法がある。ReCoVERR は
low-confidence な予測に対し、abstain する代わりに追加の手がかりを探し、LLM が関連質問を投げて
high-confidence な証拠を集め、十分な証拠が予測を裏づければ abstain せず出力する。ALMA は、conformal
prediction で棄却したあと、不確実性の主因が epistemic（データ不足）か aleatoric（特徴不足）かを診断し、
epistemic なら訓練データを、aleatoric なら追加モダリティ（特徴）を取得する。いずれも「救済＝confidence を
持ち上げる」でなく「救済＝足りない情報を実際に取得して不確実性を減らす」。

laarma への対応: DEFER（保留）→ 解決機構が追加情報を集める（#89/#135）という laarma の構造は、この
「棄却後に不足を診断して情報取得」と同型。救済を情報取得に紐づける点が、次節の警告を避ける鍵になる。

参照:
- Dual-threshold conformal prediction: https://arxiv.org/pdf/2502.07255
- ReCoVERR (reduce over-abstention via evidence gathering): https://arxiv.org/html/2402.15610v2
- ALMA (reject then acquire by uncertainty type): https://link.springer.com/article/10.1007/s10994-026-07042-w
- Two-level uncertainty (hybrid reject + confidence-weighted): https://arxiv.org/pdf/2603.13252

---

## 3. 要注意: 確率的判定で確率的判定を救う「入れ子」の危険

**要点**: 「LLM の判定で confidence を上げ、その confidence で別の判定（例: 距離による DENY）を覆す」という
設計は、分野が明確に警告する「確率的ブラックボックスで確率的ブラックボックスを監督する」入れ子に当たる。

エージェントガードレールの研究は、LLM-as-Judge や経験的セマンティックガードレールについて、「確率的
ブラックボックスで確率的ブラックボックスを監督することは、原理的に安全性の決定論的下限を与えられず、
trusted computing base の深刻な危機を招く」「context forgetting と誤った権限付与を起こしやすい」「長文脈の
相互作用で alignment drift が起きる」と指摘する。ガードレール全般の共通原則も「LLM を安全性の唯一の
判定者にしない。外部のランタイム制御が、害が伝播する前に override / escalate する」。

laarma への対応: #135 で観測した「DeferralResolver の LLM が、保留中で未実行のアクションを『実行済み』と
誤読して根拠不成立の DENY を出した」事象は、この一般的な失敗（context 誤読）の一例。したがって、意図
整合性の救済を「LLM が整合と言えば confidence を加点する」形に載せると、この入れ子の危険に触れる。
救済は前節のとおり「情報の実取得」に紐づけるべきで、LLM 自己申告の confidence 水増しに載せない。加えて、
二軸判定が機能する前提として confidence が較正されている必要がある（未較正のヒューリスティックでは、
閾値を上げれば誤りが確実に減る、という単調性が保証されない）——これは #77（confidence 較正）依存。

参照:
- Provably Secure Agent Guardrail（LLM-as-Judge の限界、決定論的下限の欠如）: https://arxiv.org/html/2605.29251
- LLM Guardrails 実務ガイド（LLM は判定者の唯一でない、決定論チェックが土台）: https://alice.io/blog/llm-guardrails
- 確信度が selective prediction を支える必要条件（単調な risk-coverage）: https://arxiv.org/html/2601.00138v1

---

## 4. laarma に近い実用システムと、reactive / proactive の区別

**要点**: laarma の中核（決定論ポリシーが判定、LLM は補助信号、外部ランタイムが override）は分野の実用
システムと同じ路線。ただし、意図整合性を「今このアクションの語義距離」で見る reactive な方式には原理的
限界があり、それを埋める proactive 系は実務には重い。

- **AgentSpec**: ランタイム安全ルールを定義する DSL（トリガー・条件・強制機構を実行中に評価）。laarma の
  `policy.yaml`（match predicate・条件・decision・priority）と構造的に同型。laarma が突飛でない傍証。
- **reactive vs proactive**: AgentSpec 系は reactive（違反が差し迫ってから反応）。Pro2Guard / ShieldAgent は
  proactive で、エージェント挙動を離散時間マルコフ連鎖等でモデル化し、不安全状態への到達確率を推定して
  事前に介入する。#128 の「semantic_distance では手続き的妥当性（このステップがゴール到達の妥当な一手か）を
  測れない」「long-horizon 依存に reactive ルールは弱い」は、この proactive 系が扱う領域。ただし到達可能性
  解析は一般企業システムには重い（次節）。
- **Cordon**（semantic transactions）: 取り消し不能な効果を commit 前にステージング（可逆変更は shadow state、
  外向き効果は effect outbox）して、合成された実行フローを検証してから commit。#135 の「DEFER 中で未実行の
  状態をどう表現するか（実行済みと誤認させない）」に、状態を明示分離する設計として参考になる（Cordon 全体の
  移植でなく、状態分離の発想のみ）。
- **provenance-aware guardrail**: 最終出力や現在のツール呼び出しだけを見るガードレールは、過去の機微データ
  アクセスが特権アクションに影響する類のリスクを見逃す。アクションの source chain（どの証拠・メモリ・ツール
  出力・外部観測が影響したか）を辿って推論すべき。AARM の Context Accumulator・#100（composite risk）の思想と一致。

参照:
- AgentSpec / Pro2Guard（reactive DSL と proactive 拡張）: https://arxiv.org/pdf/2604.22136
- Proactive runtime enforcement via probabilistic model checking（ShieldAgent 言及）: https://arxiv.org/html/2508.00500v1
- Cordon (semantic transactions, staging before commit): https://arxiv.org/pdf/2606.17573
- Evidence tracing / execution provenance サーベイ: https://arxiv.org/pdf/2606.04990

---

## 5. 深掘りしない（研究色が強く、一般企業システムに載らない）

**要点**: 以下は筋はよいが、一般企業が運用するシステムには重すぎる。laarma は採らない。将来「精緻な理論を
入れたい」という誘惑が生じたときの歯止めとして、採らないことを明記しておく。

- **ShieldAgent のマルコフ論理ネットワーク** による確率推論。
- **Pro2Guard / DTMC の確率的到達可能性解析**（不安全状態への到達確率を事前推定）。
- **conformal prediction の統計的保証系**（distribution-free coverage 保証つき abstention）。

これらは「reactive な距離ルールの限界（#128）」や「較正された確信度（#77）」に理論的な回答を与えるが、
モデル化・較正・運用のコストが高く、laarma が目指す「共通 AI エージェントツール呼び出しドメインの
実用 SDK」の路線に合わない。laarma は、決定論ポリシー + 補助的な confidence（LLM 検出を含む多層防御）+
DEFER 後の情報取得、という実務に載る範囲に留める。

---

## まとめ（設計構想への含意 — 確定は関連 Issue に委ねる）

先行研究・業界実践に照らすと、#128 に対する laarma の着地について次が言える。判断の確定は #128 で行う。

- **支持される形（分離二段）**: 危険性軸（距離 = reactive な危険信号）と評価可能性軸（confidence）を
  **分離したまま、別々の段で作用させる**。距離は危険性軸で判定し、confidence が低ければ DEFER に落とし、
  DEFER 後に追加情報（ゴール整合の証拠）を実取得して評価可能性を回復させ ALLOW/DENY を確定する。これは
  分離原則（§1）と証拠ベース救済（§2）が支持する。
- **避けるべき形（複合一式）**: 距離と confidence を一つの match 条件に混ぜ、LLM 自己申告の confidence 加点で
  距離由来の DENY を相殺する。これは危険性を評価可能性で打ち消し、かつ確率的判定で確率的判定を救う入れ子
  （§3）に当たる。分野が警告する形。
- **前提**: いずれにせよ二軸判定が機能するには confidence が較正されている必要がある（#77 依存）。

同じ「二軸」でも、分離二段は支持され、複合一式は警告される——この区別が本調査の中心的な発見である。
具体的にどの priority 帯・どの match 条件で分離二段を実装するかは #128 / #129 で確定する。
