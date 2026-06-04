"""
AARM Distance Calculator — Strategy Pattern for semantic distance.

距離計算ロジックを分離し、Embedding ベースの計算器と
既存のキーワード/Jaccard ベースのフォールバックを切り替え可能にします。

Embedding バックエンド:
  - SentenceTransformerDistanceCalculator: sentence-transformers を使ったローカル実行。
    追加 API キー不要。AARM_EMBEDDING_MODEL 環境変数でモデル切り替え可能。
  - KeywordDistanceCalculator: キーワードマッチ + Jaccard 距離の簡易実装。
    依存ライブラリなし。SentenceTransformer 失敗時のフォールバック。

環境変数:
  AARM_DISTANCE_CALCULATOR: "embedding" (default) | "keyword"
  AARM_EMBEDDING_MODEL: sentence-transformers のモデル名
                        (default: "paraphrase-multilingual-MiniLM-L12-v2")
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any


def _normalize_text(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-zA-Z0-9_\.]+", text.lower()) if t]


class DistanceCalculator(ABC):
    def compute(self, user_intent: str, tool_name: str, parameters: dict[str, Any]) -> float:
        """Compute semantic distance between user intent and proposed action (0.0=close, 1.0=far)."""
        return self._compute(user_intent, tool_name, parameters)

    @abstractmethod
    def _compute(self, user_intent: str, tool_name: str, parameters: dict[str, Any]) -> float:
        ...


class KeywordDistanceCalculator(DistanceCalculator):
    """キーワードマッチ + Jaccard 距離の簡易実装。依存ライブラリ不要。"""

    def _compute(self, user_intent: str, tool_name: str, parameters: dict[str, Any]) -> float:
        intent_lower = user_intent.lower()
        if any(str(v).lower() in intent_lower for v in parameters.values() if v):
            return 0.0
        if tool_name.lower().replace("_", " ") in intent_lower:
            return 0.1
        intent_tokens = set(_normalize_text(user_intent))
        action_tokens = set(_normalize_text(tool_name.replace("_", " ")))
        for v in parameters.values():
            action_tokens.update(_normalize_text(str(v)))
        union = len(intent_tokens | action_tokens)
        return round(1.0 - len(intent_tokens & action_tokens) / union, 3) if union else 0.0


class SentenceTransformerDistanceCalculator(DistanceCalculator):
    """
    sentence-transformers を使ったローカル Embedding ベースの距離計算。
    追加 API キー不要。モデルは初回呼び出し時に自動ダウンロードされる。

    デフォルトモデル: paraphrase-multilingual-MiniLM-L12-v2
      - 多言語対応（日本語を含む）
      - 軽量 (約4MB)
      - KeywordDistanceCalculator より大幅に高精度
    """

    # シングルトン: モデルのロードは高コストなのでインスタンスごとに保持する
    _instances: dict[str, "SentenceTransformerDistanceCalculator"] = {}

    def __new__(cls, model_name: str) -> "SentenceTransformerDistanceCalculator":
        if model_name not in cls._instances:
            instance = super().__new__(cls)
            instance._model_name = model_name
            instance._model = None
            cls._instances[model_name] = instance
        return cls._instances[model_name]

    def _load_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def _build_action_text(self, tool_name: str, parameters: dict[str, Any]) -> str:
        values = " ".join(str(v) for v in parameters.values() if v is not None)
        return f"{tool_name.replace('_', ' ')} {values}".strip()

    def _compute(self, user_intent: str, tool_name: str, parameters: dict[str, Any]) -> float:
        try:
            model = self._load_model()
            action_text = self._build_action_text(tool_name, parameters)
            embeddings = model.encode([user_intent, action_text], convert_to_tensor=False)
            # コサイン類似度を距離に変換
            import numpy as np
            a, b = embeddings[0], embeddings[1]
            similarity = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
            return round(max(0.0, min(1.0, 1.0 - similarity)), 3)
        except Exception:
            # フォールバック: KeywordDistanceCalculator を使う
            return KeywordDistanceCalculator().compute(user_intent, tool_name, parameters)


def create_default_distance_calculator() -> DistanceCalculator:
    """
    環境変数 AARM_DISTANCE_CALCULATOR に基づいて計算器を生成する。
      "embedding" (default): SentenceTransformerDistanceCalculator
      "keyword":             KeywordDistanceCalculator
    """
    strategy   = os.getenv("AARM_DISTANCE_CALCULATOR", "embedding").lower()
    model_name = os.getenv("AARM_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
    if strategy == "keyword":
        return KeywordDistanceCalculator()
    return SentenceTransformerDistanceCalculator(model_name)
