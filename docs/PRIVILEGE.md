# 権限スコープ（privilege_scope）

[← README に戻る](../README.md)

AARM 仕様 R9（最小権限強制、SHOULD）に対応する、laarma の権限スコープの扱いを説明する。

## privilege_scope とは

`IdentityContext.privilege_scope` は、そのアイデンティティが呼び出せるツール名のリストである。

```python
alice = IdentityContext(
    human_principal  = "alice@example.com",
    service_identity = "agent-svc@iam",
    session_id       = "sess_demo",
    privilege_scope  = ["read_file", "write_file", "list_files", "delete_file"],
)
```

この例では alice は4つのツールを呼び出せる。リストにないツールの呼び出しは、PolicyEngine の静的ゲートで DENY される（仕様 R9 の最小権限の考え方）。

## 未設定の場合: fail-closed

`Action.identity` が無い、または `IdentityContext.privilege_scope` が未設定/空リストのとき、PolicyEngine は **DENY** する。

privilege_scope は「この主体はこのツールを呼んでよい」という ALLOW の明示的根拠である。根拠が無い主体を素通しする（= fail-open）のは「暗黙の ALLOW は存在してはならない」という fail-closed の原則および最小権限（Security Objective 7）に反するため、laarma は未設定を「許可の根拠が無い」とみなして DENY する。

## 評価の位置づけ

privilege_scope のチェックは **PolicyEngine（静的ゲート）** で行われる。identity 検証（R6 MUST）・denied_tools（絶対禁止）と並ぶ、コンテキストを見ずに即座に判定できる静的ルールであり、`rules` の priority 解決システムより手前で評価される。

```
アクション要求
  ↓
[PolicyEngine]
  ├─ identity の検証に失敗？          → DENY  ← fail-closed（R6, #55 PR-4）
  ├─ identity/privilege_scope が未設定？ → DENY  ← fail-closed
  ├─ denied_tools にある？          → DENY
  ├─ privilege_scope にない？         → DENY  ← ここ
  ├─ rules（priority 解決）にマッチ？ → ALLOW / DENY / DEFER / MODIFY / STEP_UP
  └─ どれにも該当しない              → baseline ALLOW
```

## 仕様との関係と現状の限界

AARM 仕様 R9（SHOULD）は、just-in-time な資格発行、操作単位のスコープ（例: query は read-only）、資格使用のログ記録を求めている。

laarma の現状は「ツール名の allowlist」としての privilege_scope のみであり、以下は未実装:

- 操作単位のスコープ（同じツールでも read は許可・ write は拒否、など）
- just-in-time な資格発行（アクションごとに最小限の有効期限付き資格を発行）

現状はツール単位の on/off にとどまる。
