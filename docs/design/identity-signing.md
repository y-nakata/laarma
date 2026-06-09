# 設計メモ: アイデンティティ署名と R6 の扱い

[← README に戻る](../../README.md)

> **この文書の位置づけ**: これは**設計検討のメモ**であり、確定した仕様でも実装指示でもない。
> AARM 仕様が明言していること、laarma の現状、そして未確定の設計案を区別して記録する。
> 実装に進む前に、ここの設計案を人間が確定させる必要がある。

## 1. AARM 仕様が明言していること

### R6 本文（論文 §VII-B-6）

システムはアクションを複数レベルのアイデンティティに bind しなければならない（MUST）:

- **Human principal**: エージェントが代理として動く対象のユーザー
- **Service identity**: アクションを実行するサービスアカウント
- **Agent identity**: 特定のエージェントインスタンス
- **Session context**: 関連アクションを結ぶ識別子
- **Role and privilege scope**: 各アイデンティティに紐づく、その時点の権限

要件:
- アイデンティティはアクション送信時に捕捉され、deferred / delegated なアクションでも保持されること
- アイデンティティの主張は trusted source に対して検証されること（**freshness と revocation status** を含む）
- 検証可能なアイデンティティを欠くアクションは **deny または flag** されること
- アイデンティティ情報は tamper-evident なレシートに記録されること

### R5 の署名要件（論文 §VII-B-5）

- セキュアなアルゴリズム（Ed25519 / ECDSA P-256 / RSA-2048 以上）を使う
- レシート内容の正規シリアライゼーションに署名する
- 公開鍵はオフライン検証のために利用可能にする

### 仕様が明言していないこと

- 「個別署名 + 包括署名」という二段構成は**指定されていない**
- 「層ごとに別の鍵で署名せよ」とは**書かれていない**
- non-repudiation をどの主体の鍵でどう実現するかの具体策は実装裁量

## 2. laarma の現状（main）

`IdentityContext`（`models.py`）は4フィールドを持ち、仕様の4層に対応する:

```python
human_principal:  str   # 例: alice@example.com
service_identity: str   # 例: agent-svc@iam
session_id:       str   # 例: sess_demo
privilege_scope:  list[str]
identity_token:   str | None  # sign() で付与される HMAC
```

`sign(secret)` は `_compute_token` を呼び、**4層全体を 1つの HMAC-SHA256 で一括署名**する。鍵は環境変数 `AARM_HMAC_SECRET`。

### 現状の問題点

1. **対称鍵（HMAC）では non-repudiation が成立しない**。署名者と検証者が同じ鍵を共有するため、「誰が署名したか」を区別できない。仕様 R5 は非対称署名を要求している。
2. **主体の混在**。`AARM_HMAC_SECRET` は環境変数（= サーバー/サービスの持ち物）だが、それで human_principal（alice）を含む全層を署名している。「alice が依頼した」ことの証明にはならず、「サービスが alice という値を含む context を作った」ことしか言えない。
3. **freshness / revocation の検証がない**。`verify()` は HMAC 一致を見るだけで、発行時刻の鮮度も失効リスト照合もしない。
4. **identity 欠如時に deny / flag しない**。未署名だと warning を出すだけで処理が流れる。

## 3. 設計案（未確定 — yukinorinkt の設計判断）

> 以下は仕様が指定したものではなく、R6 の non-repudiation 要求と 4層の委任構造から導いた**設計案の一つ**。他の実装もありうる。

### 鍵を持てる主体は3者

4層のうち、秘密鍵を所有できる「主体」は3つ:

| 層 | 主体か | 鍵の例 |
|---|---|---|
| Human principal | ✅ 主体 | ユーザー証明書 |
| Service identity | ✅ 主体 | サーバー証明書 |
| Agent identity | ✅ 主体 | エージェント証明書 / machine ID |
| Role / privilege scope | ❌ 主体ではない（属性） | 鍵を持たない（署名される対象には含まれる） |

### 個別署名 + 包括署名

各主体が自分の identity を個別署名するだけだと、それらがバラバラに存在するだけで「このセットが一つのアクションのために結合された」保証がない（署名の切り貫き攻撃の余地）。そこで:

1. **個別署名**: 各主体（human / service / agent）が自分の秘密鍵で自分の層を署名する。
   - 内側の署名（alice の鍵）= 「私（alice）がこのアクションを依頼した」を証明。alice しか持たない鍵なので否認できない。
2. **包括署名**: 「この3つの identity が一つのアクションのために結合された」ことを、外側の署名で保証する。
   - 包括署名の主体は別主体を立ててもよいが、そうでないなら **Service または Agent** のどちらかが担う。
   - 筆者の見立てでは **Agent** が自然（アクションを起こし receipt を生成する主体が agent instance だから）。

これは現実の委任（delegation）構造を入れ子の署名（例: ネストした JWS、TLS 証明書チェーン）で表す考え方。

### IdentityContext 署名と Receipt 署名は別レイヤー

「receipt が署名されれば IdentityContext は改ざん可能に引き回してよいか」→ **いいえ**。

- receipt の tamper-evidence（`_compute_hash`）は、receipt 生成の**瞬間**に identity を取り込む。だから「receipt 確定後の改ざん」は検知できる。
- しかし **receipt 生成より前**に IdentityContext がメモリ内で改ざんされると、その改ざん後の値で receipt が作られ、ハッシュも改ざん後の値で計算される。検証しても一致してしまい検知できない。
- したがって identity は「アクション送信時に、その主体の鍵で署名」されているべき。receipt 署名は「処理全体の結合と確定の保証」という別レイヤー。
- つまり `IdentityContext.sign` と `AuthorizationResult._compute_hash` を**両方持つこと自体は方向として正しい**。問題は中身（対称鍵で全層一括、主体混在）。

## 4. スモールステップへの分解（実装に進む際の案）

現状から設計案までは距離がある。一気にやらず段階を分ける:

1. **命名・概念の修正**: `sign` が「主体が署名」を示唆するが実態は「システムによる attestation」であることを明確化。
2. **鍵の分離**: receipt の tamper-evidence（システムの鍵）と identity の non-repudiation（各主体の鍵）を分ける。現状は両方とも `AARM_HMAC_SECRET`。
3. **非対称署名化**: HMAC → Ed25519 等。
4. **二段署名化**: 個別署名 + 包括署名。
5. **検証の充実**: freshness / revocation、identity 欠如時の deny/flag。

## 関連

- README の仕様準拠表で R6 を「⚠️ 部分準拠（非対称署名未実装）」としているのは、本メモの問題を指す。
- レシートの tamper-evidence 範囲（deferral 系フィールドがハッシュ対象外）については #45。
