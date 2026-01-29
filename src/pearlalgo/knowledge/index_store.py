from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from pearlalgo.knowledge.types import Chunk, ChunkResult

try:
    import faiss  # type: ignore
    FAISS_AVAILABLE = True
except Exception:
    faiss = None  # type: ignore
    FAISS_AVAILABLE = False


@dataclass
class IndexConfig:
    index_dir: Path
    use_faiss: bool = False


class IndexStore:
    def __init__(self, config: IndexConfig):
        self.config = config
        self.index_dir = config.index_dir
        self.db_path = self.index_dir / "index.db"
        self.faiss_path = self.index_dir / "index.faiss"
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._faiss_index = None
        self._faiss_ids: List[str] = []
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    sha256 TEXT,
                    mtime REAL,
                    size INTEGER,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    path TEXT,
                    start_line INTEGER,
                    end_line INTEGER,
                    language TEXT,
                    kind TEXT,
                    content TEXT,
                    content_hash TEXT,
                    embedding BLOB,
                    embedding_dim INTEGER,
                    updated_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(path)")

    def get_file_hash(self, path: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute("SELECT sha256 FROM files WHERE path = ?", (path,)).fetchone()
            return row[0] if row else None

    def upsert_file(self, path: str, sha256: str, mtime: float, size: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO files(path, sha256, mtime, size, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    sha256=excluded.sha256,
                    mtime=excluded.mtime,
                    size=excluded.size,
                    updated_at=excluded.updated_at
                """,
                (path, sha256, mtime, size, now),
            )

    def delete_chunks_for_file(self, path: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM chunks WHERE path = ?", (path,))

    def upsert_chunks(self, path: str, chunks: List[Chunk], embeddings: np.ndarray) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            for chunk, embedding in zip(chunks, embeddings):
                conn.execute(
                    """
                    INSERT INTO chunks(
                        chunk_id, path, start_line, end_line, language, kind,
                        content, content_hash, embedding, embedding_dim, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        path=excluded.path,
                        start_line=excluded.start_line,
                        end_line=excluded.end_line,
                        language=excluded.language,
                        kind=excluded.kind,
                        content=excluded.content,
                        content_hash=excluded.content_hash,
                        embedding=excluded.embedding,
                        embedding_dim=excluded.embedding_dim,
                        updated_at=excluded.updated_at
                    """,
                    (
                        chunk.chunk_id,
                        chunk.path,
                        chunk.start_line,
                        chunk.end_line,
                        chunk.language,
                        chunk.kind,
                        chunk.text,
                        chunk.chunk_id.split(":")[-1],
                        embedding.astype(np.float32).tobytes(),
                        int(embedding.shape[0]),
                        now,
                    ),
                )
        self._faiss_index = None

    def list_indexed_files(self) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT path FROM files").fetchall()
        return [r[0] for r in rows]

    def load_embeddings(self) -> Tuple[List[Chunk], np.ndarray]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT chunk_id, path, start_line, end_line, language, kind, content, embedding, embedding_dim
                FROM chunks
                """
            ).fetchall()
        chunks: List[Chunk] = []
        vectors: List[np.ndarray] = []
        for row in rows:
            chunk_id, path, start_line, end_line, language, kind, content, emb_blob, emb_dim = row
            chunk = Chunk(
                chunk_id=chunk_id,
                path=path,
                start_line=int(start_line),
                end_line=int(end_line),
                text=content,
                language=language,
                kind=kind,
            )
            chunks.append(chunk)
            vec = np.frombuffer(emb_blob, dtype=np.float32, count=int(emb_dim))
            vectors.append(vec)
        if not vectors:
            return [], np.zeros((0, 1), dtype=np.float32)
        return chunks, np.vstack(vectors)

    def search(self, query_embedding: np.ndarray, top_k: int = 6) -> List[ChunkResult]:
        chunks, matrix = self.load_embeddings()
        if len(chunks) == 0:
            return []
        query_embedding = query_embedding.astype(np.float32)
        if self.config.use_faiss and FAISS_AVAILABLE:
            return self._search_faiss(chunks, matrix, query_embedding, top_k)
        return self._search_bruteforce(chunks, matrix, query_embedding, top_k)

    def _search_bruteforce(
        self, chunks: List[Chunk], matrix: np.ndarray, query_embedding: np.ndarray, top_k: int
    ) -> List[ChunkResult]:
        sims = matrix @ query_embedding.reshape(-1, 1)
        sims = sims.flatten()
        top_idx = np.argsort(-sims)[:top_k]
        return [ChunkResult(chunk=chunks[i], score=float(sims[i])) for i in top_idx]

    def _search_faiss(
        self, chunks: List[Chunk], matrix: np.ndarray, query_embedding: np.ndarray, top_k: int
    ) -> List[ChunkResult]:
        if self._faiss_index is None:
            if not FAISS_AVAILABLE:
                return self._search_bruteforce(chunks, matrix, query_embedding, top_k)
            dim = matrix.shape[1]
            index = faiss.IndexFlatIP(dim)
            index.add(matrix.astype(np.float32))
            self._faiss_index = index
            self._faiss_ids = [c.chunk_id for c in chunks]
        scores, indices = self._faiss_index.search(query_embedding.reshape(1, -1), top_k)
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            results.append(ChunkResult(chunk=chunks[idx], score=float(score)))
        return results
