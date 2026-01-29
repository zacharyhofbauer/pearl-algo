from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Chunk:
    chunk_id: str
    path: str
    start_line: int
    end_line: int
    text: str
    language: str
    kind: str


@dataclass
class ChunkResult:
    chunk: Chunk
    score: float
