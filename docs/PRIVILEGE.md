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

## 評価の位置づけ

privilege_scope のチェックは **PolicyEngine（静的ゲート）** で行われる。denied_tools（絶対禁止）と並ぶ、コンテキストを見ずに即座に判定できる静的ルールである。「そのツールを呼ぶ権限がそもそもない」は意図整合性以前の問題なので、LLM 評価（IntentAlignment）に渡る前に弾かれる。

```
アクション要求
  ↓
[PolicyEngine]
  ├─ denied_tools にある？          → DENY
  ├─ privilege_scope にない？         → DENY  ← ここ
  ├─ その他の静的ルールにマッチ？     → DENY / DEFER / MODIFY
  └─ どれにも該当しない              → None（IntentAlignment へ委譲）
```

## 仕様との関係と現状の限界

AARM 仕様 R9（SHOULD）は、just-in-time な資格発行、操作単位のスコープ（例: query は read-only）、資格使用のログ記録を求めている。

laarma の現状は「ツール名の allowlist」としての privilege_scope のみであり、以下は未実装:

- 操作単位のスコープ（同じツールでも read は許可・ write は拒否、など）
- just-in-time な資格発行（アクションごとに最小限の有効期限付き資格を発行）

現状はツール単位の on/off にとどまる。
