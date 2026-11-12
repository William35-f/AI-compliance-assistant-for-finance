"""Cross-encoder rerankers behind a small interface.

A bi-encoder (our embedding model) embeds question and chunk separately and
compares the vectors. A cross-encoder reads question and chunk TOGETHER and
outputs one relevance score. That is more accurate but much slower, so we
only use it to re-order the top ~20 candidates from the first-stage search.
"""

import os
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from regulens.config import get_settings


class Reranker(Protocol):
    name: str

    def score(self, question: str, texts: Sequence[str]) -> list[float]:
        """Relevance score per text (higher = more relevant)."""
        ...


class FastEmbedReranker:
    def __init__(self, model_name: str, cache_dir: str | None = None):
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.name = model_name
        self._model = TextCrossEncoder(model_name, cache_dir=cache_dir)

    def score(self, question: str, texts: Sequence[str]) -> list[float]:
        return [float(s) for s in self._model.rerank(question, list(texts), batch_size=8)]


class KeywordOverlapReranker:
    """Test double: scores by the number of question words found in the text."""

    name = "keyword-overlap"

    def score(self, question: str, texts: Sequence[str]) -> list[float]:
        words = set(question.lower().split())
        return [float(len(words & set(t.lower().split()))) for t in texts]


@lru_cache
def get_reranker() -> Reranker:
    settings = get_settings()
    return FastEmbedReranker(settings.reranker_model, cache_dir=str(settings.model_cache_dir))
