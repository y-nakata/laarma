# 静的ポリシー定義（policy.yaml）

[← README に戻る](../README.md)

静的ポリシーは `my_project/policies/policy.yaml` で定義します。ポリシー定義は SDK 本体とは分離して置かれ、プロジェクト側（`my_project/policies/`）で管理します。`load_policy()` でファイルを読み込み SDK に注入します。

```python
from laarma import AARMRuntime, load_policy

policy = load_policy("my_project/policies/policy.yaml")
runtime = AARMRuntime(user_intent=..., policy=policy, transform_registry=...)
```

`policy.yaml` の主要キー:

| キー | 説明 |
|-----|------|
| `denied_tools` | 絶対禁止ツール。呼び出されると即 DENY |
| `required_params` | ツールごとの必須パラメータ。不足時は DEFER |
| `max_actions` | セッション内の最大アクション数。超過時は DENY |
| `rules` | 追加の静的ルール（DENY / DEFER / MODIFY）。条件にマッチした最初のルールを適用 |

`rules` の各エントリは `conditions`（ツール名・環境・パラメータ正規表現）と `decision` を持ちます。`MODIFY` ルールはさらに `modify_transform` でパラメータ変換を指定できます（変換関数は `transform_registry` として呼び出し側が提供）。
