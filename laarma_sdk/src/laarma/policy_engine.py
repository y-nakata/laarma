"""
AARM Policy Engine — R3 (静的ルール層)
None を返した場合は Intent Alignment へ。None == ALLOW ではない。

【設計上の注意】
本来 AARM の Policy Engine は「何があっても絶対にアウト」なものだけを弾く
最小の静的ゲートであるべきで、MODIFY / DEFER の判断は Intent Alignment の責務。

ただし、この試作では context_accumulator.py の派生シグナル計算（semantic_distance /
confidence_level）がキーワードマッチ + Jaccard 距離という簡易実装にとどまっており、
Intent Alignment への入力シグナルの精度が実用レベルに達していない。
そのため以下の判断を Policy Engine に静的フックとして実装することで
デモの安定動作を確保している:

  - MODIFY: write_file の危険パス検出と書き換え (本来は Intent Alignment の責務)
  - DEFER:  本番・メンテナンス窓外での破壊的操作の保留 (本来は Intent Alignment の責務)

根本的な解決には semantic_distance を文埋め込みモデルで計算するなど、
派生シグナルの精度向上が必要（仕様 Section VIII でもオープンリサーチ課題として言及）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .environment import EnvironmentContext
from .models import Action, AuthorizationResult, Decision, SessionContext


@dataclass
class Policy:
    denied_tools:    set[str]             = field(default_factory=set)
    required_params: dict[str, list[str]] = field(default_factory=dict)
    max_actions:     int                  = 50


DEFAULT_POLICY = Policy(
    denied_tools={"drop_database", "delete_all_records", "exfiltrate_data", "disable_logging"},
    required_params={
        "write_file":  ["path", "content"],
        "delete_file": ["path"],
        "send_email":  ["to", "subject", "body"],
    },
)


class PolicyEngine:
    def __init__(self, policy: Policy | None = None) -> None:
        self._policy = policy or DEFAULT_POLICY

    def evaluate(self, action: Action, context: SessionContext, environment: EnvironmentContext | None = None) -> AuthorizationResult | None:
        p = self._policy

        # 1. 絶対禁止ツールの判定（Policy Engine 本来の責務）
        if action.tool_name in p.denied_tools:
            return AuthorizationResult(decision=Decision.DENY,
                reason=f"'{action.tool_name}' はポリシーにより絶対禁止です。", action=action)

        # 2. [試作上の簡易実装] write_file の危険パスを MODIFY で書き換え
        #    本来は Intent Alignment が環境コンテキストとシグナルを見て判断すべき。
        #    派生シグナル精度が向上すれば Intent Alignment 側に移行する。
        if action.tool_name == "write_file":
            path = str(action.parameters.get("path", ""))
            if path.startswith("/") or ".." in path:
                safe_path = os.path.basename(path) or "safe_output.txt"
                modified_params = dict(action.parameters)
                modified_params["path"] = safe_path
                return AuthorizationResult(
                    decision=Decision.MODIFY,
                    reason=f"危険な書き込み先 '{path}' を安全なパス '{safe_path}' に書き換えました。",
                    action=action,
                    modified_params=modified_params,
                )

        # 3. [試作上の簡易実装] 本番・メンテナンス窓外での破壊的操作を DEFER
        #    本来は Intent Alignment が environment.to_dict() を受け取って判断すべき。
        #    confidence_level の精度が向上すれば Intent Alignment 側に移行する。
        if environment and environment.environment == "production":
            if action.tool_name == "delete_file" and not environment.in_maintenance_window():
                return AuthorizationResult(
                    decision=Decision.DEFER,
                    reason="本番環境かつメンテナンス窓外での削除操作のため、追加の実行トレース検証が必要です（一時保留）。",
                    action=action,
                )

        # 4. 必須パラメータのチェック（Policy Engine 本来の責務）
        missing = [k for k in p.required_params.get(action.tool_name, []) if k not in action.parameters]
        if missing:
            return AuthorizationResult(decision=Decision.DEFER,
                reason=f"'{action.tool_name}' に必須パラメータが足りません: {missing}", action=action)

        # 5. 最大アクション数の制限（Policy Engine 本来の責務）
        action_count = sum(1 for e in context.action_history if e.get("type") != "tool_output")
        if action_count >= p.max_actions:
            return AuthorizationResult(decision=Decision.DENY,
                reason=f"アクション数上限 ({p.max_actions}) に達しました。", action=action)

        return None  # 動的評価層（Intent Alignment）へ委譲
