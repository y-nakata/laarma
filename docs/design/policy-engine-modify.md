# 設計メモ: PolicyEngine の MODIFY と IntentAlignment（R3）の関係

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは**設計検討のメモ**であり、確定した仕様でも実装指示でもない。
> AARM 仕様が明言していること、laarma の現状、そして未確定の設計案を区別して記録する。
> 実装に進む前に、ここの設計案を人間が確定させる必要がある。
>
> **仕様の典拠について**: AARM の公式仕様は CSA（Cloud Security Alliance）版の System Category Specification v1.0。
> arXiv 論文（2602.09433）は同じ著者によるその解説版で、要件をより詳しく説明している。
> 本メモでは、規範的な典拠として CSA版の要件番号（R3/R4 等）を一次とし、
> 詳しい説明が必要な箇所で論文の該当節を併記する。
>
> **出典・ライセンス**: 本メモが参照・引用・翻訳する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。引用・翻訳は同ライセンスに基づく。

## 1. 発端: PolicyEngine の MODIFY が IntentAlignment を完全に迂回する

`laarma_sdk/src/laarma/runtime.py` の `intercept()` はこうなっている:

```python
result = self._policy_engine.evaluate(action, self._accumulator.context, self._environment)
if result is None:
    result = self._intent_alignment.evaluate(...)
```

**PolicyEngine が `None` 以外（DENY / DEFER / MODIFY）を返すと、IntentAlignment は一切呼ばれない。**

`policy_engine.py` の冒頭には、すでに次の自己言及コメントがある:

> AARM 仕様では MODIFY は (a, C, E) タプルを評価する動的判断である。
> PolicyEngine が MODIFY を返す場合（例: 危険な書き込みパスの basename 変換）は
> AARM 仕様外の実用的妥協である。ドメイン固有の決定論的変換ルールを
> IntentAlignment に混入させず PolicyEngine で完結させることで層の責務を明確化している。

このコメントは「**層の責務分担**」（変換ロジックをどちらの層に置くか）の問題として説明しているが、本メモで扱うのはそれとは別の、**安全性の問題**である。

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

### Table I: Action Classification Framework（論文 §IV-B-5）

論文の分類表を見ると、さらに踏み込んだことが分かる:

| Category | Policy Baseline | Context Evaluation | Runtime Decision |
|---|---|---|---|
| Forbidden | N/A | **Ignored** | DENY |
| Context-Dependent Deny | ALLOW | Misalignment detected | DENY |
| Context-Dependent Allow | DENY | Alignment confirmed | STEP_UP / ALLOW |
| Context-Dependent Defer | ALLOW or DENY | Insufficient or conflicting signals | DEFER |
| Standard Allow | ALLOW | No signals | ALLOW |
| Standard Deny | DENY | No alignment | DENY |

**Context Evaluation が「Ignored」とされているのは Forbidden の1行だけ**。他の全カテゴリは、たとえ最終的な決定が変わらなくても（例: Standard Deny の「No alignment」）、何らかのコンテキスト評価を経ることが前提になっている。そして **MODIFY はこの表のどこにも登場しない**。

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

この式(3)は、**ある1つの a を1回評価して5値のうち1つを返す、1段階のモデル**である点にも注意が必要。ALLOW の「unchanged」も MODIFY の「transformed」も、同じ a を基準にした話であり、評価が複数段階に分かれて a 自体が書き換わっていく、という状況は想定されていない。

## 3. laarma の現状

`my_project/policies/policy.yaml` の MODIFY ルールは現在1つだけ: `unsafe_write_path`。

```yaml
- id: unsafe_write_path
  conditions:
    tool: write_file
    path: "^/|\\.\\."        # 絶対パス or ディレクトリトラバーサル
  decision: MODIFY
  modify_transform: basename  # path を basename(path) に変換
```

`_evaluate_rules` がこの条件にマッチすると、**`AuthorizationResult(decision=MODIFY, ...)` を terminal な結果として返す**。`runtime.intercept` はこれを `None` ではないと判定し、IntentAlignment を呼ばない。

## 4. 具体的な懸念シナリオ

ユーザーの依頼は「README.md を読んで内容を教えて」（意図 = 読み取りのみ）。エージェント（暴走 or 仕込み）が `write_file(path="/etc/cron.d/evil", content="...")` を呼ぶ。

1. `unsafe_write_path` が発火（`path` が `^/` にマッチ）
2. `path` → `basename("/etc/cron.d/evil")` = `"evil"` に変換
3. `MODIFY` を即座に terminal な結果として返す。**IntentAlignment はスキップ**
4. `write_file(path="evil", content="...")` が**実行される**

ここで重要なのは、**もしこのルールが存在しなかったら**という比較である。その場合この呼び出しは `None` → IntentAlignment に渡り、シナリオ4（意図外の delete_file を動的に検知して DENY する）と同じロジックで「意図は read のみなのに write_file が来た」として **DENY されていたはず**。

つまり `unsafe_write_path` ルールは、「危険なパスを安全にする」という安全策のはずが、**「意図外の write をそもそも検知する機会」を奪っている**。ルールが無い方が、まだ安全（意図外として DENY される）。安全策が、既存の防御層（意図外検知）を迂回させてしまう、という逆説的な構造になっている。

## 5. 一般化: DENY/DEFER と MODIFY の非対称性

PolicyEngine が Step 0 で **DENY や DEFER** を確定させるのは、安全側に倒れる。これらは「実行させない/保留する」方向なので、IntentAlignment をスキップしても、最悪「過剰に保守的」になるだけ（IntentAlignment なら ALLOW したかもしれないものを止める）。**危険なアクションを通す方向には倒れない**。

一方 **MODIFY** は「実行させる」方向の決定である。これを Step 0 で確定させると、**IntentAlignment なら DENY/DEFER したはずのアクションが、パラメータの安全化だけを理由に実行されうる**。

R3 の整理（forbidden だけがコンテキスト評価省略を許される、それ以外は何らかのコンテキスト評価を経る）と、この非対称性は整合する。「実行に至らない決定（DENY/DEFER）の即時確定」は forbidden の精神（ハード制限、文脈不要）に近いが、「実行に至る決定（MODIFY）の即時確定」は、forbidden にも他のどのカテゴリにも当てはまらない。

## 6. 設計案（未確定 — yukinorinkt の設計判断）

> 以下は仕様が指定したものではなく、R3（context-dependent actions はコンテキストに対して評価されること）と
> 上記の非対称性から導いた**設計案の一つ**。

### PolicyEngine の MODIFY を非終端にする

`unsafe_write_path` のような MODIFY ルールが発火しても、`_evaluate_rules` は **terminal な `AuthorizationResult` を返さない**。代わりに「変換後のパラメータ」と「発火したルールの `policy_rule_id`」を、継続情報として `runtime.intercept` に渡す。

`runtime.intercept` は、変換後のパラメータを適用した（修正済みの）アクションで **IntentAlignment を呼ぶ**。IntentAlignment は「意図に沿っているか」を、**変換後のアクション**に対して評価する。

最終的な決定は IntentAlignment の判断になる:

- IntentAlignment が ALLOW → 最終決定は **MODIFY**（パラメータ変換 + 意図確認済み）。`modified_params` と `policy_rule_id` は引き続き receipt に記録される
- IntentAlignment が DENY/DEFER/STEP_UP → そちらが最終決定

シナリオ7（意図に沿った要約の書き出し、パスだけ危険）は、変換後のアクション（安全なパスへの write）も意図に沿っているので IntentAlignment も ALLOW し、結果は変わらない。一方、§4 の意図外 write のケースは、パスが安全化されても IntentAlignment が「意図外」として DENY/DEFER できるようになる。

### STEP_UP に modified_params が乗るケースの扱い

上記の設計で、IntentAlignment が変換後のアクションに対して STEP_UP を返すケースがありうる。このとき:

- **`decision` は標準の5値の1つである `STEP_UP` のまま**にする（R4 の決定モデルを拡張しない）
- `modified_params`（PolicyEngine が施した変換）は、**承認者に提示する「完全なアクションコンテキスト」の一部**として receipt に残す。これは R4 の STEP_UP 要件「承認者には完全なアクションコンテキストが利用可能でなければならない」と整合する
- 承認後に実行されるのは変換後（サニタイズ済み）のパラメータであるべき。承認者には「これが承認されれば実際に実行される内容」を見せる

`models.py` の `AuthorizationResult.modified_params` は `decision` と独立したフィールドであり、この扱いを構造的に許容している。

### STEP_UP（modified_params あり）が承認された場合の最終結果: ALLOW か MODIFY か

上記がさらに先送りしていた論点がある。**人間が承認した後、最終的な receipt の `decision` は ALLOW なのか MODIFY なのか。**

#### 仕様は1段階モデル、laarma の設計案は2段階モデル

§2 で見たとおり、R4・式(3)は「ある1つの a を1回評価して5値のうち1つを返す」**1段階モデル**である。この世界では a は1つしかなく、ALLOW の「unchanged」と MODIFY の「transformed」は、同じ a を基準にした話で、両者の間に曖昧さは生じない。

ところが本メモの設計案は **2段階**になっている。

1. PolicyEngine が元のアクション a を a'（変換後）に書き換える
2. IntentAlignment が a' を評価し、STEP_UP を返す
3. 人間が承認 → a' が実行される

ここで「unchanged」「transformed」は、**どちらの a を基準にするかで答えが変わる**。承認者に見せた a'（＝実行されるもの）を基準にすれば「a' がそのまま実行された」→ ALLOW。エージェントが最初に提案した a を基準にすれば「a が a' に変換されて実行された」→ MODIFY。

**仕様の1段階モデルは、この基準点が分岐するケースを想定していない。** ALLOW でも MODIFY でも、どちらを選んでも仕様が明示的に答えを与えているわけではない。**この組み合わせ（複数段階の評価を経て a が書き換わった上での STEP_UP 承認）自体が、仕様が明示的に扱っていない領域である。**

#### STEP_UP の解決先（ALLOW/DENY のみか）について

仕様の STEP_UP 要件（§2）は承認/却下の二値ゲートとしての操作を記述するのみで、「承認された場合に `decision` が何になるか」を明記していない。「STEP_UP は ALLOW/DENY のみに解決される」という想定も、「MODIFY にも解決されうる」という想定も、**どちらも仕様の文言からは導けない**。仕様が MODIFY を STEP_UP の解決先として明示的に排除しているわけではないが、明示的に含めているわけでもない。

#### laarma の選択（未確定）

仕様が空白である以上、**R4 自身の定義（unchanged / transformed）に最も整合する基準点を選ぶ**のが一案である。

R4 の定義における a は、π:(a,C)→{...} の a、すなわち**最初に評価対象になったアクション**と読むのが自然。2段階設計でこれに対応するのは、**エージェントが最初に提案した（変換前の）アクション**である。これを基準にすれば、a' が実行された時点で a と異なる → **最終決定は MODIFY**。

人間が承認した、という事実は `decision` とは別に、`AuthorizationResult.resolution_method`（例: `"human_approved"`）で記録できる。役割分担としては、`decision` =「最終的に何が実行されたか（最初の a と比べて変わったか）」、`resolution_method` =「どう解決されたか（人間の承認を経たか）」、という整理になる。

逆に「ALLOW + modified_params（元と異なる）」を選ぶと、R4 の ALLOW の定義（unchanged）と `modified_params` が non-null であるという事実が、字面上で矛盾する。

**したがって本メモでの暫定的な方向性は、「最終決定は MODIFY、`resolution_method=human_approved` を併記」**とする。ただしこれも仕様が指定したものではなく、**R4 の定義との整合性から導いた laarma の設計選択（仕様外拡張）**であることに変わりはない。

### Step 0（PolicyEngine の terminal 出力）として残るのは DENY と DEFER のみ

§5 の非対称性に基づき、PolicyEngine が IntentAlignment を経ずに terminal な結果を返してよいのは **DENY と DEFER のみ**とする。MODIFY（および将来 ALLOW を静的に返すルールが追加される場合も同様）は、必ず IntentAlignment（または `_skip_intent_alignment_for_testing` 時のスタブ）を経由する。

## 7. 影響範囲とスモールステップ案

この変更は #43・#56 規模の一行修正ではなく、`runtime.py` の制御フロー変更を伴う。

1. **`policy_engine.py`**: MODIFY ルール発火時の戻り値の形を変える。terminal な `AuthorizationResult` ではなく、「変換後パラメータ + `policy_rule_id`」を表す中間データ（例: `(None, modified_params, policy_rule_id)`）を返すようにする。DENY/DEFER は従来どおり terminal。
2. **`runtime.py`**: `intercept()` で、PolicyEngine が「変換後パラメータ」を返した場合、それを適用したアクションで IntentAlignment を呼ぶ。最終結果に `modified_params` と `policy_rule_id` を引き継ぐ（IntentAlignment の reason とは別に、ポリシーが事前変換した事実を残す）。IntentAlignment が STEP_UP を返した場合、承認後の最終 `decision`（§6「STEP_UP（modified_params あり）が承認された場合の最終結果」）の扱いを実装する。
3. **`intent_alignment.py`**: 変換後のアクション（元のアクションではない）を評価する呼び出しになることを確認・調整する。
4. **`benchmark.py`**: `--mode policy-engine`（`_skip_intent_alignment_for_testing=True`）のとき、MODIFY ルールが発火した場合の挙動を定義する。現在 `_POLICY_ENGINE_DECISIONS = {DENY, DEFER, MODIFY}` は MODIFY を「PolicyEngine だけで判定可能」として扱っているが、新設計では MODIFY は IntentAlignment（またはそのスキップスタブ）の結果に依存する。スキップ時は「変換後パラメータで ALLOW」相当として `decision=MODIFY, decision_source=policy_engine` を返す、といった定義が必要。
5. **回帰ケース追加**: §4 のような「意図外 write、パスは危険」のケースを benchmark に追加し、変換後も DENY/DEFER になることを確認する（pipeline モード、LLM 必要）。シナリオ7相当（意図に沿った write）の結果が変わらないことも確認する。STEP_UP 承認後に `decision=MODIFY, resolution_method=human_approved` となるケースの確認も追加する。

## 8. 未検討の関連論点

§2 の Table I を見ると、コンテキスト評価が「Ignored」なのは Forbidden の1行だけで、他の全カテゴリ（Context-Dependent Deny/Allow/Defer、Standard Allow/Deny）は何らかのコンテキスト評価を前提としている。

`policy.yaml` には MODIFY 以外にも、静的ルールで DENY や DEFER を terminal に返すものがある（例: `deny_critical_db_delete_in_prod` のような本番環境での `.db` ファイル削除の即時 DENY、本番・メンテナンス窓外の DEFER）。§5 では「DENY/DEFER の即時確定は安全側に倒れるので問題ない」と整理したが、これは**安全性の観点**であり、**R3 適合性（これらのルールが forbidden に分類できるか、それとも context-dependent として本来コンテキスト評価を要するか）**は別の問題である。

本セッションでは MODIFY に絞って検討した。他の静的 DENY/DEFER ルールが forbidden（ハード制限、文脈不要）として正当化できるか、それとも同様の論点を抱えるかは、**未検討**。別途の検討課題とする。

## 関連

- `laarma_sdk/src/laarma/runtime.py` の `intercept()`
- `laarma_sdk/src/laarma/policy_engine.py` 冒頭の設計注記
- `my_project/policies/policy.yaml` の `unsafe_write_path`
- README の仕様準拠状況: R3（意図整合性評価）は「✅ 準拠」としているが、本メモの問題はその下にある MODIFY 経路の話
