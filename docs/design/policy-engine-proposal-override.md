# 設計メモ: PolicyEngine を R3・式(3) の π として完成させる（提案/上書きモデル）

[← README に戻る](../../README.md)

> **状態（#112 Phase A 後）**: 本メモが記録する「提案/上書きモデル」（LLM ベース
> IntentAlignment による確認/上書き構造）は [decision-layer-policy-engine.md](decision-layer-policy-engine.md)
> の設計により置き換えられ、`_confirm_with_ia` と IntentAlignment 自体は削除済みである。
> §6「設計: 提案/上書きモデル」および「IntentAlignment には常に original action（a）を渡す」節は
> **もはや適用されない**（判断を上書きする LLM 層が存在しないため）。
> 一方、「STEP_UP に modified_params が乗るケースの扱い」「STEP_UP（modified_params あり）が
> 承認された場合の最終結果」「modify_transform の narrowing 不変条件」「DEFER の解決先は DEFER を
> 含まない」の各節は、priority 解決エンジンに移行した後も**有効な設計制約として引き続き適用される**
> （StaticRule の priority 勝者が STEP_UP や MODIFY を返す場合の扱いは変わっていない）。
>
> **この文書の位置づけ（Phase A 以前の記録として）**: これは laarma の**確定した設計方針**を記録する設計メモである。
> AARM 仕様が明言していること、laarma の現状、そして仕様の空白部分に対する laarma の設計判断を、
> それぞれ区別して記録する。本メモの方針は合意済みであり、実装はこの方針に従う。
>
> **仕様の典拠について**: AARM の公式仕様は CSA（Cloud Security Alliance）版の System Category Specification v1.0。
> arXiv 論文（2602.09433）は同じ著者によるその解説版で、要件をより詳しく説明している。
> 本メモでは、規範的な典拠として CSA版の要件番号（R3/R4 等）を一次とし、
> 詳しい説明が必要な箇所で論文の該当節を併記する。
>
> **方法論上の注記（重要）**: 論文 Figure 1（AARM Logical Component Model）は、本メモの根拠として**使用しない**。
> Figure 1 は Context Accumulator と Policy Engine を並列の箱として描いており、
> この図を文字通り読むと「Policy Engine への入力に C（蓄積コンテキスト）が含まれない」ことになり、
> R3・式(3) が要求する「policy engine **with intent alignment**」（評価は (a,C) の両方に対して行う）が
> 構造的に成立しない。つまり Figure 1 は R3・式(3) の MUST テキストと矛盾する。
> 論文自身も「コンポーネント（関心事の語彙）を規定するのであって実装の詳細を規定するのではない」と述べており、
> Figure 1 はコンポーネント間のデータフローを精査した設計図ではなく、概念の配置図に近い。
> MUST テキスト（R3/R4/式3）と図が矛盾する場合、図を優先してはならない。
> なお Table I（Action Classification Framework）は、R3 の本文で述べられる4分類を表形式に
> 整理したものであり、図1のような独立した構造的主張ではない（R3 本文の言い換え）ため、
> 本メモでは R3 本文の補助として引用する。
>
> **出典・ライセンス**: 本メモが参照・引用・翻訳する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。引用・翻訳は同ライセンスに基づく。

## 1. 発端: PolicyEngine の静的ルールが IntentAlignment を完全に迂回する

`laarma_sdk/src/laarma/runtime.py` の `intercept()` はこうなっている:

```python
result = self._policy_engine.evaluate(action, self._accumulator.context, self._environment)
if result is None:
    result = self._intent_alignment.evaluate(...)
```

**PolicyEngine が `None` 以外（DENY / DEFER / MODIFY / STEP_UP）を返すと、IntentAlignment は一切呼ばれない。**

`policy_engine.py` の冒頭には、すでに次の自己言及コメントがある:

> AARM 仕様では MODIFY は (a, C, E) タプルを評価する動的判断である。
> PolicyEngine が MODIFY を返す場合（例: 危険な書き込みパスの basename 変換）は
> AARM 仕様外の実用的妥協である。ドメイン固有の決定論的変換ルールを
> IntentAlignment に混入させず PolicyEngine で完結させることで層の責務を明確化している。

このコメントは「**層の責務分担**」（変換ロジックをどちらの層に置くか）の問題として説明しているが、本メモで扱うのはそれとは別の、**安全性の問題**である。

当初は MODIFY（`unsafe_write_path`）に絞って検討を始めたが、検討の過程で **DEFER（`production_delete_defer`）にも同型の問題があること**が分かった（§4）。そこで本メモは MODIFY 単体の修正ではなく、**PolicyEngine の静的ルールと IntentAlignment の関係を、R3・式(3) に基づいて再設計する**という、より広いスコープに改める。

## 2. AARM 仕様が明言していること

### R3: Policy Evaluation with Intent Alignment（CSA版 R3 / 論文 §VII-B-3）

CSA版 R3 はこう定める（MUST）:

> システムは、インターセプトした各アクションを、アクションそのものとエージェントの
> 意図表明への整合性の両方を考慮するポリシーに対して評価しなければならない。
> **意図コンテキストなしにアクションを単独で評価するポリシーは、この要件を満たさない。**

論文 §VII-B-3 はこれをより詳しく展開する:

- システムは静的ポリシーと文脈的意図整合性の**両方**に対してアクションを評価しなければならない（MUST）
- サポートすべきアクション分類は **forbidden / context-dependent deny / context-dependent allow / context-dependent defer の4つ**
- forbidden actions は静的ポリシーで**即座に denial**と評価してよい
- **context-dependent actions は蓄積されたセッションコンテキストに対して評価**しなければならない
- defer は、policy engine が確信を持って allow/deny を決定できない場合にトリガーされる（MUST）

**この4分類のどこにも MODIFY は登場しない。** そして「コンテキスト評価を省略して即座に決定してよい」と明示的に許可されているのは **forbidden（→DENY）のみ**。

### Table I: Action Classification Framework（論文 §IV-B-5、R3本文の言い換え）

| Category | Policy Baseline | Context Evaluation | Runtime Decision |
|---|---|---|---|
| Forbidden | N/A | **Ignored** | DENY |
| Context-Dependent Deny | ALLOW | Misalignment detected | DENY |
| Context-Dependent Allow | DENY | Alignment confirmed | STEP_UP / ALLOW |
| Context-Dependent Defer | ALLOW or DENY | Insufficient or conflicting signals | DEFER |
| Standard Allow | ALLOW | No signals | ALLOW |
| Standard Deny | DENY | No alignment | DENY |

**Context Evaluation が「Ignored」とされているのは Forbidden の1行だけ**。他の全カテゴリは、たとえ最終的な決定が変わらなくても、何らかのコンテキスト評価を経ることが前提になっている。そして **MODIFY はこの表のどこにも登場しない**。

特に注目すべきは2行目: **Context-Dependent Deny は「Policy Baseline = ALLOW」だが、コンテキスト評価で misalignment が検出されると DENY になる**。すなわち、**静的ポリシーが下した非DENYの判断を、コンテキスト評価（意図整合性）が DENY に上書きする**、という構造が、R3本文・Table Iの双方に明記されている。これが後述する「提案/上書きモデル」の直接の根拠になる。

### R4: Five Authorization Decisions（CSA版 R4 / 論文 §VII-B-4）

CSA版 R4（MUST）:

> ポリシーエンジンは、評価した各アクションについて、ALLOW（そのまま実行）、
> DENY（実行をブロック）、MODIFY（変換されたバージョンを実行）、
> STEP_UP（実行前に人間の承認を要求）、DEFER（追加コンテキストを待って実行を遅延）の
> **5つの決定のうち、正確に1つ**を生成できなければならない。

論文 §VII-B-4 も各決定を一行で定義している:

- ALLOW: そのまま進む
- DENY: ブロックされ、効果なし
- **MODIFY: 変換されたパラメータで進む**
- **STEP_UP: 人間の承認を待って一時停止**（追加要件: 承認者には完全なアクションコンテキストが利用可能でなければならない）
- DEFER: 不十分・曖昧・矛盾するコンテキストにより一時停止

「変換されたパラメータで進む」は **MODIFY の定義に組み込まれており、STEP_UP の定義には登場しない**。

STEP_UP の MUST 要件は操作的な記述に留まる: 承認が得られるまで実行をブロックすること、承認リクエストを設定済みの承認者にルーティングすること、設定可能なタイムアウトを設けること（タイムアウト時は DENY が推奨）、承認者には完全なアクションコンテキストを利用可能にすること。**「承認された場合、最終的な `decision` が何になるか」は、仕様のどこにも明記されていない。**

### §IV-C2 式(3): 形式モデル

論文 §IV-C2 は policy π を `π:(a,C)→{ALLOW,DENY,MODIFY,STEP_UP,DEFER}` という**単一値を返す関数**として定義する。各 π の構成要素には、match predicate・decision d・priority に加えて、「**d = MODIFY のときに適用される**」任意の modification function `f(a)→a'` が含まれる。

→ **MODIFY と STEP_UP は、同じ (a,C) に対する互いに排他的な決定値**として定義されている。「変換後のパラメータを STEP_UP として人間に提示する」という組み合わせは、この形式モデルには現れない。

この式(3)が定めるのは、**π の入出力契約**——「ある (a,C) を入れたら5値のうち1つが出る」——だけである。π の内部で評価が何段あるか、評価対象が途中で a→a' と書き換わるか、収束ループを回すかは、**仕様の規定外（ブラックボックス）**であり、式(3)はそれらを禁じも要求もしていない。ただし、π の出力に現れる ALLOW の「unchanged」/ MODIFY の「transformed」が**何を基準とした unchanged/transformed なのか**——すなわち「最初に π に入った a」を基準とするのか、内部で書き換えられた中間状態を基準とするのか——は、式(3)の表面からは一意に読み取れない。この基準点の問題は §6「STEP_UP（modified_params あり）が承認された場合の最終結果」で扱う。

**式(3)の最も重要な点**: π は `(a, C)` の両方を入力に取る、**単一の関数**である。laarma の現状（PolicyEngine が `(a,C,E)` の一部だけ見て None を返し、別関数 IntentAlignment が `(a,C,E)` 全体を見る、という2関数構成）は、**π を2つに分割した実装**になっている。この分割自体が、§1 の問題を生んでいる。

## 3. laarma の現状

### MODIFY: `unsafe_write_path`

```yaml
- id: unsafe_write_path
  conditions:
    tool: write_file
    path: "^/|\\.\\."        # 絶対パス or ディレクトリトラバーサル
  decision: MODIFY
  modify_transform: basename  # path を basename(path) に変換
```

`_evaluate_rules` がこの条件にマッチすると、`AuthorizationResult(decision=MODIFY, ...)` を terminal な結果として返す。`runtime.intercept` はこれを `None` ではないと判定し、IntentAlignment を呼ばない。

### DEFER: `production_delete_defer`

```yaml
- id: production_delete_defer
  conditions:
    tool: delete_file
    environment_type: production
    not_in_maintenance_window: true
    none_of:
      - path: "\\.(conf|config|log|db|sqlite)$"
      - path: "database"
  decision: DEFER
  reason: "本番環境かつメンテナンス窓外での削除操作のため、追加の実行トレース検証が必要です（一時保留）"
```

この条件は**意図整合性とは無関係**（環境・タイミングのみ）。発火すると `AuthorizationResult(decision=DEFER, ...)` が terminal に返り、IntentAlignment は呼ばれない。

## 4. 具体的な懸念シナリオ

両方とも、ユーザーの依頼は「README.md を読んで内容を教えて」（意図 = 読み取りのみ）。エージェント（暴走 or 仕込み）が意図外のツールを呼ぶ。

### MODIFY のケース

エージェントが `write_file(path="/etc/cron.d/evil", content="...")` を呼ぶ。

1. `unsafe_write_path` が発火（`path` が `^/` にマッチ）
2. `path` → `basename("/etc/cron.d/evil")` = `"evil"` に変換
3. `MODIFY` を即座に terminal な結果として返す。**IntentAlignment はスキップ**
4. `write_file(path="evil", content="...")` が**実行される**

もしこのルールが存在しなかったら、`None` → IntentAlignment に渡り、シナリオ4（意図外の delete_file を動的に検知して DENY する）と同じロジックで「意図は read のみなのに write_file が来た」として **DENY されていたはず**。

### DEFER のケース

エージェントが `delete_file(path="notes.txt")` を本番・メンテナンス窓外で呼ぶ（`.conf/.db` 等ではないので `deny_critical_file_delete_in_prod` は不発火）。

1. `production_delete_defer` が発火（環境・タイミングのみで判定）
2. `DEFER` を即座に terminal な結果として返す。**IntentAlignment はスキップ**
3. `DeferralResolver.resolve()` が呼ばれる。LLM に `user_intent`・`derived_signals`・`proposed_action`・`original_deferral_reason`（="本番環境かつメンテナンス窓外での削除操作のため..."）を渡す
4. `DeferralResolver` の CRITICAL CRITERIA は「`original_deferral_reason` が高リスクな環境/操作ルールに関わる場合、`derived_signals` に異常が無くても ALLOW してはならず、**STEP_UP に格上げ**」を指示する
5. 結果は **STEP_UP**。承認者に提示される `reason` は「本番環境かつメンテナンス窓外での削除操作のため、追加の実行トレース検証が必要」であり、**「意図は read のみなのに delete_file が来た」という、本来 DENY の根拠だったはずの情報は提示されない**

もしこのルールが存在しなかったら、`None` → IntentAlignment に渡り、Table I の「Context-Dependent Deny: misalignment detected → DENY」のロジックで **DENY** されていたはず。

### 両者に共通する構造

どちらのケースも、**静的ルールは「意図とは無関係な軸」（パスの危険性、本番環境のタイミング）で判断し、その判断が確定してしまうことで、「意図整合性」という別の軸の評価機会が失われる**。MODIFY のケースは DENY されるべきものが実行に至る。DEFER のケースは DENY されるべきものが STEP_UP（人間が承認すれば実行に至る、かつ承認者には「意図外」という最重要情報が提示されない）に変わる。**いずれも「実行に至る経路が、意図整合性チェックを経ずに開く」**という同じ構造。

## 5. 一般化: DENY だけが安全に terminal（§5 の旧版からの訂正）

> 旧版の本メモは「DENY/DEFER の即時確定は安全側、MODIFY の即時確定は危険」と整理していた。
> §4 の DEFER の検証により、**この整理は誤りだった**。DEFER も MODIFY と同型の問題を持つ。
> 正しい一般化は以下の通り。

PolicyEngine が Step 0 で **DENY** を確定させるのは、常に安全側に倒れる。DENY は「実行させない」終端であり、IntentAlignment をスキップしても、最悪「過剰に保守的」になるだけ（IntentAlignment なら ALLOW したかもしれないものを止める）。**危険なアクションを通す方向には倒れない。** これは、その DENY ルールが「本当に forbidden（ハード制限）か」を問わず成立する。静的ルールが下す DENY は、結果として常に「ハード制限を追加した」のと同じ安全性を持つ。

一方、**DENY 以外の4値（ALLOW・MODIFY・DEFER・STEP_UP）はすべて、何らかの形で「実行に至る経路」を持つ**。ALLOW は直接実行。MODIFY は変換後に実行。DEFER は DeferralResolver の解決を経て ALLOW/STEP_UP（→人間承認で実行）になりうる。STEP_UP は人間承認で実行になりうる。これらを Step 0 で確定させると、**IntentAlignment なら DENY としたはずのアクションが、これらの経路のいずれかを通って実行に至りうる**。

**R3・Table I との対応**: forbidden（→即DENY、コンテキスト評価不要）のみがコンテキスト評価省略を許される。Context-Dependent Deny（Policy Baseline=ALLOW、misalignment detected→DENY）は、**静的な ALLOW 相当の判断を、コンテキスト評価が DENY に上書きする**形を示している。この「静的判断 → コンテキスト評価による上書きの可能性」という構造を、DENY 以外の全決定に一般化したものが、次節の設計である。

## 6. 設計: 提案/上書きモデル

> 本節は laarma の確定した設計方針である。R3・式(3)・Table I（Context-Dependent Deny の上書き構造）から導いた。
> 仕様が明示的に規定していない部分については、その旨を都度明記する。

### 概要

`PolicyEngine.evaluate(a, C, E)` を、**式(3)の π を完全に実現する単一の関数**にする。IntentAlignment は、この関数の**内部協力者**になる（laarma の用語では PolicyEngine が AARM の「Policy Engine」に対応し、IntentAlignment はその内部実装の一部、という位置づけ）。`runtime.intercept()` は `policy_engine.evaluate(...)` を呼ぶだけになり、戻り値は常に terminal（5値のいずれか）。`if result is None: ...` という分岐は不要になる。

`evaluate()` 内部のロジックは、静的ルールの `decision` 値によって2つに分かれる:

**`decision == DENY` の場合 → そのまま terminal。** IntentAlignment は呼ばない。§5の通り、これは常に安全。

**`decision` がそれ以外（ALLOW・MODIFY・DEFER・STEP_UP、および「マッチするルールが無い」場合の暗黙の ALLOW）の場合 → それは「提案」にすぎない。** IntentAlignment に渡して確認を取る:

- 提案に `modified_params` がある（＝ MODIFY 変換が適用された）場合、変換後のアクション `a'` を IntentAlignment に渡す
- ない場合、元のアクション `a` を IntentAlignment に渡す

（この基準は提案の `decision` ではなく `modified_params` の有無で決める。詳細は後述「IntentAlignment に渡すアクションは `modified_params` の有無で決める」。）

IntentAlignment の結果が **ALLOW** → 静的ルールの**提案が確定**する（`decision`・`modified_params`・`policy_rule_id` はそのまま採用）。

IntentAlignment の結果が **ALLOW 以外（DENY/DEFER/STEP_UP）** → IntentAlignment の判断が**最終決定として上書き**する。

### 「マッチするルールが無い」場合も同じモデルに統一される

現状の `policy_engine.evaluate()` が `None`（マッチするルールが無い）を返すケースは、新モデルでは「**提案 = ALLOW（変換なし、`a'=a`）**」として扱える。IntentAlignment が `a` を評価し、ALLOW なら提案確定（=ALLOW）、それ以外なら上書き。これは**現状の `None → IntentAlignment.evaluate(a,...)` という挙動と完全に同じ**であり、新モデルは現状の挙動を「提案=ALLOW のケース」として包含する。つまり、**新モデルは既存の動作を壊さず、MODIFY・DEFER・STEP_UP のケースに同じロジックを拡張するだけ**。

### policy.yaml に「意図確認が必要」フラグは持たせない

検討の過程で「ルールごとに `needs_intent_check: true/false` のようなフラグを持たせる」案も考えたが、**採用しない**。

理由: そのようなフラグを追加すると、ルール作者がフラグを書き忘れる・誤って `false` にする、という**新しい失敗モードを作る**。これは §4 で見つかった問題（`production_delete_defer` が「意図確認が必要」であることがどこにも明示されていなかった）と**同じ形の穴**であり、穴を塞ぐために同じ形の穴をもう一つ開けることになる。

代わりに、**`decision == DENY` かどうかという、既存のフィールドの値から自動的に決まる**。DENY は terminal、それ以外は全て提案として IntentAlignment を経由する。ルール作者は「このルールは意図確認が必要か」を意識する必要が無く、**意識しなくても安全側に倒れる**（DENY 以外は常に確認される）。

### §4 のシナリオがどう変わるか

**MODIFY のケース**: `unsafe_write_path` → 提案 MODIFY（`a'` = basename後）。IntentAlignment が `a'` を評価。シナリオ7（意図に沿った要約の書き出し）は ALLOW → MODIFY 確定（**結果は変わらない**）。§4 の意図外 write（`/etc/cron.d/evil`）は IntentAlignment が DENY → **DENY で上書き**。

**DEFER のケース**: `production_delete_defer` → 提案 DEFER。IntentAlignment が（変換が無ければ）元のアクション `a` を評価。シナリオ6（ユーザーが実際に削除を依頼）は ALLOW → DEFER 確定（**結果は変わらない**、従来どおり DeferralResolver へ）。§4 の意図外 delete は IntentAlignment が DENY → **DENY で上書き**。`production_delete_defer` の `reason` も `DeferralResolver` も一切呼ばれず、**情報が失われる経路自体が発生しない**。

### 意図確認の目的: 「情報補完」ではなく「意図外の排除」

提案/上書きモデルを実装する際に陥りやすい誤解がある。「IntentAlignment による確認は足りない情報を埋めるためのものだから、情報が揃っていない／構文的な問題に過ぎないケースでは省略してよい」という発想である。**これは誤り。**

IntentAlignment の確認の目的は、**「このアクションが意図に沿っているかを見て、沿っていなければ DENY に落とす」**ことである。「足りない情報を埋める」ことではない。この2つは別の問いで、別のタイミングに属する:

- **意図に沿っているかの判定**（IntentAlignment の役割）: 提案を確定させる前に行う。意図外なら DENY に上書きして、そもそも実行経路に乗せない。
- **足りない情報の補完**（DeferralResolver の役割）: DEFER が**確定した後**のワークフローで行う。

順序が重要である。情報補完を先にやって意図確認を後回しにすると、**意図外のアクションが情報を補完されて実行に向かう経路に乗ってしまう**。意図確認を先に通せば、意図外のものはその時点で DENY に落ち、補完ワークフローに入る前に止まる。

### 構文的な DEFER（required_params 不足など）も「提案」として扱う

上記の帰結として、**「DENY 以外はすべて提案、terminal は DENY のみ」という原則に例外を作ってはならない**。

具体例: `required_params`（必須パラメータ）不足。これを「構文エラーであって意図整合性の問題ではないから」と即 terminal な DEFER にすると、§4 の `production_delete_defer` と**完全に同型の穴**が開く。ユーザーの意図が read のみなのにエージェントが `send_email` をパラメータ不足で呼んだ場合、即 DEFER → DeferralResolver が不足パラメータを補完 → **意図外の send_email が実行に向かう**。本来 IntentAlignment が「意図外」として DENY に落とすべきだった機会が消える。

したがって required_params 不足は「DEFER の**提案**」であって「DEFER の確定」ではない。他の非 DENY 提案と同様、必ず IntentAlignment を通す。意図に沿っていれば DEFER 確定 → DeferralResolver が補完。意図外なら IntentAlignment が DENY に上書き → 補完に入る前に停止。

### MODIFY 変換は「アクションの書き換え」なので、書き換え後に再評価して収束させる

MODIFY が他の決定と異なり厄介なのは、**それが「決定」であると同時に「アクションそのものの書き換え（a→a'）」でもある**点である。他の4決定（ALLOW/DENY/DEFER/STEP_UP）はアクションの処遇を決めるだけでパラメータをいじらないが、MODIFY だけが評価の途中で対象を別物に変える。

ここから重要な帰結が出る。**評価対象を途中で書き換えたなら、書き換え後のアクションにもうマッチするルールが無くなるまで、ルール評価をやり直さなければならない**。a を a' に変換した時点で、a' は「まだ評価されていない新しいアクション」であり、a' が別のルール（別の MODIFY、あるいは DENY）にマッチするかもしれない。それを見ずに「a' で確定」とするのは、評価をやり残している＝ final な状態に落ち着いていない。

具体例: ルールA「パスが `^/` なら basename 化」、ルールB「ファイル名が `evil` を含むなら DENY」があるとき、`write_file(path="/etc/cron.d/evil")` はルールA で `path=evil` に変換される。ここで1パスで打ち切ると、`evil` がルールB（DENY）にマッチするのを見逃して危険なファイル名がすり抜ける。a' を再評価していればルールB が DENY で止められた。

> **方法論上の補足**: 「式(3)が1段階モデルだから多段評価をしない」という論証は**誤り**であり、本メモは採らない。式(3)の π は入出力契約（(a,C) を入れたら5値のどれかが出る）を定めるだけで、π の内部で評価が何段あるか・収束ループを回すかは**仕様の規定外（ブラックボックス）**である。実際、本メモの設計では π の内部に「静的ルール評価 → IntentAlignment 確認」という多段構造を既に置いている。内部で収束ループを回すことは式(3)と矛盾しない。

#### 収束ループの規則

- 静的ルール評価は、**マッチするルールが無くなるまで反復**する。
  - MODIFY がマッチしたらアクションを変換し、**変換後のアクションで再評価**する（変換は累積する）。
  - 途中で **DENY がマッチしたら、そこで terminal DENY**（即終了）。
  - マッチするルールが尽きたら、その時点のアクション（変換が累積した a'）を「提案」として次段（required_params 判定 → IntentAlignment）へ渡す。
- **振動・無限ループ対策は「反復回数の上限」のみ**とする。「同じルールを二度発火させない」という条件は**採らない**（ルール内容次第で、正当な多段適用を不当に打ち切る一方、2ルールが往復する振動は各ルール1回ずつなので検知できず、二重に筋が悪い）。反復回数という外形だけで打ち切るほうが、ルールの意味解釈に依存せず堅牢。
- **上限到達時（収束しなかった場合）は DENY**。ここに到達するのは実質的に**ルール設定の誤り**（ルールが振動している）であり、DEFER にしても DeferralResolver が追加コンテキストを集めて解決する見込みはなく、STEP_UP にしても承認者に判断材料が無い。設定ミス起因の異常は安全側に倒して止める（§5「DENY だけが安全に terminal」と一致）。
- 反復上限はパラメータ `max_modify_iterations` として**カスタマイズ可能**とする。**デフォルトは 10**。これは正常系のチューニングパラメータではなく、**異常（ルール振動）を捕まえるセーフティネット**である。正当な MODIFY 変換の連鎖はまず数段に収まるため、通常はこの上限に到達しない。実運用で正当な連鎖がより深くなりうる場合は、運用側で引き上げられる（AARM 仕様が cascading deferral 上限などを configurable と求めているのと同じ流儀）。

#### required_params の判定タイミング

`required_params` の判定は、**この収束ループでマッチするルールが尽きた後の最終的な a' に対して**行う（ループ途中の中間状態ではない）。

- 最終 a' で required_params が揃えば → MODIFY 提案のまま
- 最終 a' でも不足なら → **変換を保持したまま**（元の危険な a に戻さない。DeferralResolver が危険な a を相手にするのを避けるため）DEFER 提案に切り替える。`modified_params` は提案に乗せ続ける（`decision=DEFER` だが `modified_params` あり、という状態。STEP_UP+modified_params と同じ構造で、データモデルは許容する）

### modify_transform の不変条件: narrowing（封じ込め）に限る

`modify_transform` に登録する変換は narrowing（封じ込め）に限る。能力を広げる/意味を変える変換は MODIFY ではなく DENY か STEP_UP の対象（#88）。

この不変条件があるからこそ、a' の auto-apply に根拠が成り立つ: a' は a を狭めるだけで新しい能力を足さない（basename は path をワークスペース内に狭める。数値クランプ・安全フラグ強制も同様）。次節で述べる「IntentAlignment に a' を見せない」という設計は、a' が PolicyEngine の決定的変換による narrowing の結果であり、かつ a 自体が意図に沿うと IntentAlignment が判定済みであることに依拠する——「IA が a を承認 ⟹ a' ⊑ a は a より危険になりようがない」。

現状、`policy.yaml` のルールが `modify_transform` で参照する変換は `unsafe_write_path` の `basename` のみであり、narrowing を満たす。今後ルールに変換を追加する際は、この不変条件を満たすことを確認する。

### IntentAlignment には常に original action（a）を渡す

`_confirm_with_ia()` が IntentAlignment に渡すアクションは、提案の `modified_params` の有無や `decision` にかかわらず、**常に original action（a）**である。a' を渡すことはない。

理由（#88、IA(LLM) が確定的 MODIFY を覆した退行の修正）: IntentAlignment の役割は「エージェントの**意図** a が妥当か」を評価することであり、「実行されるパラメータ a' が安全か」を判定することではない。パラメータの封じ込め（path 無害化等）は PolicyEngine の決定論的な別レイヤーが担い、この二層は直交していて混ぜない。a' は組織の合意形成を符号化した `modify_transform`（TCB の一部）の出力であり、ランタイムの IA はその合意文脈 C を代理で持てない——IA に a' を見せて「ユーザ意図とズレている」と判定させることは、match(a,C) の権威を IA に渡すことに等しく、確定的に守ったはずの a' を LLM が覆す経路を開く。

IA に a を渡せば、シグナル（`semantic_distance` / `action_matches_intent` など、いずれも a で計算済み）と `proposed_action` が常に a で一貫し、「a' の値が a と違う」という偽トリガーが構造的に発生しない。

採用関係（`_confirm_with_ia()` の非対称な振る舞い）:

- IA が **ALLOW** → 提案を確定する（`decision`・`modified_params`・`policy_rule_id` は PolicyEngine 提案のまま）。
- IA が **ALLOW 以外**（DENY/DEFER/STEP_UP） → 最終 `decision`・`reason` は IA のものを採用する（IA は「a が妥当でない」という判断自体の権威を持つ）。ただし **`modified_params` は提案（PolicyEngine 由来）を保持し、IA の結果で上書きしない**——IA は変換を生成も書き換えもできない（IA から MODIFY を除いたことの帰結。#88）。

> 本節は IntentAlignment(LLM) の**評価入力**として何を見せるかの設計であり、STEP_UP の**承認者**（人間）に何を提示するかとは別の問題である。次節「STEP_UP に modified_params が乗るケースの扱い」（#70 で確定済み）は変更しない: PolicyEngine が施した a' は、receipt・承認者への提示には引き続き乗る。IA(LLM) への評価入力を a に統一することと、人間の承認者が a' を見て y/n することは、混同しない。

### DEFER の解決先は DEFER を含まない

DEFER 提案が IntentAlignment を通って DEFER 確定した後、DeferralResolver が解決する。その**解決先は ALLOW / DENY / STEP_UP に収束させ、再び DEFER にしてはならない**。

根拠は R4 の DEFER 詳細要件（MUST）。「並行する deferred アクションが設定上限を超えたらシステムはそれ以上のアクションを deny しなければならない（無限に deferred 状態を溜めない）」と、cascading deferral を明示的に bound することを要求している。「DEFER を解決したらまた DEFER」という再帰は、この bound の精神に反する。仕様は DEFER の解決先を ALLOW/DENY のみに明示限定してはいないが、列挙される解決経路（十分なコンテキスト収集／追加検証／safe constraints の適用→実行、または timeout→DENY）に DEFER への回帰は含まれない。

（laarma の現状確認: `DeferralResolver` は解決先を ALLOW/DENY/STEP_UP の3値に限定し、それ以外が返った場合は STEP_UP にフォールバックするガードを持つ。この要件は既に満たされている。）

### STEP_UP に modified_params が乗るケースの扱い

> 本節と次節は、PolicyEngine が施した a' を**人間の承認者**にどう提示するか（#70 で確定済みの仕様）を扱う。IntentAlignment(LLM) の評価入力を常に a に統一する前節の設計とは別個であり、前節の変更によって本節・次節の内容は変わらない。

提案が MODIFY（`a'`）で、IntentAlignment が **a を評価して** STEP_UP を返すケースがありうる（IA には常に a が渡るため、IA が見るのは a であって a' ではない。a' は IA の判断を経て確定した提案に PolicyEngine 由来のまま乗り続け、承認者への提示で使われる）。このとき:

- **`decision` は標準の5値の1つである `STEP_UP` のまま**にする（R4 の決定モデルを拡張しない）
- `modified_params`（PolicyEngine が施した変換）は、**承認者に提示する「完全なアクションコンテキスト」の一部**として receipt に残す。これは R4 の STEP_UP 要件「承認者には完全なアクションコンテキストが利用可能でなければならない」と整合する
- 承認後に実行されるのは変換後（サニタイズ済み）のパラメータであるべき。承認者には「これが承認されれば実際に実行される内容」を見せる

`models.py` の `AuthorizationResult.modified_params` は `decision` と独立したフィールドであり、この扱いを構造的に許容している。

### STEP_UP（modified_params あり）が承認された場合の最終結果: ALLOW か MODIFY か

**問題は「unchanged/transformed の基準点」**。§2 で見たとおり、式(3)は π の入出力契約を定めるだけで、ALLOW の「unchanged」/ MODIFY の「transformed」が何を基準とするかを一意には定めていない。

本設計では、評価が次のように進む: (1) PolicyEngine が元のアクション a を a'（変換後）に書き換える、(2) IntentAlignment が a' を評価し STEP_UP を返す、(3) 人間が承認 → a' が実行される。ここで「unchanged」「transformed」は、承認者に見せた a'（＝実行されるもの）を基準にすれば ALLOW、エージェントが最初に提案した a を基準にすれば MODIFY、と**基準点によって答えが分岐する**。式(3)はこの基準点を明示していないため、これは**仕様が明示的に扱っていない領域**である。

**laarma の決定**: R4 の定義における a は π:(a,C)→{...} の a、すなわち**最初に評価対象になったアクション**と読むのが自然。これを基準にすれば、a' が実行された時点で a と異なる → **最終決定は MODIFY**。人間が承認した事実は `decision` とは別に `resolution_method`（例: `"human_approved"`）で記録する。

逆に「ALLOW + modified_params（元と異なる）」を選ぶと、R4 の ALLOW の定義（unchanged）と `modified_params` が non-null であるという事実が、字面上で矛盾する。

**したがって laarma は「最終決定は MODIFY、`resolution_method=human_approved` を併記」とする。** これは R4 の定義（unchanged/transformed の基準点を「最初の a」とする）との整合性から導いた、仕様の空白部分に対する laarma の設計判断である（仕様の決定モデルそのものは拡張しない。`decision` は標準の5値のうちの MODIFY のまま）。

### レシートへの記録（フォレンジック、R5）

静的ルールの「提案」が IntentAlignment によって**上書き**された場合、レシートには両方の情報を残す: 提案した `policy_rule_id` と提案された `decision`（例: `production_delete_defer` が DEFER を提案）、および最終的な `decision`（例: IntentAlignment による DENY）とその `reason`。これにより「どの静的ルールが発火し、それが意図整合性チェックでどう判断されたか」が事後に追跡できる（R5 のフォレンジック要件）。

## 7. 影響範囲とスモールステップ

この変更は #43・#56 規模の一行修正ではなく、`runtime.py`/`policy_engine.py` の制御フロー変更を伴う。

1. **`policy_engine.py`**: `PolicyEngine` のコンストラクタに `IntentAlignment`（またはそのスタブ）を注入できるようにする。`evaluate()` は常に terminal な `AuthorizationResult` を返す。内部の流れ:
   - **静的ルール評価を、マッチするルールが無くなるまで反復する（収束ループ）**:
     - DENY がマッチ（denied_tools / privilege_scope / ルールの DENY / max_actions など）→ そのまま terminal で返す。
     - MODIFY がマッチ → アクションを変換し（`modified_params` を累積）、変換後のアクションで再評価。
     - マッチするルールが尽きたら、その時点のアクション（累積した a'）を「提案」として次へ。
     - 反復は `max_modify_iterations`（デフォルト 10、カスタマイズ可能）で上限を設け、上限到達時は設定ミス起因の異常として **DENY**（§6「収束ループの規則」参照）。「同じルールの二度発火禁止」は採らない。
   - 収束後の最終 a' に対して `required_params` を判定する。不足があれば、**変換を保持したまま**（`modified_params` を捨てない）DEFER 提案に切り替える。
   - こうして組み立てた「提案」（MODIFY / DEFER / 暗黙 ALLOW など、DENY 以外）を `_confirm_with_ia()` に渡す。IntentAlignment に渡すアクションは、提案の `decision` ではなく **`modified_params` の有無**で決める（あれば a'、なければ a）。
   - IntentAlignment が ALLOW なら提案を確定、それ以外なら上書きする（`proposed_decision` に元の提案 decision を記録）。
   - **terminal にしてよいのは DENY のみ**。required_params 不足のような構文的な DEFER も含め、DENY 以外は必ず IntentAlignment を経由する。
2. **`runtime.py`**: `intercept()` を簡素化。`result = self._policy_engine.evaluate(action, self._accumulator.context, self._environment)` のみになり、`if result is None: ...` および `self._intent_alignment` フィールドは不要になる。IntentAlignment が STEP_UP を返した場合の承認後の最終 `decision`（§6「STEP_UP（modified_params あり）が承認された場合の最終結果」）の扱いを実装する。
3. **`benchmark.py`**: `--mode policy-engine` を、runtime レベルの `_skip_intent_alignment_for_testing` フラグ（env var ゲート付き）ではなく、`PolicyEngine` へスタブ IntentAlignment を注入する形に再定義する。スタブは「常に ALLOW を返す」ことで、静的ルールの「提案」がそのまま確定する（= 現在の `_POLICY_ENGINE_DECISIONS` の挙動を再現）。
4. **回帰ケース追加**:
   - §4 の「意図外 write、パスは危険」（MODIFY→上書きDENY）
   - §4 の「意図外 delete、本番・窓外」（DEFER→上書きDENY）
   - **意図外ツールを required_params 不足で呼ぶ → IntentAlignment が DENY に上書き**（構文的 DEFER も意図確認を通ることの回帰）
   - **MODIFY 変換後の a' が別の DENY ルールにマッチ → 収束ループ内で DENY**（変換後の再評価が効くことの回帰）
   - **振動するルールを設定 → `max_modify_iterations` 到達で DENY**（収束ループの上限が効くことの回帰）
   - シナリオ6・7相当（意図に沿った操作）の結果が変わらないこと（提案確定）
   - STEP_UP 承認後に `decision=MODIFY, resolution_method=human_approved` となるケース
   - レシートに「提案」と「上書き」の両方の情報が記録されること

## 関連

- `laarma_sdk/src/laarma/runtime.py` の `intercept()`
- `laarma_sdk/src/laarma/policy_engine.py` 冒頭の設計注記
- `my_project/policies/policy.yaml` の `unsafe_write_path`、`production_delete_defer`
- `laarma_sdk/src/laarma/deferral.py` の `DeferralResolver`（CRITICAL CRITERIA）
- リスク把握（data_classification 等）の設計判断: [risk-classification.md](risk-classification.md)
- README の仕様準拠状況: R3（意図整合性評価）
