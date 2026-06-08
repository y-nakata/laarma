# PAP（Policy Administration Point）

[← README に戻る](../README.md)

静的ポリシーは `my_project/policies/policy.yaml` で定義します。PAP はポリシーの定義・管理を担うコンポーネントであり、SDK 本体（PDP）とは分離して置かれます。`load_policy()` でファイルを読み込み SDK に注入します。

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
