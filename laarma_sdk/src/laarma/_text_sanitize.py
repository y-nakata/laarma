"""
LLM へ渡すペイロードのテキスト切り詰め・サニタイズ用ヘルパー。

特定の LLM 呼び出し元専用ではなく、DEFER 解決(deferral.py)など複数の呼び出し元から
共有される汎用ヘルパーのため、決定判定ロジックとは独立したモジュールに置く。
"""

from __future__ import annotations

_MAX_INTENT_LEN = 500
_MAX_PARAM_LEN  = 300
_MAX_REASON_LEN = 300


def _truncate(s: str, max_len: int) -> str:
    return s if len(s) <= max_len else s[:max_len] + " …[truncated]"


def _sanitize_params(params: dict) -> dict:
    return {k: (_truncate(v, _MAX_PARAM_LEN) if isinstance(v, str) else v) for k, v in params.items()}


def _sanitize_recent_actions(actions: list) -> list:
    result = []
    for entry in actions:
        if isinstance(entry, dict) and "parameters" in entry:
            entry = {**entry, "parameters": _sanitize_params(entry["parameters"])}
        result.append(entry)
    return result
