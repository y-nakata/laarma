"""
AARM Policy Engine

【役割】静的ルールで「確実にアウト」なアクションだけを弾く最初の関門。
       ここで判断できないものはすべて Intent Alignment (Claude) に委ねる。

【重要】Policy Engine は AARM の一部に過ぎない。
       静的ルールを通過しても Intent Alignment が DENY することがある。
       逆に step_up_tools に入っていないツールでも、
       コンテキストによって Intent Alignment が STEP_UP / DENY にすることがある。
       "静的ルールに引っかからなければ ALLOW" ではない。

評価順序:
  1. 禁止リスト          (DENY   : 何があっても実行しない)
  2. 要確認パラメータ    (DEFER  : 情報不足で判断できない)
  3. アクション数上限    (DENY   : セッション暴走の防止)
  4. None を返す         (→ Intent Alignment へ)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import Action, AuthorizationResult, Decision, SessionContext


# ---------------------------------------------------------------------------
# ポリシー定義
# ---------------------------------------------------------------------------

@dataclass
class Policy:
    """
    AARM 静的ポリシーの設定。
    "確実にアウト" なものだけをここに書く。
    グレーゾーンは Intent Alignment に任せる。

    Attributes:
        denied_tools:    何があっても実行しない絶対禁止ツール
        required_params: ツール実行に必須なパラメータ (欠如で DEFER)
        max_actions:     セッションあたりの最大アクション数
    """
    denied_tools:    set[str]             = field(default_factory=set)
    required_params: dict[str, list[str]] = field(default_factory=dict)
    max_actions:     int                  = 50


DEFAULT_POLICY = Policy(
    denied_tools={
        # 不可逆かつ正当な理由が存在しない操作のみ絶対禁止
        "drop_database",
        "delete_all_records",
        "exfiltrate_data",
        "disable_logging",
    },
    required_params={
        "write_file":  ["path", "content"],
        "delete_file": ["path"],
        "send_email":  ["to", "subject", "body"],
    },
    max_actions=50,
)


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """
    静的ポリシーでアクションを評価する。

    None を返した場合は「静的ルールでは判断不能」を意味し、
    呼び出し元 (AARMRuntime) が Intent Alignment に委ねる。
    None == ALLOW ではない。
    """

    def __init__(self, policy: Policy | None = None) -> None:
        self._policy = policy or DEFAULT_POLICY

    def evaluate(
        self,
        action: Action,
        context: SessionContext,
    ) -> AuthorizationResult | None:
        """
        静的ポリシーで評価する。

        Returns:
            引っかかった場合は AuthorizationResult。
            引っかからない場合は None → Intent Alignment へ。
        """
        p    = self._policy
        tool = action.tool_name

        # 1. 絶対禁止ツール
        if tool in p.denied_tools:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"'{tool}' はポリシーにより絶対禁止です。",
                action=action,
            )

        # 2. 必須パラメータの欠如
        missing = [k for k in p.required_params.get(tool, []) if k not in action.parameters]
        if missing:
            return AuthorizationResult(
                decision=Decision.DEFER,
                reason=f"'{tool}' に必須なパラメータが足りません: {missing}",
                action=action,
            )

        # 3. アクション数上限
        action_count = sum(
            1 for e in context.action_history if e.get("type") != "tool_output"
        )
        if action_count >= p.max_actions:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason=f"セッションのアクション数が上限 ({p.max_actions}) に達しました。",
                action=action,
            )

        # 静的ルールでは判断不能 → Intent Alignment へ委ねる
        # (None == ALLOW ではない)
        return None
