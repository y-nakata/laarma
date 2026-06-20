# 設計メモ: laarma の用語規律 — 認可（access control）の語彙を使わない

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは laarma の**確定した用語規律**を記録する設計メモである。
> 「laarma の評価系をどの語彙で説明するか」という方針の正典。AARM 仕様が使う語彙、
> laarma が避ける語彙、その理由を記録する。コードやドキュメントの文言を書く・直すときの拠り所。
>
> **出典・ライセンス**: 本メモが参照・引用・翻訳する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。引用・翻訳は同ライセンスに基づく。

## 方針（要約）

laarma は AARM = **ランタイムガバナンス**（アクション実行を実行時に制御する層）の実装である。**認可（access control / authorization）の語彙、特に XACML の PDP / PEP / PAP / PIP を用いない。** これらは「主体に資源への権限があるか」を判定する認可システムの用語であり、AARM の評価（意図整合性・DEFER・MODIFY を含む）を取りこぼすため。

ポリシーの記述・読み込みは、平易に「**静的ポリシー定義**（`policy.yaml`）」「ポリシーファイル読み込み機構」と表記する。

## 1. なぜ XACML の語彙（PDP/PEP/PAP）を使わないか

XACML（eXtensible Access Control Markup Language）の PDP（Policy Decision Point）/ PEP（Policy Enforcement Point）/ PAP（Policy Administration Point）/ PIP（Policy Information Point）は、**アクセス制御（認可）** のリファレンスアーキテクチャの用語である。これらが扱うのは「ある主体が、ある資源に対し、ある操作をする権限があるか」という認可判定で、その出力は permit / deny（および NotApplicable / Indeterminate）である。

AARM が行うのはこれではない。AARM の評価は認可を**含むが超える**:

- `denied_tools` や `privilege_scope` のチェックは認可に近い（権限の有無）。
- しかし **意図整合性評価**（IntentAlignment）は、権限があっても意図とずれていれば止める。これは権限判定ではない。
- **DEFER** は権限を判定していない。確信が持てないから保留しているだけで、認可の語彙（permit/deny）には存在しない決定である。
- **MODIFY** はアクションのパラメータを書き換える。これも認可にはない。

AARM の決定が5値（ALLOW / DENY / MODIFY / STEP_UP / DEFER）であること自体が、これが permit/deny の認可ではないことの現れである。したがって、laarma の評価系を「PDP」と呼ぶと、認可を超える部分（AARM を特徴づける部分）が語彙から抜け落ちる。

なお、これらの用語は **AARM 仕様（論文・CSA 版とも）に一度も登場しない**。仕様が使っていない外部フレームワークの語彙を laarma が持ち込むと、仕様とのトレーサビリティも下がる。

## 2. 「万物 PDP 分析病」への戒め

PDP という強力なレンズを持つと、「許可 / 拒否を出すもの」を何でも PDP（認可決定点）に還元したくなる。これを避ける。

laarma の評価系（PolicyEngine の静的ルール、IntentAlignment、DeferralResolver、StepUpResolver）は、いずれも最終的にアクションの可否に関わるが、**判断の根拠・扱う情報・決定論性がそれぞれ異なる**。これらを「permit/deny を出すものはすべて認可（PDP）」とまとめて還元すると、提案/上書きモデルの非対称（DENY のみ terminal、それ以外は提案）、意図整合性が権限判定を超えること、DEFER が「判断の保留」という別カテゴリであること、といった laarma の設計の核が見えなくなる。

「許可 / 拒否がある」ことは「認可である」ことを意味しない。**統制（ランタイムガバナンス）と認可は別**であり、認可は統制の構成要素の一つにすぎない。文言を書くときは、評価系を安易に「認可」「permit/deny」「PDP」に縮約しないこと。

## 3. AARM 仕様が使う語彙（こちらに揃える）

AARM 仕様はコンポーネントを独自の語彙で記述している。laarma の命名・説明はこれに揃える:

- action mediation（アクション仲介）
- context accumulation（コンテキスト蓄積）
- **policy evaluation with intent alignment** / **policy engine**（ポリシーエンジン）
- approval workflows / deferral mechanisms（承認・保留）
- receipt generation（レシート生成）
- telemetry export（テレメトリ）

`PolicyEngine` という名称は、AARM 仕様が "policy engine" という語を使っている（論文 §V Trust Assumptions の Trusted コンポーネント列挙ほか）ため、**仕様準拠であり問題ない**。XACML の PDP とは無関係に、AARM 自身が用いる語である。

ポリシーの保管・記述について、AARM 仕様は "policy store" / "policy authoring process"（論文 §V Trust Assumptions）と平易に呼んでいる。これらも XACML 用語ではなく一般的な表現の系列であり、laarma では同様に平易な「静的ポリシー定義」「ポリシーファイル読み込み機構」と表記する（"policy store" という語を積極採用はしない。容れ物と中身の区別という新たな表現負担を避けるため）。

## 4. 実務上の規律

- ポリシー定義ファイル（`policy.yaml`）とその読み込み（`policy_loader.py`）を「PAP」と呼ばない。「静的ポリシー定義」「ポリシーファイル読み込み機構」と書く。
- SDK 本体や `PolicyEngine` を「PDP」と呼ばない。
- 評価系を説明するとき、「認可」「permit/deny」に縮約せず、AARM の5値の決定（ALLOW / DENY / MODIFY / STEP_UP / DEFER）と、意図整合性・保留を含む統制として記述する。
- `PolicyEngine` の名称は維持する（仕様語彙）。

## 関連

- 提案/上書きモデル（評価系の非対称・5値の決定）: [policy-engine-proposal-override.md](policy-engine-proposal-override.md)
- 静的ポリシー定義の書き方: [../POLICY.md](../POLICY.md)
- `laarma_sdk/src/laarma/policy_loader.py`（ポリシーファイル読み込み機構）
- README の仕様準拠状況（R1–R9 と各コンポーネント）
