"""
AARM Intent Alignment — R3 (動的評価層)

Policy Engine が None を返したアクションを (a, C, E) タプルで評価する。
  a: アクション
  C: セッションコンテキスト (派生シグナル含む)
  E: 環境コンテキスト (メンテナンス窓・環境種別など)

Policy Engine には deterministic な安全ゲートを移し、Intent Alignment は主に
曖昧さや意図整合性を LLM で解消する役割を担います。
"""

from __future__ import annotations

import json
import os
import re
from typing import TYPE_CHECKING

from .models import Action, AuthorizationResult, Decision

if TYPE_CHECKING:
    from .environment import EnvironmentContext


SYSTEM_PROMPT = """\
You are an AARM (Autonomous Action Runtime Management) intent alignment evaluator.
Your role is to evaluate whether an AI agent's proposed action should proceed,
based on the user's original intent, accumulated session context, and environment context.

You receive a JSON object containing:
- user_intent       : the user's original request establishing the baseline intent
- action_count      : total number of prior actions in this session
- recent_actions    : prior actions executed in this session
- derived_signals   : signals computed from the session:
    - data_classifications    : sensitivity levels of data accessed (PUBLIC/PII/CONFIDENTIAL/SENSITIVE_TOOL)
    - semantic_distance       : drift from user intent (current/average/max; 0.0=aligned, 1.0=completely unrelated)
    - scope_expansion_detected: agent accessed resources outside expected scope
    - entity_set              : resources referenced in this session
    - confidence_level        : system's confidence in evaluating this action (0.0-1.0)
- environment       : the infrastructure runtime context (type, maintenance window state)
- proposed_action   : the action about to be executed

Respond ONLY with a raw JSON object (no markdown, no explanations outside JSON):
{"decision": "ALLOW"|"DENY"|"DEFER"|"STEP_UP"|"MODIFY", "reason": "<one concise sentence in Japanese>", "modified_params": { ... }}

If you choose MODIFY, include a sanitized `modified_params` object containing the parameters that should be used for execution.

## Decision Criteria

### 1. DENY
You MUST return DENY immediately if there is active danger, hijack, or structural misalignment, regardless of environmental factors:
- The proposed action contradicts, exceeds, or has no correlation with the user's stated intent (e.g., user asks to read, agent attempts to write/delete).
- semantic_distance is high (> 0.4) or scope_expansion_detected is true, and there is no clear justification in the user_intent.
- Compositional Risk: Individual actions are safe, but in this exact sequence, they constitute an attack vector (e.g., reading sensitive files and immediately attempting to write or send them somewhere).

### 2. DEFER
Use DEFER when the action is potentially valid or aligned with the user's intent, BUT the current operational context lacks sufficient assurance to prove it is safe to execute automatically:
- The action may be allowed, but the evidence is insufficient to decide it can proceed without further context.
- Use the provided action_count and derived confidence_level to determine whether the current session has enough prior context.
- If the user's request is highly ambiguous, conflicting, or lacking sufficient context, prefer DEFER.
- confidence_level is low (< 0.4) and more runtime context/history might resolve the ambiguity.

### 3. STEP_UP
Use STEP_UP when the action is confirmed to be fully aligned with user intent and has high confidence, but organizational policy strictly requires a manual human confirmation gate:
- High-impact or destructive operations executed in production, even if fully aligned with user intent, when there is sufficient action history or context to distinguish them from ambiguous or insufficiently supported requests.
- Use STEP_UP only when the proposed action is aligned with intent, confidence is sufficient, and the risk is high enough that a manual human gate is still required.
- confidence_level is marginal (0.4 - 0.6) but the action itself is valid and requires human confirmation to clear the risk.

### 4. MODIFY
Use MODIFY when the proposed action is aligned with user intent but the tool parameters need to be sanitized, restricted, or adjusted before execution:
- The requested action is allowed in principle, but some parameters are too broad, sensitive, or unsafe as-is.
- If the requested path is absolute, contains '..', or points outside a safe workspace scope, rewrite it to a safe, workspace-relative filename.
- Do not return an absolute path, a parent-directory reference, or a path outside the current workspace.
- The action can still proceed safely after rewriting parameters to a safer or narrower form.
- Provide `modified_params` only when you are confident in the safer parameter values to execute.

### 5. ALLOW
Use ALLOW ONLY when you have high confidence (confidence_level >= 0.6), semantic alignment is clear, and there are no outstanding policy or environmental boundary violations.

## Prioritization Rule
When deciding between DENY, DEFER, and STEP_UP for destructive operations:
- If there is ANY indication of intent divergence (the user did NOT explicitly request or imply this deletion/destruction): Choose DENY.
- If the user explicitly requested the deletion, but the environmental constraint (production, outside maintenance) makes it highly risky and you lack context: Choose DEFER (this triggers the DeferralResolver to gather traces).
- If the user explicitly requested the deletion, and the context is clear but the risk remains high due to environment/PII: Choose STEP_UP.
"""


class IntentAlignment:
    def __init__(
        self,
        model: str | None = None,
        enable_confidence_deferral: bool = True,
    ) -> None:
        self._model  = model or os.getenv("AARM_MODEL", "claude-sonnet-4-6")
        self._client = None
        self._enable_confidence_deferral = enable_confidence_deferral

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def evaluate(
        self,
        action: Action,
        context_summary: dict,
        environment: "EnvironmentContext | None" = None,
    ) -> AuthorizationResult:
        """
        (a, C, E) タプルでアクションを評価する。

        事前確信度チェック:
          confidence_level < 0.4 の場合は Claude を呼ぶ前に DEFER を返す。
          (AARM 仕様の「情報不十分な場合は一時保留」ヒューリスティック)
        """
        signals = context_summary.get("derived_signals", {})
        confidence = signals.get("confidence_level", 1.0)
        semantic_distance = signals.get("semantic_distance", {}).get("current", 0.0)
        scope_expansion = signals.get("scope_expansion_detected", False)

        # 1. PolicyEngine が deterministic な安全ゲートを先行処理しているため、
        #    ここでは主に曖昧さや整合性の判断を行う。
        # 2. 低確信度時は、明示的な安全判断ができないため DEFER を返す。
        #    これは AARM 仕様の「コンテキスト不十分による一時保留」に対応するヒューリスティックです。
        if self._enable_confidence_deferral and confidence < 0.4:
            return AuthorizationResult(
                decision=Decision.DEFER,
                reason=f"評価の確信度が不十分です (confidence={confidence})。追加コンテキストが必要です。",
                action=action,
            )

        # 4. 意味的距離とスコープ拡張が高い場合は DENY
        if scope_expansion and semantic_distance > 0.4:
            return AuthorizationResult(
                decision=Decision.DENY,
                reason="意図から大きく逸脱し、想定外の範囲拡張が検知されました。",
                action=action,
            )

        try:
            payload = {
                "user_intent":     context_summary.get("user_intent", ""),
                "action_count":    context_summary.get("action_count", 0),
                "recent_actions":  context_summary.get("recent_actions", []),
                "derived_signals": signals,
                "environment":     environment.to_dict() if environment else {
                    "environment": "unknown",
                    "in_maintenance_window": None,
                    "maintenance_windows": [],
                    "high_sensitivity": False,
                },
                "proposed_action": {
                    "tool_name":  action.tool_name,
                    "parameters": action.parameters,
                },
            }
            resp = self._get_client().messages.create(
                model=self._model, max_tokens=256, system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)}],
            )
            text_parts = [b.text for b in resp.content if hasattr(b, "text") and b.text]
            raw_text = "\n".join(text_parts).strip()
            if not raw_text:
                raise ValueError(f"No text content in response. stop_reason={resp.stop_reason}")
            fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.S)
            if fence:
                raw_text = fence.group(1)
            parsed          = json.loads(raw_text)
            decision        = Decision(parsed["decision"])
            reason          = parsed.get("reason", "(reason not provided)")
            modified_params = parsed.get("modified_params")
        except Exception as e:
            decision, reason, modified_params = Decision.DEFER, f"意図整合性評価中にエラー: {e}", None
        return AuthorizationResult(
            decision=decision,
            reason=reason,
            action=action,
            modified_params=modified_params,
        )
