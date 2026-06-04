"""
AARM Policy Engine — R3 (静的ルール層)
None を返した場合は Intent Alignment へ。None == ALLOW ではない。

Policy Engine は「何があっても絶対にアウト」なものだけを弾く
最小の静的ゲートとして振る舞います。

このプロトタイプでは、距離計算を埋め込みベースの `DistanceCalculator` に移行し、
`IntentAlignment` が `MODIFY` / `DEFER` の判断を直接扱えるように設計されています。
そのため `PolicyEngine` は現在、以下の責務に絞られています:

  - DENY: 絶対禁止ツールのブロック
  - DEFER: 必須パラメータ不足の一時保留
  - その他: アクション数上限の制御

`IntentAlignment` が信頼できる派生シグナルを受け取れるようになれば、
この静的ゲートワークフローはより仕様に近い形になります。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .environment import EnvironmentContext
from .models import Action, AuthorizationResult, Decision, SessionContext


def _is_unsafe_write_path(action: Action) -> bool:
    path = action.parameters.get("path")
    return (
        action.tool_name == "write_file"
        and isinstance(path, str)
        and (path.startswith("/") or ".." in path)
    )


def _safe_write_path(path: str) -> str:
    return os.path.basename(path) or "safe_output.txt"


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

        # 2. 静的安全ゲート: 明らかに危険な書き込み先は PolicyEngine で MODIFY
        if _is_unsafe_write_path(action):
            path = str(action.parameters.get("path", ""))
            safe_path = _safe_write_path(path)
            modified_params = dict(action.parameters)
            modified_params["path"] = safe_path
            return AuthorizationResult(
                decision=Decision.MODIFY,
                reason=f"危険な書き込み先 '{path}' を安全なパス '{safe_path}' に書き換えました。",
                action=action,
                modified_params=modified_params,
            )

        # 3. 静的安全ゲート: 本番環境かつメンテナンス窓外の削除は DEFER
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
