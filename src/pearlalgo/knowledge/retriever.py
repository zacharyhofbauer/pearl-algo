from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np

from pearlalgo.knowledge.embeddings import EmbeddingConfig, EmbeddingProvider
from pearlalgo.knowledge.index_store import IndexConfig, IndexStore
from pearlalgo.knowledge.types import ChunkResult


@dataclass
class RetrieverConfig:
    index_dir: Path
    embedding_provider: str = "auto"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384
    top_k: int = 6
    use_faiss: bool = False
    max_chars: int = 2000


class KnowledgeRetriever:
    def __init__(self, config: RetrieverConfig):
        self.config = config
        self.embedder = EmbeddingProvider(
            EmbeddingConfig(
                provider=config.embedding_provider,
                model=config.embedding_model,
                dim=config.embedding_dim,
            )
        )
        self.store = IndexStore(IndexConfig(index_dir=config.index_dir, use_faiss=config.use_faiss))

    def search(self, query: str) -> List[ChunkResult]:
        if not query:
            return []
        embedding = self.embedder.embed_texts([query])[0]
        return self.store.search(embedding, top_k=self.config.top_k)

    def format_context(self, results: List[ChunkResult]) -> str:
        if not results:
            return ""
        parts: List[str] = []
        for res in results:
            chunk = res.chunk
            snippet = chunk.text
            if len(snippet) > self.config.max_chars:
                snippet = snippet[: self.config.max_chars] + "\n... (truncated)"
            parts.append(f"- {chunk.path}:{chunk.start_line}-{chunk.end_line}\n{snippet}")
        return "\n\n".join(parts)
