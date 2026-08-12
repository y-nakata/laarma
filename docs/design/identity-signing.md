# 設計メモ: アイデンティティ署名と R6 の扱い

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは laarma の**確定した設計方針**を記録する設計メモである。
> AARM 仕様が明言していること、laarma の現状、そして仕様の空白部分に対する laarma の設計判断を、
> それぞれ区別して記録する。本メモの方針は合意済みであり、実装はこの方針に従う。
>
> **仕様の典拠について**: AARM の公式仕様は CSA（Cloud Security Alliance）版の System Category Specification v1.0。
> arXiv 論文（2602.09433）は同じ著者によるその解説版で、要件をより詳しく説明している。
> 本メモでは、規範的な典拠として CSA版の要件番号（R5/R6 等）を一次とし、
> 詳しい説明が必要な箇所で論文の該当節を併記する。
>
> **出典・ライセンス**: 本メモが参照・引用・翻訳する AARM 仕様および論文
> （Autonomous Action Runtime Management, Herman Errico, Cloud Security Alliance, 2026, arXiv:2602.09433）
> は [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) でライセンスされている。引用・翻訳は同ライセンスに基づく。

## 1. AARM 仕様が明言していること

### R6: アイデンティティバインディング（仕様: CSA版 R6 / 解説: 論文 §VII-B-6）

CSA版 R6 は「すべてのアクションレシートはエージェントアイデンティティに暗号的に bind され、その binding は検証可能でアクションを開始したエージェントを一意に識別し、non-repudiation（否認防止）を支えなければならない」と定める（MUST）。

論文 §VII-B-6 はこれをより詳しく、複数レベルのアイデンティティへの bind として展開する:

- **Human principal**: エージェントが代理として動く対象のユーザー
- **Service identity**: アクションを実行するサービスアカウント
- **Agent identity**: 特定のエージェントインスタンス
- **Session context**: 関連アクションを結ぶ識別子
- **Role and privilege scope**: 各アイデンティティに紐づく、その時点の権限

要件:
- アイデンティティはアクション送信時に捕捉され、deferred / delegated なアクションでも保持されること
- アイデンティティの主張は trusted source に対して検証されること（**freshness と revocation status** を含む）
- 検証可能なアイデンティティを欠くアクションは **deny または flag** されること
- アイデンティティ情報は、**監査およびフォレンジックのために**、tamper-evident なレシートに記録されること

### R5 の署名要件（仕様: CSA版 R5 / 解説: 論文 §VII-B-5）

CSA版 R5 は tamper-evident なレシートを MUST とし、改ざんに対して検証可能であることを求める。論文 §VII-B-5 は署名の具体を補足する:

- セキュアなアルゴリズム（Ed25519 / ECDSA P-256 / RSA-2048 以上）を使う
- レシート内容の正規シリアライゼーションに署名する
- 公開鍵はオフライン検証のために利用可能にする

### 仕様が明言していないこと

- 「個別署名 + 包括署名」という二段構成は**指定されていない**
- 「層ごとに別の鍵で署名せよ」とは**書かれていない**
- non-repudiation をどの主体の鍵でどう実現するかの具体策は実装裁量
- 上記3点は、本メモ §3〜§4 で laarma の設計判断として確定する。

## 2. laarma の現状

`IdentityContext`（`models.py`）は §3〜§4 の方針どおり、Human（依頼者）/ Agent（実行者）/
Service（調停者）が各自の Ed25519 秘密鍵で署名する構成を持つ:

```python
human_principal:    str        # 例: alice@example.com
agent_identity:     str        # 例: fs-agent-instance-01
service_identity:   str        # 例: agent-svc@iam
session_id:         str        # 例: sess_demo
privilege_scope:    list[str]
human_signature:    str | None  # sign_human() で付与される Ed25519 署名（hex）
agent_signature:    str | None  # sign_agent() で付与される Ed25519 署名（hex）
service_signature:  str | None  # sign_service() で付与される包括署名（hex）
```

- `sign_human` / `sign_agent` は各主体が自分の層（principal/identity + session_id）のみを署名する個別署名。session_id を含めることで、署名を別セッションへ使い回すリプレイ攻撃を防ぐ。
- `sign_service` は human_principal / agent_identity / service_identity / privilege_scope / session_id を束ねた包括署名（§3「個別署名 + 包括署名」）。
- 検証は `verify_human` / `verify_agent` / `verify_service`。`AARMRuntime` が `AARM_IDENTITY_PUBKEY_DIR`（principal の値をファイル名にした PEM 公開鍵を置くディレクトリ）から鍵を読んで検証する。
- **laarma SDK は秘密鍵を生成・保管しない**（§4「laarma は発行者でなく検証者」）。§4 は Human の鍵について「laarma は alice の秘密鍵を生成・保管してはならない」と定めるが、これは3主体すべてに及ぶ ── Agent の鍵も Service の鍵もデモ側（`my_project`）が生成・保管するものであり、SDK 側にはどの主体の秘密鍵も置かない。SDK は公開鍵での検証のみを担う。鍵生成はデモ側（`my_project/identity_keys.py`、第1段階・CA なし自己生成）が担う。

### 現状の問題点

非対称署名・主体分離は実装済みだが、R6 の要件のうち次が未充足（§5 のステップ5 で扱う）:

1. **freshness / revocation の検証がない**。発行時刻の鮮度も失効リスト照合もしない（第2段階のローカル CA で扱う）。ステップ5b として未着手のまま残る。
2. ~~identity 欠如時に deny / flag しない。~~ **解決済み（PR-4, #55）。** 未署名・公開鍵欠如時は `IdentityContext.verification_error` がセットされ、`PolicyEngine.evaluate()` が `privilege_scope` と同じ fail-closed の gate として DENY する（`decision_source="identity_verification"`）。以前は `warnings.warn()` のみで処理が流れていた。

   **適合性上の留保**: この deny/flag は `AARM_IDENTITY_PUBKEY_DIR`（検証鍵の置き場所）が設定されている場合にのみ働く。未設定のまま（既定構成）だと検証自体が走らず、未署名の identity がそのまま通る。これはオプトインを意図的に維持した設計判断であり（鍵基盤を用意していない環境で全アクションが DENY になる事態を避けるため。#94 系の学習用途に沿う）、実装漏れではない。しかし結果として、「deny/flag は実装済み」は**検証鍵を設定した場合に限り真**であり、既定構成では R6 のこの部分は充足していない。#174 で R3(c) の適用範囲を明示的に限定した（`docs/design/decision-layer-policy-engine.md` §4）のと同種の構図として、ここに明示しておく。

## 3. 設計方針

> 本節は laarma の確定した設計方針である。CSA版 R6 の non-repudiation 要求と 4層の委任構造から導いた。
> 仕様が明示的に規定していない部分（二段署名構成など）については、その旨を都度明記する。

### 鍵を持てる主体は3者

4層のうち、秘密鍵を所有できる「主体」は3つ:

| 層 | 主体か | 鍵の例 |
|---|---|---|
| Human principal | ✅ 主体 | ユーザーの秘密鍵（外部 IdP/CA 発行、またはデモ用自己生成） |
| Service identity | ✅ 主体 | サーバーの秘密鍵 |
| Agent identity | ✅ 主体 | エージェントの秘密鍵 / machine ID |
| Role / privilege scope | ❌ 主体ではない（属性） | 鍵を持たない（署名される対象には含まれる） |

### 役割の整理: 依頼者 / 実行者 / 調停者

3主体は、委任の連鎖における役割が異なる:

- **Human = 依頼者**: アクションを依頼する当事者。
- **Agent = 実行者**: アクションを実際に起こす当事者。
- **Service = 調停者・ブローカー**: Human の依頼を受け、Agent に実行させる、委任の連鎖の結節点。

### 個別署名 + 包括署名

各主体が自分の identity を個別署名するだけだと、それらがバラバラに存在するだけで「このセットが一つのアクションのために結合された」保証がない（署名の切り貼り攻撃の余地）。そこで:

1. **個別署名（当事者）**: 依頼者 Human と実行者 Agent が、それぞれ自分の秘密鍵で自分の層を署名する。
   - Human の署名（alice の鍵）= 「私（alice）がこのアクションを依頼した」を証明。alice しか持たない鍵なので否認できない。
   - Agent の署名（agent の鍵）= 「この agent instance が実行した」を証明。
2. **包括署名（調停者）**: 「Human の依頼・Agent の実行・その時の権限スコープが、一つのアクションのために結合された」ことを、**Service** が自分の鍵で外側から署名して保証する。
   - 包括署名の主体を **Service** とするのは、Service が委任の連鎖の結節点（調停者・ブローカー）だから。「依頼と実行が正しく結合している」ことを保証する立場として、結節点にいる Service が自然。
   - 加えて、AARM の脅威モデルでは agent が動く orchestration 層は untrusted とされる。untrusted 側に近い Agent より、相対的に trusted 側に置かれる Service に全体保証を委ねるほうが、信頼の置き場所として妥当。

> この「個別署名 + 包括署名」の二段構成は仕様が指定したものではなく、4層の委任構造と non-repudiation 要求から laarma が選択した設計である。

### Service 自身の個別署名は不要（包括署名に統合）

Service の層だけは、Human / Agent のように個別署名を別途行う必要はない。

- 包括署名は **Service の鍵**で作られるため、包括署名が成立した時点で「Service がこのアクション全体に関与し、結合を保証した」ことは Service の鍵で証明済み。Service の関与の否認不可性は包括署名に内包される。
- したがって Service の個別署名を別に持つのは冗長（署名2回は実装・性能面でも劣る）。「当事者（Human / Agent）は個別に自己署名し、調停者（Service）は全体を束ねる包括署名で関与を示す」という、役割に署名の形が対応した構造になる。
- **実装上の注意**: Service の関与を担保するため、包括署名の対象に `service_identity` を必ず含めること。これにより、個別署名を省いても service identity が包括署名で保護される。

結果として署名は3つ:「Human 個別署名」「Agent 個別署名」「Service 包括署名（自身の id と role/scope も対象に含む）」。これは現実の委任（delegation）構造を入れ子の署名（例: ネストした JWS、TLS 証明書チェーン）で表す考え方。

### IdentityContext 署名と Receipt 署名は別レイヤー

「receipt が署名されれば IdentityContext は改ざん可能に引き回してよいか」→ **いいえ**。

- receipt の tamper-evidence（`_compute_hash`）は、receipt 生成の**瞬間**に identity を取り込む。だから「receipt 確定後の改ざん」は検知できる。
- しかし **receipt 生成より前**に IdentityContext がメモリ内で改ざんされると、その改ざん後の値で receipt が作られ、ハッシュも改ざん後の値で計算される。検証しても一致してしまい検知できない。
- したがって identity は「アクション送信時に、その主体の鍵で署名」されているべき。receipt 署名は「処理全体の結合と確定の保証」という別レイヤー。
- つまり `IdentityContext.sign` と `AuthorizationResult._compute_hash` を**両方持つこと自体は方向として正しい**。問題は中身（対称鍵で全層一括、主体混在）。

## 4. 鍵の方針（アルゴリズムと出どころ）

> 本節も laarma の確定した設計方針。R5 が許すアルゴリズム集合の中から laarma の既定を定め、
> 各主体の鍵がどこから来るか（特に Human）を明確にする。

### アルゴリズム: 既定は Ed25519

R5 は Ed25519 / ECDSA P-256 / RSA-2048 以上を許す。laarma はこのうち **Ed25519 を既定**とする。

- 鍵・署名が短く（公開鍵32バイト、署名64バイト）、3者分の署名をレシートに載せても肥大しにくい
- 署名・検証が速く、AARM が想定する machine speed の大量アクションに合う
- 決定論的署名のため、ECDSA のような署名ごとの高品質乱数を要求せず、ノンス再利用による鍵漏洩事故を避けられる
- 曲線パラメータが固定で、実装の誤用余地が少ない

ECDSA P-256 / RSA は、既存 PKI（組織の証明書基盤、HSM、WebPKI）との互換が必要になった場合の**検証側サポート**として将来拡張する余地を残す（§4「Human の鍵の出どころ」の第3段階に対応）。laarma が鍵を発行する Service / Agent は Ed25519 で統一する。

### Human の鍵の出どころ: laarma は「発行者」ではなく「検証者」

重要な原則: **laarma は Human（alice）の秘密鍵を生成・保管してはならない**。

- non-repudiation の本質は「秘密鍵をその主体だけが持つ」こと。laarma が alice の秘密鍵に触れた時点で、「サービスが alice になりすませる」ことになり、§2 の「主体の混在」に逆戻りする。
- R6 が「アイデンティティの主張は trusted source に対して検証されること」と定めているのは、まさにこの役割分担を示す。**Human の鍵は外部の trusted source（組織 CA / IdP）が発行し、laarma はそれを検証する**のが本来の姿。

普通の Web アプリは「ログイン後のセッション」を信頼の基盤にし、リクエストごとのユーザー署名や証明書を持たない。AARM が non-repudiation を MUST にするのは、orchestration 層が untrusted で「誰が依頼したか」を暗号的に証明する必要があるという、Web より一段強い要求から来ている。この違いが「ユーザー証明書」という、通常の Web 開発では馴染みのない概念を要求する理由である。

現実の Human 鍵の発行元（laarma 外部）の例: 組織の PKI / AD 証明書サービスが発行するクライアント証明書、Okta / Entra ID / Google Workspace などの IdP が発行する短命証明書やトークン、Vault / Teleport が発行する短命 SSH 証明書、YubiKey / FIDO2 / Passkey などのハードウェアトークン（秘密鍵がデバイス内に閉じる）。いずれも laarma は検証側に回る。

### laarma プロトタイプの段階設計

現実の証明書発行は laarma の外側の重いインフラであり、プロトタイプに丸ごと持ち込むのは非現実的。以下の段階で扱う:

- **第1段階（既定・現プロトタイプの範囲）**: デモ用に、各主体の Ed25519 鍵ペアを laarma（またはデモスクリプト）が生成する。CA は無し（自己署名相当）。現実の信頼チェーンは無いが、**「alice の鍵で署名し alice の公開鍵で検証する」という主体分離の構造はデモで再現する**。これにより §2 の「主体の混在」は解消される。3者とも Ed25519。
- **第2段階（オプション）**: デモ用の簡易ローカル CA（自前ルート鍵）で各主体にクライアント証明書を発行し、証明書チェーン検証・失効リスト（CRL）照合をミニチュアで実装・デモする。R6 の freshness / revocation 検証の学習用。`cryptography` ライブラリ等で実装可能。
- **第3段階（将来拡張・本メモのスコープ外）**: 外部 IdP（OIDC / SSO）や SPIFFE/SPIRE と統合する実運用形態。ここで初めて Human 鍵が外部発行（P-256 / RSA など）になり、laarma の検証側に複数アルゴリズムのサポートが必要になる。論文 Architecture D（Vendor Integration）的な世界。

### 鍵ファイルの取り扱い（リポジトリ衛生）

- デモ用に生成する秘密鍵・鍵ペアは**リポジトリに一切コミットしない**。`.gitignore` に `*.key` / `*.pem` / `keys/` を追加済み。
- 鍵は `keys/` ディレクトリ配下に置く運用とし、`keys/` ごと無視する。デモ用の公開鍵（`alice.pub` 等）も、秘密鍵とまとめて `keys/` に置いて無視する（公開鍵自体は本来コミット可能だが、デモ鍵をリポジトリに残さない方針を優先）。
- これは `.env`（`AARM_RECEIPT_SECRET` 等）を gitignore する既存方針と同じ、公開リポジトリの秘密情報衛生の一環。

## 5. スモールステップへの分解

現状から設計方針までは距離があるため、Issue #55 で以下のステップ（PR-1a 〜 PR-5）に分けて実施する。各ステップ名は当 Issue 内での呼称。

1. ✅ **命名・概念の修正**（PR-1a, #80）: `sign` が「主体が署名」を示唆するが実態は「システムによる attestation」であることを明確化。
2. ✅ **鍵の分離**（PR-1b, #83）: receipt の tamper-evidence（システムの鍵）と identity の non-repudiation（各主体の鍵）を分ける。
3. ✅ **非対称署名化**（PR-2, #86）: HMAC → Ed25519（§4 の通り、3主体とも Ed25519。プロトタイプ第1段階では Human も自己生成）。
4. ✅ **二段署名化**（PR-2, #86 に統合実施）: 当事者（Human / Agent）の個別署名 + 調停者（Service）の包括署名。
5. **検証の充実**:
   - ✅ **5a. identity 欠如/検証失敗時の deny/flag**（PR-4, #55）: 実装済み。
   - **5b. freshness / revocation**（第2段階のローカル CA で CRL 照合をデモ、オプション）: 未着手。

## 関連

- README の仕様準拠表の R6 は、本メモ §3〜§4 の非対称署名・主体分離に加え、ステップ5a（identity 欠如/検証失敗時の deny/flag）が実装された旨を反映する（freshness/revocation〔ステップ5b〕は未着手のため、まだ「✅ 準拠」への変更はしない）。
- レシートの tamper-evidence 範囲（deferral 系フィールドがハッシュ対象外）については #45。
