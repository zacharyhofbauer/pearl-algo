from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except Exception:
    OpenAI = None  # type: ignore
    OPENAI_AVAILABLE = False


TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class EmbeddingConfig:
    provider: str = "auto"  # auto | openai | hash
    model: str = "text-embedding-3-small"
    dim: int = 384
    max_chars: int = 8000


class EmbeddingProvider:
    def __init__(self, config: Optional[EmbeddingConfig] = None):
        self.config = config or EmbeddingConfig()
        self._client = None

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        if self._use_openai():
            return self._embed_openai(texts)
        return self._embed_hash(texts)

    def _use_openai(self) -> bool:
        if self.config.provider == "hash":
            return False
        if self.config.provider == "openai":
            return OPENAI_AVAILABLE and bool(os.getenv("OPENAI_API_KEY"))
        return OPENAI_AVAILABLE and bool(os.getenv("OPENAI_API_KEY"))

    def _embed_openai(self, texts: List[str]) -> np.ndarray:
        if not OPENAI_AVAILABLE:
            return self._embed_hash(texts)
        if self._client is None:
            self._client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        trimmed = [t[: self.config.max_chars] for t in texts]
        response = self._client.embeddings.create(model=self.config.model, input=trimmed)
        vectors = [np.array(item.embedding, dtype=np.float32) for item in response.data]
        return self._normalize(np.vstack(vectors))

    def _embed_hash(self, texts: List[str]) -> np.ndarray:
        dim = int(self.config.dim)
        vectors = np.zeros((len(texts), dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for token in TOKEN_RE.findall(text.lower()):
                idx = hash(token) % dim
                vectors[i, idx] += 1.0
        return self._normalize(vectors)

    def _normalize(self, vectors: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms
