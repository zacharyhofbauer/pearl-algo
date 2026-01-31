from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

from pearlalgo.knowledge.chunker import ChunkConfig, Chunker
from pearlalgo.knowledge.embeddings import EmbeddingConfig, EmbeddingProvider
from pearlalgo.knowledge.index_store import IndexConfig, IndexStore
from pearlalgo.knowledge.scanner import RepoScanConfig, RepoScanner


@dataclass
class KnowledgeIndexConfig:
    root_dir: Path
    index_dir: Path
    include_paths: List[str]
    exclude_globs: List[str]
    max_file_size_kb: int = 512
    chunk_max_chars: int = 2000
    chunk_overlap_chars: int = 200
    embedding_provider: str = "auto"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 384
    use_faiss: bool = False


class KnowledgeIndexer:
    def __init__(self, config: KnowledgeIndexConfig):
        self.config = config
        self.scanner = RepoScanner(
            RepoScanConfig(
                root_dir=config.root_dir,
                include_paths=config.include_paths,
                exclude_globs=config.exclude_globs,
                max_file_size_kb=config.max_file_size_kb,
            )
        )
        self.chunker = Chunker(
            ChunkConfig(
                max_chars=config.chunk_max_chars,
                overlap_chars=config.chunk_overlap_chars,
            )
        )
        self.embedder = EmbeddingProvider(
            EmbeddingConfig(
                provider=config.embedding_provider,
                model=config.embedding_model,
                dim=config.embedding_dim,
            )
        )
        self.store = IndexStore(IndexConfig(index_dir=config.index_dir, use_faiss=config.use_faiss))

    def sync_index(self) -> Dict[str, int]:
        files = self.scanner.scan()
        indexed = 0
        skipped = 0
        for path in files:
            rel_path = path.relative_to(self.config.root_dir).as_posix()
            sha = self._file_hash(path)
            prior = self.store.get_file_hash(rel_path)
            if prior == sha:
                skipped += 1
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            chunks = self.chunker.chunk_file(Path(rel_path), text)
            if not chunks:
                skipped += 1
                continue
            embeddings = self.embedder.embed_texts([c.text for c in chunks])
            self.store.delete_chunks_for_file(rel_path)
            self.store.upsert_file(rel_path, sha, path.stat().st_mtime, path.stat().st_size)
            self.store.upsert_chunks(rel_path, chunks, embeddings)
            indexed += 1
        self._prune_missing(files)
        return {"indexed": indexed, "skipped": skipped, "total": len(files)}

    def _file_hash(self, path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _prune_missing(self, files: List[Path]) -> None:
        current = {p.relative_to(self.config.root_dir).as_posix() for p in files}
        indexed = set(self.store.list_indexed_files())
        missing = indexed - current
        if not missing:
            return
        for rel_path in missing:
            self.store.delete_chunks_for_file(rel_path)
