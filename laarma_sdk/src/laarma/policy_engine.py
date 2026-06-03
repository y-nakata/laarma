"""
AARM Policy Engine — R3 (静的ルール層)
None を返した場合は Intent Alignment へ。None == ALLOW ではない。
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
        
        # 1. 絶対禁止ツールの判定
        if action.tool_name in p.denied_tools:
            return AuthorizationResult(decision=Decision.DENY,
                reason=f"'{action.tool_name}' はポリシーにより絶対禁止です。", action=action)

        # 2. WRITE_FILE における危険なパスはパラメータを修正して実行
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

        # 3. 本番環境かつメンテナンス時間外における破壊的操作の強制 DEFER トラップ
        if environment and environment.environment == "production":
            if action.tool_name == "delete_file" and not environment.in_maintenance_window():
                return AuthorizationResult(
                    decision=Decision.DEFER,
                    reason="本番環境かつメンテナンス窓外での削除操作のため、追加の実行トレース検証が必要です（一時保留）。",
                    action=action
                )

        # 4. 必須パラメータのチェック
        missing = [k for k in p.required_params.get(action.tool_name, []) if k not in action.parameters]
        if missing:
            return AuthorizationResult(decision=Decision.DEFER,
                reason=f"'{action.tool_name}' に必須パラメータが足りません: {missing}", action=action)
        
        # 5. 最大アクション数の制限
        action_count = sum(1 for e in context.action_history if e.get("type") != "tool_output")
        if action_count >= p.max_actions:
            return AuthorizationResult(decision=Decision.DENY,
                reason=f"アクション数上限 ({p.max_actions}) に達しました。", action=action)
        return None  # 動的評価層（Intent Alignment）へ委譲
