# AARMRuntime 単独使用時の DEFER ハンドリング

[← README に戻る](../README.md)

`AARMToolProxy` を使わず `AARMRuntime.intercept()` を直接呼び出す場合、
DEFER が返ったときの再評価処理は呼び出し側が担う。

```python
from laarma import AARMRuntime, Decision
from laarma.deferral import DeferralResolver

runtime = AARMRuntime(user_intent="...", ...)
result = runtime.intercept("delete_file", {"path": "tmp.txt"})

if result.decision == Decision.DEFER:
    resolver = DeferralResolver()
    resolved = resolver.resolve(result, runtime.context_summary)
    runtime.record_deferred_resolution(resolved)
    result = resolved

# result.decision は ALLOW / MODIFY / DENY / STEP_UP のいずれか
if result.decision == Decision.ALLOW:
    ...  # ツールを実行
elif result.decision == Decision.DENY:
    ...  # ブロック
```

`DeferralResolver.resolve()` は ALLOW / DENY / STEP_UP を返す（DEFER は返さない）。
STEP_UP になった場合は `StepUpResolver` で人間承認フローに進むか、DENY として扱う。

`AARMToolProxy` を使う場合はこのハンドリングが自動化されており、呼び出し側は
`proxy.call()` の戻り値か `ToolBlocked` 例外だけを意識すればよい。
