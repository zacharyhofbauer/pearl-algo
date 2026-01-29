from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from pearlalgo.knowledge.types import Chunk


@dataclass
class ChunkConfig:
    max_chars: int = 2000
    overlap_chars: int = 200


class Chunker:
    def __init__(self, config: Optional[ChunkConfig] = None):
        self.config = config or ChunkConfig()

    def chunk_file(self, path: Path, text: str) -> List[Chunk]:
        suffix = path.suffix.lower()
        if suffix == ".py":
            chunks = self._chunk_python(path, text)
            return chunks or self._chunk_generic(path, text, language="python")
        if suffix in {".md", ".markdown"}:
            return self._chunk_markdown(path, text)
        if suffix in {".yaml", ".yml", ".toml", ".ini"}:
            return self._chunk_generic(path, text, language="config")
        return self._chunk_generic(path, text, language="text")

    def _chunk_python(self, path: Path, text: str) -> List[Chunk]:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return []
        lines = text.splitlines()
        chunks: List[Chunk] = []

        # Module-level chunk (imports + constants)
        if lines:
            module_end = min(len(lines), max(1, self.config.max_chars // max(1, len(lines[0]))))
            module_text = "\n".join(lines[:module_end]).strip()
            if module_text:
                chunks.append(self._build_chunk(path, 1, module_end, module_text, "python", "module"))

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
                    continue
                start = int(node.lineno)
                end = int(node.end_lineno or node.lineno)
                start = max(1, start)
                end = min(len(lines), end)
                snippet = "\n".join(lines[start - 1 : end]).strip()
                if snippet:
                    kind = "class" if isinstance(node, ast.ClassDef) else "function"
                    chunks.append(self._build_chunk(path, start, end, snippet, "python", kind))

        return chunks

    def _chunk_markdown(self, path: Path, text: str) -> List[Chunk]:
        lines = text.splitlines()
        chunks: List[Chunk] = []
        start = 0
        for idx, line in enumerate(lines):
            if idx == 0:
                continue
            if line.startswith("#"):
                chunk_text = "\n".join(lines[start:idx]).strip()
                if chunk_text:
                    chunks.append(self._build_chunk(path, start + 1, idx, chunk_text, "markdown", "section"))
                start = idx
        final_text = "\n".join(lines[start:]).strip()
        if final_text:
            chunks.append(self._build_chunk(path, start + 1, len(lines), final_text, "markdown", "section"))
        return chunks

    def _chunk_generic(self, path: Path, text: str, language: str) -> List[Chunk]:
        if not text.strip():
            return []
        max_chars = self.config.max_chars
        overlap = self.config.overlap_chars
        chunks: List[Chunk] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + max_chars)
            chunk_text = text[start:end].strip()
            if chunk_text:
                start_line = text[:start].count("\n") + 1
                end_line = text[:end].count("\n") + 1
                chunks.append(self._build_chunk(path, start_line, end_line, chunk_text, language, "block"))
            if end >= len(text):
                break
            start = max(0, end - overlap)
        return chunks

    def _build_chunk(
        self,
        path: Path,
        start_line: int,
        end_line: int,
        text: str,
        language: str,
        kind: str,
    ) -> Chunk:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        chunk_id = f"{path.as_posix()}:{start_line}-{end_line}:{digest}"
        return Chunk(
            chunk_id=chunk_id,
            path=path.as_posix(),
            start_line=start_line,
            end_line=end_line,
            text=text,
            language=language,
            kind=kind,
        )
