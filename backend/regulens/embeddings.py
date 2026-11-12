"""Text embedders behind one small interface.

The real embedder runs a local ONNX model through `fastembed`: no API key,
no rate limits, no cost, and the same model embeds documents at ingest time
and questions at query time (they MUST match, or similarities are meaningless).

Why nomic-embed-text-v1.5 (quantised)? It accepts up to 8192 tokens, so our
500-800 token chunks are embedded whole. Popular small models such as
bge-small silently cut input at 512 tokens. The quantised version is only
~130 MB, which matters later when we deploy to a small free-tier server.
"""

import hashlib
import math
import os
import re
from collections.abc import Sequence
from functools import lru_cache
from typing import Protocol

from regulens.config import get_settings

# Some models were trained with task prefixes and work noticeably worse without them.
_PREFIXES: dict[str, tuple[str, str]] = {
    # model name: (document prefix, query prefix)
    "nomic-ai/nomic-embed-text-v1.5": ("search_document: ", "search_query: "),
    "nomic-ai/nomic-embed-text-v1.5-Q": ("search_document: ", "search_query: "),
    "BAAI/bge-small-en-v1.5": ("", "Represent this sentence for searching relevant passages: "),
    "BAAI/bge-base-en-v1.5": ("", "Represent this sentence for searching relevant passages: "),
}


class Embedder(Protocol):
    name: str
    dim: int

    def count_tokens(self, text: str) -> int: ...
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedEmbedder:
    """Local embedding model run with fastembed (ONNX Runtime, CPU)."""

    def __init__(self, model_name: str, cache_dir: str | None = None, batch_size: int = 8):
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        from fastembed import TextEmbedding  # imported here: slow import, not needed in tests

        self.name = model_name
        self._model = TextEmbedding(model_name, cache_dir=cache_dir)
        self._doc_prefix, self._query_prefix = _PREFIXES.get(model_name, ("", ""))
        self._batch_size = batch_size
        # fastembed exposes the Hugging Face tokenizer it uses; we reuse it so
        # chunk sizes are measured in the model's own tokens.
        self._tokenizer = self._model.model.tokenizer
        self.dim = len(self.embed_query("dimension probe"))

    def count_tokens(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = [self._doc_prefix + t for t in texts]
        return [v.tolist() for v in self._model.embed(inputs, batch_size=self._batch_size)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.embed([self._query_prefix + text]))).tolist()


class HashingEmbedder:
    """Tiny deterministic embedder for tests: hashed bag of words, L2-normalised.

    Texts that share words get similar vectors, which is enough to test the
    plumbing (storage, search, idempotency) without downloading a model.
    """

    def __init__(self, dim: int = 64):
        self.name = f"hashing-{dim}"
        self.dim = dim

    def count_tokens(self, text: str) -> int:
        return len(re.findall(r"\w+|[^\w\s]", text))

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in re.findall(r"\w+", text.lower()):
            bucket = int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


@lru_cache
def get_embedder() -> Embedder:
    """The app-wide embedder, loaded once (loading the model takes a few seconds)."""
    settings = get_settings()
    return FastEmbedEmbedder(settings.embedding_model, cache_dir=str(settings.model_cache_dir))
