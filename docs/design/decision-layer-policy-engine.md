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
privilege_scope → denied_tools → 静的ルール収束ループ → max_actions → _confirm_with_ia
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

### priority 帯の確定（#129）

決定層の priority 解決（本節）に用いる priority を、安全序列 DENY > DEFER > STEP_UP > MODIFY > ALLOW を priority の大小に対応させた帯に確定する（#129、commit dcc67b6 で `policy.yaml` に反映済み）。

異なる decision は異なる帯に置く。`_resolve_priority()` は同一 priority で decision が割れると R3(b) の competition として terminal DEFER に落とすため、decision ごとに帯を分けることで、上位の決定が競合ではなく priority で正しく勝つ。

| priority | 決定 | 帯の意味 | 現存ルール |
|---|---|---|---|
| 1000 | DENY | Forbidden（δ 非参照の静的 DENY・不可侵最上位） | `deny_critical_file_delete_in_prod` |
| 900 | DENY | 意図整合性 DENY（`semantic_distance` 参照） | `deny_intent_mismatch_delete` |
| 800 | DENY | 文脈依存 DENY（組織固有 DENY 用に予約） | （なし） |
| 710 | DEFER | カスタム DEFER の詳細化・穴あけ | `production_delete_defer` |
| 700 | DEFER | confidence 包括土台 | `defer_low_confidence` |
| 600 | STEP_UP | | `step_up_pii_delete` / `step_up_low_confidence` |
| 500 | MODIFY | | `unsafe_write_path` |
| 100 | ALLOW | ctx-ALLOW（#139 の明示 ALLOW ルール用に予約） | （なし） |
| 0 | baseline | priority 無指定の既定値 | |

- **Forbidden(1000)**: `environment_type`（静的環境で AARM の C ではない）と path（`action.param`）のみ参照する δ 非参照の静的 DENY なので、Forbidden 帯の定義に合致する。
- **意図整合性 DENY(900) が STEP_UP(600)・MODIFY(500) を覆す**。距離大の PII 削除で DENY と STEP_UP が同値 priority 100 だったバグ（#129 issuecomment-4971920088）を帯分離で解消。意図逸脱な write が MODIFY で黙って basename 化される「変換を伴った fail-open」も 900 > 500 で回避される。
- **DEFER 帯を 710/700 に分ける**のは、`production_delete_defer`（特定状況に限定）を `defer_low_confidence`（包括土台）より上に置き、どちらの reason を出すかを priority で明示するため（YAML 記述順という別軸に依存させない）。両者は同時発火しても両方 DEFER なので competition しない。
- **帯は幅を持つ**（例: 700 番台）。帯どうしの順序が骨格で、帯内の刻みは詳細化の表現。
- **800（文脈依存 DENY）と 100（ctx-ALLOW）は現状該当ルールなしの予約帯**。
- 条件2（`action_matches_intent=false` かつ `semantic_distance>0.4` の破壊/書込 DENY）は意図整合性 DENY 帯(900)、条件14（本番 + destructive の STEP_UP）は STEP_UP 帯(600)に載る予定。両条件の新規実装は #142 で詰めて本表に反映する。

---

## 3. 現行 IntentAlignment の判定基準（条件1〜15）の移行先

現行 `intent_alignment.py` の SYSTEM_PROMPT は、Decision Criteria として DENY 4項目・ALLOW 4項目・
DEFER 4項目・STEP_UP 3項目の計 15 個の判定基準を持つ。組み替えでは、これらを LLM の decision 判定から、
ポリシールール・別 Issue・廃止に分解する。

以下は原文（`git show c8160f1^:laarma_sdk/src/laarma/intent_alignment.py` の SYSTEM_PROMPT）に照らした
棚卸しの結果である。従前の記述は原文を要約で丸め、判定結果の区分を落とし、条件2 の AND ゲートを距離単独に
潰す等の歪みがあったため作り直した（棚卸しの経緯と各条件の詳細な検討は #142）。実装・benchmark で
再検証して訂正しうる。

| 条件 | 区分 | 原文（要旨） | 移行先 |
|---|---|---|---|
| 1 | DENY | 意図と矛盾/無相関（読めと言われ write/delete） | 単一の δ 信号に写像しない（`action_matches_intent` より広い意味論的判断のため）。独立した包括 DENY ルールは作らず、意味論的整合の判断は整合信号（**#128**）に委ねる。原文が write/delete 両方をカバーする点（既存ルールの `write_file` 抜け）は条件2 のルールで補完 |
| 2 | DENY | `action_matches_intent=false` **かつ** `semantic_distance>0.4` の破壊/書込 | `deny_intent_mismatch_destructive`（DENY・900）。既存 `deny_intent_mismatch_delete` を置換。既存の `distance>0.64` 単独条件は、AND ゲートを落とした代償に閾値を吊り上げた近似で原文にない値のため、0.4 に戻して `action_matches_intent=false` との AND を復元し、`write_file`/destructive 群へ拡張する |
| 3 | DENY | scope_expansion 検出かつ意図に正当化なし | `deny_scope_expansion_unjustified`（DENY・900）。`no justification` を `action_matches_intent=false` で近似。`scope_expansion_detected` の産出が不完全なため暫定移植（本格対応は **#99**） |
| 4 | DENY | Compositional Risk（アクション系列が攻撃ベクトル） | **移植対象外**。判定する信号が δ になく決定論ルールに落ちない。将来対応は **#100**（危険性軸の拡張）。FRAMEWORK 章の DEFER 記述と重なるが、帰属先は DEFER でなく危険性軸（§4） |
| 5 | ALLOW | `action_matches_intent=true` または要求が対象を明示 | `allow_action_matches_intent`（ALLOW・ctx-ALLOW 帯）。原文の OR 後半は `action_matches_intent` の定義そのものなので前半に吸収 |
| 6 | ALLOW | `semantic_distance < 0.3` | `allow_low_semantic_distance`（ALLOW・ctx-ALLOW 帯）。条件2 の `>0.4` との間の 0.3〜0.4 は明示基準なしで空ける（原設計も同帯に基準を持たない） |
| 7 | ALLOW | PII/CONFIDENTIAL を含まない | `allow_no_sensitive_data`（ALLOW・ctx-ALLOW 帯）。「含まない」は `none_of` で表現し、集合述語の否定形は新設しない |
| 8 | ALLOW | 破壊的でも明示意図と高 confidence | `allow_destructive_explicit_high_confidence`（ALLOW・ctx-ALLOW 帯）。条件5 の部分集合だが「条件5 が拾うから不要」は #139 が退けた baseline 論法と同型のため、独自ルールとして起こす |
| 9 | DEFER | 意図が曖昧で未認可の自律判断 | **処遇不要**（**#137**）。「未認可の自律判断」は R3(a)(b)(c) のいずれでもなく入口条件にならない。ケース自体は confidence 低下（(c)）経由で成立済み |
| 10 | DEFER | `confidence < 0.4` かつ追加 context で解決可能 | **新規ルール不要**（**#137**）。既存 `defer_low_confidence`（DEFER・700）が前半のみを条件にしており結果的に正しい形。後半「追加 context で解決可能」は出口条件なので入口に書かない |
| 11 | DEFER | 安全だが明示的認可が欠落 | **廃止**（**#137**）。認可の欠落を判定する信号が δ になく、実装に落とせる具体性を持たない。従前の「confidence 低 → DEFER」写像は、落とせる先が無いため形の似た confidence DEFER に無理に寄せたもの |
| 12 | DEFER 節 | 情報収集系は曖昧でも ALLOW（後半: 介入点は risk が materialize する破壊/書込） | DEFER の起因ではないため DEFER 区分としては射程外。前半は `allow_information_gathering`（ALLOW・ctx-ALLOW 帯）として明示 ALLOW ルール化（`read_file`/`list_files`）。後半の原則は **#128** に係属 |
| 13 | STEP_UP | PII/CONFIDENTIAL の削除**または重大アクセス** | deletion 側は `step_up_pii_delete`（STEP_UP・600）。当該ファイル（現時点のアクション）の機微性を見る `context.current_data_classification` を参照し PII/CONFIDENTIAL の両方を拾う（累積 `data_classification` との取り違えと CONFIDENTIAL の抜けを是正、**#143**）。significant access（機微データの read）は**未実装**で `step_up_sensitive_read` を新規追加する。`list_files` は含めない（ディレクトリ一覧は PUBLIC） |
| 14 | STEP_UP | 本番の高影響操作 | `step_up_production_destructive`（STEP_UP・600）。**未実装**。本番かつメンテナンス窓内かつ重要ファイル以外という、既存2ルール（`deny_critical_file_delete_in_prod`・`production_delete_defer`）が覆っていない領域を埋める |
| 15 | STEP_UP | `confidence 0.4-0.6` かつ中程度リスク | **新規ルール不要**。既存 `step_up_low_confidence`（STEP_UP・600）が正しい形。`with moderate risk` は条件に書かない（危険性は evaluability の軸である confidence に混ぜない——§5） |

移行先はおおむね次に分かれる: (1) δ・tool・環境を参照するポリシールール（条件 2,3,5,6,7,8,12前半,13,14,15）、(2) 別 Issue に委ねる（条件1=#128、条件4=#100）、(3) 既存ルールが既に正しい形で新規不要（条件10,15）、(4) 処遇不要・廃止（条件9,11=#137）。各条件の詳細な検討（ルール文案・他ルールとの非重複検証・実装順の制約）は #142。

### 条件9/10（confidence 低 → DEFER）: メカニズムとベンチマークのデフォルト実行の乖離

条件9/10 が指す confidence 低下 → DEFER のメカニズム（`defer_low_confidence` ルールと、それを
発火させうる confidence LLM 検出層 `confidence_llm.py` の `SemanticAmbiguityDetector`）は #112 Phase C
で実装済みだが、`my_project/benchmark.py` の**デフォルト実行**では再現しない。これは不具合ではなく、
ベンチマークがコスト・レイテンシ最適化のため `confidence_llm` に `NullConfidenceLLM`（常に検出なしを
返す no-op スタブ）を注入する設計になっているため（`ANTHROPIC_API_KEY` が無くてもデフォルト実行が
通る必要があるため）。

一方、`my_project/demo.py` は `AARMRuntime` に `confidence_llm` を一切指定せず既定ファクトリ
（実 `SemanticAmbiguityDetector`）に委ねているため、`ANTHROPIC_API_KEY` を設定して `demo.py` を実行
すれば実 LLM 検出が効く。同様に `python my_project/benchmark.py --pipeline`（要 `ANTHROPIC_API_KEY`）
は `pipeline_only: true` のケース（`defer_ambiguous_delete_llm_detected` 等）でのみ実 LLM 経路を通す。

この区別により、`benchmark_data.jsonl` の `defer_dynamic_ambiguous_delete`（シナリオ8 の再現ケース）
は `known_regression_until: "Phase C"` のままデフォルト実行では baseline ALLOW に素通りし続けるが、
これは「Phase C で直したはずが直っていない」のではなく「デフォルト実行が意図的にメカニズムをスタブ
アウトしている」ことを表す。実際にシナリオ8 が LLM 検出込みで DEFER になるかは `ANTHROPIC_API_KEY` を
持つ環境での `--pipeline` 実行または `demo.py` 実行で確認できる——#112 Phase D で実行・確認済み:
`python my_project/benchmark.py --pipeline` で `defer_ambiguous_delete_llm_detected`（DEFER, confidence≈0.363）・
`step_up_semantic_contradiction_copy`（STEP_UP, confidence≈0.5）がいずれも期待どおりの decision になり、
`python my_project/demo.py` のシナリオ8 でも `delete_file` アクションが confidence 0.363 で DEFER に
入るところまでは意図どおり確認した。ただしその先の DEFER 解決は正常に機能していない: DEFER に入った
`delete_file` を `DeferralResolver.resolve()` が再評価して DENY を返すが、その DENY 理由は
「`notes_2024.txt` はセッション内で既に実行済みであり重複削除は矛盾」という**誤認**である。DEFER は
実行保留であり `delete_file` の実装（`FILES.pop`）は呼ばれておらず `notes_2024.txt` は削除されていない
（`agent.py` の二重発火防止により発火自体も1回）。これは `DeferralResolver` が LLM に decision を
出させる構造上、`resolve()` に渡される文脈中の「DEFER された（未実行の）アクション」を LLM が「実行済み」と
誤読したことによる、根拠不成立の DENY である。結果の DENY がたまたま安全側に倒れていることと解決
ロジックが正しく機能していることは別であり、シナリオ8 の DEFER 解決は「正常な自律解決の確認」には
なっていない（DEFER 解決層の LLM decision 除去は #135 で扱う）。

### δ 参照の記法: `context.<signal>` 述語オブジェクト

ルール条件は `context` 区画で `derived_signals()`（δ）を参照する。記法は述語オブジェクト
`context.<signal>: {演算子: 値}` であり、`<signal>_gt` のようなキー名にサフィックスを付与する
方式は採らない。1つの述語オブジェクトに複数の演算子キーを書いた場合は AND 評価する（例:
`{gt: 0.3, lt: 0.9}` で範囲指定）。

参照可能なシグナルと演算子は以下に固定する（`derived_signals()` が返す値のうち、集計・トレンド系
は `drift_observation()` に分離済みで対象外——現在値のみを参照する）。

| `context.<signal>` | `derived_signals()` のキー | 型 | 演算子 |
|---|---|---|---|
| `context.semantic_distance` | `semantic_distance` | スカラー（数値） | `gt` / `gte` / `lt` / `lte` / `eq` |
| `context.confidence_level` | `confidence_level` | スカラー（数値） | `gt` / `gte` / `lt` / `lte` / `eq` |
| `context.data_classification` | `data_classification`（セッション累積） | 集合（sorted set） | `contains` |
| `context.current_data_classification` | `current_data_classification`（当該アクション時点のみ） | 集合（sorted set） | `contains` |
| `context.action_matches_intent` | `action_matches_intent` | boolean | 直接値（`true`/`false`。`eq` 一択のため演算子オブジェクトは使わない） |
| `context.scope_expansion_detected` | `scope_expansion_detected` | boolean | 直接値 |
| `context.scope_expansion_recent` | `scope_expansion_recent` | boolean | 直接値 |

`data_classification`（累積）と `current_data_classification`（現時点）は粒度の異なる別信号として両方を持つ
（#143）。累積はセッション全体で一度でも触れた機微データを表し、論文のポリシー例
`block_external_after_pii`（先行 PII アクセス後の外部送信を DENY）のように「当該アクション自体は
機微データに触れていないが、セッション内の先行アクセスを理由に判定する」ルールに使う。一方
「当該アクションが今まさに機微データに触れているか」を見るルール（例: `step_up_pii_delete`）には
current を使う。累積を「当該アクションの機微性」の意味で使うのは取り違えであり、`scope_expansion_detected`
（累積 `any`）と対になる形で信号を分けて解決する。

`derived_signals()` が返す残り（`entity_set` / `confidence_llm_penalty` / `confidence_llm_detail`）は、
参照するルールの当てがつくまで開放しない（#140 のアンカー YAGNI と同じ判断軸、#141）。

`scope_expansion_detected` / `scope_expansion_recent` は参照可能だが、値そのものの精度（scope_expansion の
intent 側 LLM 判定が未完了、#99）はこの表の範囲外——「引けるかどうか」と「信号の意味論が十分か」は別軸。

未参照の context を DEFER トリガーにする R3(a)（CONFORMANCE 章、次節参照）は実装しない。laarma は
δ を評価前に必ず算出してから policy 評価に渡す同期モデルであり、`derived_signals()` は履歴が無い
シグナルも常にデフォルト値（`semantic_distance=0.0` / `confidence_level=1.0` /
`data_classification=[]` 等）で埋めて返す。したがって「未 populate な context 参照」という状態が
実行時に生じない。ルール側の `context.<signal>` 述語も、値が `None` または空集合のときは
安全側（不一致）に倒して false を返すため、R3(a) 用に accumulator へ未 populate 検出を追加する
必要はない。

---

## 4. DEFER のトリガー: 適合性は R3、FRAMEWORK 章を拾うかは laarma の設計選択

**適合性（conformance）は CONFORMANCE 章 R3 の (a)(b)(c) に対してのみ判定される**（`docs/aarm/deferral.md` §1）。FRAMEWORK 章（§IV-B-4）が DEFER に値する状況をより広くナラティブに列挙しているのは informative な記述で、R3 に対応しない部分は適合要件ではない——実装しなくても AARM に conformant である。したがって当初の「R3 だけだと FRAMEWORK 章を取りこぼすから両方を含めねばならない」という整理は誤りだった。**FRAMEWORK 章の状況を R3 を超えて拾うかどうかは、AARM の適合要件ではなく laarma の設計選択**である。

そのうえで各状況を「laarma が拾う設計選択をするとして、具体的に実装できるか」で精査すると、拾えるものは限られる。

論文の二つの記述:

- **CONFORMANCE 章 R3**（MUST・適合要件）: (a) match predicate が未 populate の context を参照、(b) 同一 priority で複数ポリシーが矛盾、(c) confidence スコア（実装されている場合）が閾値未満。
- **FRAMEWORK 章**（informative・DEFER に値する状況）: (1) 高影響だが allow/deny に十分な confidence がない、(2) 曖昧な意図または矛盾する文脈信号、(3) 不完全な履歴ゆえに不明な複合リスク、(4) 安全性がセッション未取得の情報に依存。

各項の実装可能性（confidence = 評価可能性、危険性 = 別軸。§5）:

- **(1) 高影響だが confidence 不足** → 拾える。「高影響」は危険性軸（destructive_tools / production 等のポリシー条件）で表現し、「confidence 不足」は R3(c) に対応する。両者の**組み合わせ**が DEFER を生む。危険性は confidence に混ぜない。

- **(2a) 曖昧な意図** → 拾える（設計選択）。意図が曖昧かどうかは閾値/集合の決定論述語では書けず、意味理解＝LLM でしか判定できない。これは §5「confidence 計算への LLM 活用」に合流する——LLM が曖昧さを読んで confidence（evaluability）を下げ、R3(c) の閾値を割れば DEFER になる。evaluability の定義（「意図が曖昧で評価しきれない」＝評価可能性が低い）に忠実で、confidence に入れてよいものの典型。

- **(2b) 矛盾する文脈信号** → 特定可能な矛盾のみ拾い、特定不能な矛盾は拾わない。「何と何が矛盾するか」が既知の矛盾（例: `params.src == params.dst`、`copy(src, src)`）は決定論述語で書ける（既知の既知）。一方「どこかに矛盾がある気がするが何と何かは特定できない」矛盾は、LLM に問うても当たり判定ができず（何と何かを特定できていないので検証しようがない）、その出力を confidence に混ぜると confidence が「検証できない何か」で濁る。evaluability の定義に形式上は合致するが、検証不能な判定を混ぜて confidence の意味を濁すので拾わない（§5 の「confidence をゴミ溜めにしない」線引きの適用）。特定不能な矛盾は未知の未知側で、DEFER の対象にならず DENY／射程外（`docs/aarm/deferral.md` §1）。

- **(3) 不完全な履歴ゆえに不明な複合リスク** → 拾える DEFER が残らない。実装に下ろすと三筋に分解され、いずれも DEFER にならない:
  - (i) **履歴窓の不備**: 現行 IA が5履歴サマリしか LLM に渡さないため、email 送信時に先行 PII アクセスが見えず「不完全履歴で DEFER」となるのは、履歴窓を広げれば消える**実装の不備**であって FRAMEWORK 章の状況ではない。PII アクセスは C に蓄積される既知の事実で、これまでアクセスが無ければその時点の email 送信にリスクは無い。
  - (ii) **起きていない事実を待つ**: 「まだ起こっていないこと」に対し履歴が不完全だから DEFER、は待つべき対象が無く、未知の未知を DEFER するのと同じ不条理（`docs/aarm/deferral.md` §1）。
  - (iii) **既知悪性パターンへの接近**: 「あと一手で既知の悪性パターンに完全一致しそうだから DEFER」は、DEFER する限りアクションが実行されずパターンは永久に完成しない——待つのでなく**止める（DENY）**べき。パターンが既知なら既知の**危険性**であり、DEFER（評価可能性）でなく危険性軸で扱う（#100 composite risk）。

- **(4) 安全性がセッション未取得情報に依存** → 参照先がポリシーに書けている既知の未知なら R3(a)（未 populate の context 参照）で捉わる。未知の未知（参照先を書けない）は DEFER の対象でなく DENY（`docs/aarm/deferral.md` §1）。なお laarma の同期モデルでは δ は評価前に必ず算出され「未 populate」が生じないため、R3(a) は現状非発生（並行/非同期実行を採れば発生しうる）。

**まとめ**: 適合性は R3(a)(b)(c) で足りる。laarma が FRAMEWORK 章を超えて拾う設計選択のうち、実装できるのは (1) の組み合わせと (2a) 曖昧な意図（§5 の confidence-LLM 経由）に絞られる。(2b) の特定不能な矛盾と (3) 複合リスクは、拾おうとしても実装可能性・検証可能性・DEFER/DENY の区別の壁に当たり、DEFER として拾わない（該当する筋は決定論ポリシー・DENY・#100 に振り分ける）。したがって §5 の confidence 計算への LLM 活用は、「曖昧な意図」を評価可能性に反映する経路として設計に入れる（決定論で書ける矛盾はポリシーで、危険性は危険性軸で扱う、という境界は保つ）。

上記 (4) は論文解釈としては R3(a) に対応するが、laarma では R3(a) 自体を実装しない（§3「δ 参照の記法」
参照）。laarma の同期モデルでは δ が評価前に必ず算出され「未 populate な context 参照」という状態が
実行時に生じないため、決定論的な (4) の捕捉は R3(a) という機構を介さず構造的に成立する。

### DEFER 後の扱い（#89 に先送り）

決定層（入口）は「DEFER するか」を判定するだけで、「その曖昧さが何で、どう解決できるか」は
DEFER 後の解決機構（#89）に先送りする。これは AARM が入口をクリーンに保つ境界切り分けに沿う
（`docs/aarm/deferral.md` 参照）。confidence が曖昧さを正しく低く算出できるかという較正は #77。

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

なお「特定不能な矛盾」を LLM に判定させて confidence に反映することは**しない**（§4 (2b)）。当たり判定のできない
LLM 出力を混ぜると confidence が検証不能な値で濁り、evaluability という定義の明快さを損なうためである。LLM が
担うのは、次項の「決定論で列挙しきれないが意味論的に特定できる矛盾・曖昧さ」に限る。

### confidence 計算への LLM 活用（多層防御、最初から設計に入れる）

DEFER トリガー (c) の confidence スコアは、論文では計算方法が未定義（実装依存）。ここに laarma は
**多層防御としての LLM を最初から設計に入れる**:

- 引数不足のような**決定論で判定できるもの**は、決定論（ポリシー match / パラメータ検証）で扱う。不確実な LLM に頼らない。
- `copy(src, src)` のような**意味論的に矛盾しているが、全パターンを決定論で列挙しきれないもの**、および**曖昧な意図**（§4 (2a)）は、多層防御として LLM で検出し、confidence を下げる（→ 閾値を下回れば DEFER）。LLM は **decision を出さない**——confidence（評価可能性）という δ の一信号の計算に使われるだけで、decision を出すのはポリシー（confidence 閾値ルール）。

これは AARM 仕様に反しない: semantic distance は式4 で定義されているが、confidence の計算方法は論文が未定義（実装依存）であり、そこに LLM を入れるのは仕様が空けている領域を埋めること。

**多層防御として最初から入れる理由**: LLM がなければ `copy(src,src)` 型の意味論的矛盾は決定論の網をすり抜けて
全て通ってしまう（fail-open の穴）。この穴を「後で不足が観測されたら塞ぐ」と後回しにするのは、
気づいている fail-open を検証都合で放置することになり不適切。最初から confidence 計算に LLM を入れて
fail-closed 側に倒す。LLM が誤検出しても、それは多層防御の一層の限界であり、他の層（決定論ポリシー）が
残っている。どの決定が決定論ルールで下され、どれが confidence 経由（LLM 検出含む）で下されたかを**受領書
（receipt）に記録**すれば、切り分けと検証は担保できる（検証都合で fail-open を残す必要はない）。

なお LLM は最後の網であって唯一の防御ではない。決定論で書ける危険性・矛盾はポリシーで書き、LLM は
「決定論で列挙しきれない意味論的な曖昧・矛盾（ただし特定できるもの）」だけを担う。この境界を守らないと、決定論で書けるものまで
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

- **実装済み・確認可能**: semantic distance の埋め込み計算（式4、`distance_calculator.py`）。決定層のポリシー評価エンジン化（LLM decision 判定の除去、priority 解決、MODIFY の1パス terminal 化、同一 priority 競合の DEFER）— #112 Phase A で実装済み。δ を参照する match predicate の共通機構（`context.<signal>` 述語評価。数値 gt/gte/lt/lte/eq・集合 contains）— #112 Phase B0 で実装済み。semantic_distance・data_classification・confidence の個別ポリシールール（`deny_intent_mismatch_delete`・`step_up_pii_delete`・`step_up_low_confidence`/`defer_low_confidence`）— #112 Phase B1〜B3 で実装済み。confidence の evaluability 定義に基づく LLM 検出層（`confidence_llm.py`。`copy(src,src)` 型の意味論的矛盾・曖昧な意図の検出、fail-closed、受領書への減点幅・検出理由の記録）— #112 Phase C で実装済み。benchmark（`my_project/benchmark.py`）で回帰確認済み。
- **設計のみ・未実装**: 条件2（`distance > 0.4`、本番外・`delete_file` 以外への一般化）・条件14
  （production + destructive → STEP_UP）— #112 Phase D の再検証で未実装と確定し、priority 帯の
  割り当て設計とあわせて [#129](https://github.com/y-nakata/laarma/issues/129) に申し送り済み。
  DEFER トリガーの整理（適合性は R3、FRAMEWORK 章は実装可能なもの〔(1) 組み合わせ・(2a) 曖昧な意図〕
  のみ設計選択で拾う）のうち δ 依存部分の網羅的な検証。
- **条件1〜15 の再検証完了（#112 Phase D）**: 条件1・13・15 はデフォルト benchmark 実行で確定再現
  （`deny_dynamic_delete_intent_mismatch`・`step_up_pii_delete`・`step_up_low_confidence_external_action`）。
  条件6・7・12 は明示 ALLOW ルール化の対象（#139）。「baseline ALLOW で自然に出るため専用ルール不要」という従前の判断は、非重複が無検証・明示性の喪失・将来衝突の非検知の3点で誤り。
  条件3・4 は既存の記述どおり（別 Issue の穴）。条件11 は廃止（#137）。条件9/10（デモシナリオ8「古いファイル」）
  はメカニズム自体は実装済みだが、`benchmark.py` のデフォルト実行が意図的に `NullConfidenceLLM`
  スタブを使うため `defer_dynamic_ambiguous_delete` は `known_regression_until: "Phase C"` のまま
  素通りし続ける——詳細は §3「条件9/10: メカニズムとベンチマークのデフォルト実行の乖離」を参照。
  実 LLM 経路（`demo.py`・`--pipeline`）での再現は `ANTHROPIC_API_KEY` を持つ環境での実行で
  確認済み——`--pipeline` 実行で `defer_ambiguous_delete_llm_detected`・`step_up_semantic_contradiction_copy`
  がいずれも期待どおりの decision になった。`demo.py` シナリオ8 でも `delete_file` が confidence 0.363
  で DEFER に入ることは確認したが、その先の `DeferralResolver` による自律解決は保留中で未実行の
  アクションを「実行済み・重複」と誤認した根拠不成立の DENY であり、正常な DEFER 解決の確認には
  なっていない（詳細は §3「条件9/10」節末尾。DEFER 解決層の LLM decision 除去は #135 で扱う）。
  条件2・14 は上記のとおり未実装と確定。
- **他 Issue 依存**: confidence 較正（#77）、DEFER 解決機構（#89）、scope_expansion 再設計（#99）、
  composite risk（#100）、priority 体系化（#129。条件2・14 の割り当てを含む）。δ 参照ポリシーは
  本リファクタ内で段階実装（旧 #107 吸収）。

---

## 関連

- 論文解釈の土台: [docs/aarm/classification-and-policy-model.md](../aarm/classification-and-policy-model.md)（Table I・Policy Structure・測定と評価の二段）、[docs/aarm/deferral.md](../aarm/deferral.md)（DEFER の informative/normative 二層・既知/未知の未知・confidence 解釈）
- AARM 論文 arXiv:2602.09433: 式2（Context Accumulation）、式3（Policy Structure）、式4（semantic distance）、R3・R7、§IV-B-4（FRAMEWORK 章 DEFER）、§IV-C、Contribution 2
- 旧・提案/上書きモデル（本設計により置き換え済み、アーカイブ）: [docs/design/policy-engine-proposal-override.md](policy-engine-proposal-override.md)
- リスク把握（δ でのリスク把握・危険性軸の集合・confidence≠危険性）: [docs/design/risk-classification.md](risk-classification.md)
- 環境条件の扱い: [docs/design/environment-demo-fiction.md](environment-demo-fiction.md)（本リファクタが触る `_match_conditions` の環境条件〔`environment_type` / `not_in_maintenance_window`〕、および §3 条件14 の environment=production は、汎用の環境評価入力ではなくデモフィクションとして踏襲する。E は AARM の (a, C) 入力ではない〔[docs/aarm/environment-and-context.md](../aarm/environment-and-context.md)〕）
- 関連 Issue: #112（本設計の実装。#94 後継）、#94（signal/decision 分離。#112 に立て直し・not_planned クローズ）、#107（δ 参照拡張。#112 に吸収・not_planned クローズ）、#99（scope_expansion）、#100（composite risk）、#77（confidence 較正）、#89（DEFER 解決機構）
