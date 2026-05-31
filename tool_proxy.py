"""
AARM ToolProxy  ―  SDK Instrumentation アーキテクチャの実装

「SDK Instrumentation」とは:
  エージェントのコードに直接変更を加えることなく、
  エージェントとツール実装の「間」に AARM を挿入する方式。
  AARM 仕様 Section VI-B に対応。

透過性:
  エージェントは proxy.call(tool_name, params) を呼ぶだけ。
  AARM が存在することを知らない。import もしない。なにもしない。

  これが「SDK 方式」の意味:
    - エージェントのコードは変更しない
    - AARM のセットアップはエージェントの外側 (demo.py) で行う
    - エージェントから見ると proxy.call() は「失敗することがあるツール」に見えるだけ

フロー:
  エージェント
    ↓ proxy.call(tool_name, params)
  AARMToolProxy                        ← エージェントはここの存在を知らない
    ↓ runtime.intercept()
  AARMRuntime
    ↓ policy_engine.evaluate()         ← 静的ルールで「確実にアウト」なものだけ強制割り
    ↓ None の場合
  IntentAlignment                      ← コンテキスト全体を見て Claude が動的判断
    ↓ ALLOW / DENY / DEFER / STEP_UP
  実ツール実装 or ToolBlocked 例外
    ↓
  エージェント (成功 or エラーとして認識するだけ)
"""

from __future__ import annotations

from typing import Any, Callable

from .models import Decision
from .runtime import AARMRuntime


class ToolBlocked(Exception):
    """AARM がツール実行をブロックしたときに送出される例外。
    エージェントには「ツールが失敗した」としてだけ伝わる。"""

    def __init__(self, decision: Decision, reason: str) -> None:
        self.decision = decision
        self.reason   = reason
        super().__init__(f"[AARM {decision.value}] {reason}")


class AARMToolProxy:
    """
    SDK Instrumentation 方式の AARM 透過インターセプトレイヤー。

    エージェントから見ると「ただのツール実行窓口」だが、
    内部では AARM Runtime を通じてすべてのアクションをインターセプトする。
    エージェントは AARM の import もインスタンス生成も一切行わない。
    """

    def __init__(self, runtime: AARMRuntime) -> None:
        # runtime はエージェントの外側で初期化され、プロキシ経由で注入される
        self._runtime = runtime
        self._tools: dict[str, Callable[[dict], Any]] = {}

    def register(self, tool_name: str, fn: Callable[[dict], Any]) -> None:
        """ツール名と実装関数を登録する。"""
        self._tools[tool_name] = fn

    def call(self, tool_name: str, params: dict[str, Any]) -> str:
        """
        [エージェントから呼ばれる唯一のメソッド]

        エージェントはこれを「ツール実行関数」として呼ぶだけ。
        内部で AARM が透過的にインターセプトし、
        - ALLOW  : 実ツール関数を実行して結果を返す
        - それ以外: ToolBlocked 例外 (エージェントにはただのエラー)
        """
        # ▼ ここが SDK Instrumentation の核心 ―
        #   エージェントのコードを一行も変えずに AARM が割り込む
        result = self._runtime.intercept(tool_name, params)

        if result.decision == Decision.ALLOW:
            fn = self._tools.get(tool_name)
            if fn is None:
                raise KeyError(f"ツール '{tool_name}' が登録されていません。")
            output = fn(params)
            self._runtime.record_tool_output(result.action.action_id, output)
            return output

        # DENY / STEP_UP / DEFER はすべて ToolBlocked として伝播
        # エージェントには「ツールが失敗した」としか見えない
        raise ToolBlocked(result.decision, result.reason)
