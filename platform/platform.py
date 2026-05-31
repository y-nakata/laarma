"""
platform.py — AARM 組み込み層

AARM SDK を知っているのはこのファイルだけ。
エージェントの外側に立って AARM をセットアップし、proxy 経由でエージェントに注入する。
デモや本番環境から run_scenario() を呼び出す。
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agent"))

from aarm import AARMRuntime, AARMToolProxy, IdentityContext
from agent import run
from tools import IMPLS


def run_scenario(
    title: str,
    user_request: str,
    identity: IdentityContext,
    note: str = "",
) -> None:
    print(f"\n{'='*65}")
    print(f"▶ {title}")
    print(f"  リクエスト: {user_request}")
    if note:
        print(f"  ポイント : {note}")
    print(f"{'-'*65}")

    # AARM のセットアップ — エージェントの外側で行う
    runtime = AARMRuntime(user_intent=user_request, identity=identity)
    proxy   = AARMToolProxy(runtime)
    for name, fn in IMPLS.items():
        proxy.register(name, fn)

    # エージェントには proxy だけ渡す
    run(user_request, proxy)

    # セッションサマリ
    ctx = runtime.context_summary
    sig = ctx.get("derived_signals", {})
    sd  = sig.get("semantic_distance", {})
    print(f"\n  「「「 AARM サマリ 》》》")
    print(f"  総アクション数    : {ctx['action_count']}")
    print(f"  データ分類      : {sig.get('data_classifications', [])}")
    print(f"  セマンティック距離: avg={sd.get('average', '-')} max={sd.get('max', '-')}")
    print(f"  レシート:")
    for r in runtime.receipts:
        print(f"    {r['decision']:7s} | {r['action']['tool_name']:15s} | {r['reason']}")
