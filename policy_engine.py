"""
AARM Policy Engine

静的ポリシーに基づいてアクションを評価する。
AARM 仕様の "evaluates against static policy" 要件に対応。

評価順序:
  1. 禁止リスト (DENY)
  2. 要承認リスト (STEP_UP)
  3. 要確認パラメータ (DEFER)
  4. レート制限 (DENY)
  5. 上記に引っかからなければ ALLOW
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .models import Action, AuthorizationResult, Decision, SessionContext


# ---------------------------------------------------------------------------
# ポリシー定義
# ---------------------------------------------------------------------------

@dataclass
class Policy:
    """
    AARM 静的ポリシーの設定。

    Attributes:
        denied_tools:       実行を完全に禁止するツール名のセット
        step_up_tools:      必ず人間承認を要求するツール名のセット
        required_params:    特定ツールに必須なパラメータキー (なければ DEFER)
        max_actions:        セッションあたりの最大アクション数 (DENY)
    """
    denied_tools:    set[str]              = field(default_factory=set)
    step_up_tools:   set[str]              = field(default_factory=set)
    required_params: dict[str, list[str]]  = field(default_factory=dict)
    max_actions:     int                   = 50


DEFAULT_POLICY = Policy(
    denied_tools={
        "drop_database",
        "delete_all_records",
        "exfiltrate_data",
        "disable_logging",
    },
    step_up_tools={
        "send_email",
        "deploy_to_production",
        "delete_file",
        "execute_shell",
    },
    required_params={
        "write_file":   ["path", "content"],
        "delete_file":  ["path"],
        "send_email":   ["to", "subject", "body"],
    },
    max_actions=50,
)


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    静的ポリシーを基にアクションの安全性を評価する。
    インスタンス生成時に Policy を注入するか、デフォルトの DEFAULT_POLICY を使用する。
    """

    def __init__(self, policy: Policy | None = None) -> None:
        self._policy = policy or DEFAULT_POLICY

    def evaluate(
        self,
        action: Action,
        context: SessionContext,
    ) -> AuthorizationResult | None:
        """
        アクションを静的ポリシーで評価する。

        Returns:
            ポリシーに引っかかった場合は AuthorizationResult、
            引っかからない場合は None (次の評価ステップへ)。
        """
        p = self._policy
        tool = action.tool_name
        params = action.parameters

        # 1. 禁止ツール
        if tool in p.denied_tools:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"'{tool}' はポリシーにより禁止されています。",
                action=action,
            )

        # 2. 人間承認必須ツール
        if tool in p.step_up_tools:
            return AuthorizationResult(
                decision=Decision.STEP_UP,
                reason=f"'{tool}' は人間の承認が必要です。",
                action=action,
            )

        # 3. 必須パラメータの欠如
        required = p.required_params.get(tool, [])
        missing = [k for k in required if k not in params]
        if missing:
            return AuthorizationResult(
                decision=Decision.DEFER,
                reason=f"'{tool}' に必須なパラメータが足りません: {missing}",
                action=action,
            )

        # 4. アクション数上限
        action_count = sum(
            1 for e in context.action_history
            if e.get("type") != "tool_output"
        )
        if action_count >= p.max_actions:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"セッションのアクション数が上限 ({p.max_actions}) に達しました。",
                action=action,
            )

        # すべてのチェックをパス → 次の評価ステップに委ねる
        return None
