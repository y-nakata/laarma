"""
AARM Distance Calculator — Strategy Pattern for semantic distance.

このモジュールは距離計算ロジックを分離し、Embedding ベースの計算器と
既存のキーワード/Jaccard ベースのフォールバックを切り替え可能にします。
"""

from __future__ import annotations

import math
import os
import re
from abc import ABC, abstractmethod
from typing import Any


def _normalize_text(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z0-9_\.]+", text.lower()) if t]


class DistanceCalculator(ABC):
    def compute(self, user_intent: str, tool_name: str, parameters: dict[str, Any]) -> float:
        """Compute a semantic distance between user intent and a proposed action."""
        return self._compute(user_intent, tool_name, parameters)

    @abstractmethod
    def _compute(self, user_intent: str, tool_name: str, parameters: dict[str, Any]) -> float:
        ...


class KeywordDistanceCalculator(DistanceCalculator):
    def _build_action_tokens(self, tool_name: str, parameters: dict[str, Any]) -> set[str]:
        action_tokens = set(_normalize_text(tool_name.replace("_", " ")))
        for v in parameters.values():
            action_tokens.update(_normalize_text(str(v)))
        return action_tokens

    def _compute(self, user_intent: str, tool_name: str, parameters: dict[str, Any]) -> float:
        intent_lower = user_intent.lower()
        if any(str(v).lower() in intent_lower for v in parameters.values() if v):
            return 0.0
        if tool_name.lower().replace("_", " ") in intent_lower:
            return 0.1

        intent_tokens = set(_normalize_text(user_intent))
        action_tokens = self._build_action_tokens(tool_name, parameters)
        union = len(intent_tokens | action_tokens)
        if union == 0:
            return 0.0
        return round(1.0 - len(intent_tokens & action_tokens) / union, 3)


class EmbeddingDistanceCalculator(DistanceCalculator):
    def __init__(self, model: str | None = None) -> None:
        self._model = model or os.getenv("AARM_EMBEDDING_MODEL", "text-embedding-3-small")
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic()
        return self._client

    def _build_action_text(self, tool_name: str, parameters: dict[str, Any]) -> str:
        values = " ".join(str(v) for v in parameters.values() if v is not None)
        return f"{tool_name.replace('_', ' ')} {values}".strip()

    def _cosine_similarity(self, vector_a: list[float], vector_b: list[float]) -> float:
        dot = 0.0
        norm_a = 0.0
        norm_b = 0.0
        for a, b in zip(vector_a, vector_b):
            dot += a * b
            norm_a += a * a
            norm_b += b * b
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))

    def _compute(self, user_intent: str, tool_name: str, parameters: dict[str, Any]) -> float:
        text_a = user_intent
        text_b = self._build_action_text(tool_name, parameters)

        try:
            client = self._get_client()
            resp = client.embeddings.create(model=self._model, input=[text_a, text_b])
            embeddings = [item.embedding for item in resp.data]
            if len(embeddings) != 2:
                raise ValueError("Embedding response did not contain exactly 2 vectors")
            similarity = self._cosine_similarity(embeddings[0], embeddings[1])
            return round(max(0.0, min(1.0, 1.0 - similarity)), 3)
        except Exception:
            return KeywordDistanceCalculator().compute(user_intent, tool_name, parameters)


def create_default_distance_calculator() -> DistanceCalculator:
    strategy = os.getenv("AARM_DISTANCE_CALCULATOR", "embedding").lower()
    if strategy == "keyword":
        return KeywordDistanceCalculator()
    return EmbeddingDistanceCalculator()
