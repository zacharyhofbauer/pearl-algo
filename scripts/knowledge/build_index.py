#!/usr/bin/env python3
# ============================================================================
# Category: Knowledge
# Purpose: Build or refresh the repo knowledge index
# Usage:
#   python3 scripts/knowledge/build_index.py
# ============================================================================
from __future__ import annotations

import argparse
from pathlib import Path

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.knowledge.indexer import KnowledgeIndexConfig, KnowledgeIndexer


def _load_config() -> KnowledgeIndexConfig:
    cfg = load_service_config(validate=False) or {}
    knowledge_cfg = cfg.get("knowledge", {}) or {}
    repo_root = Path(__file__).resolve().parent.parent.parent
    index_dir = Path(str(knowledge_cfg.get("index_dir", "data/knowledge_index")))
    if not index_dir.is_absolute():
        index_dir = (repo_root / index_dir).resolve()

    return KnowledgeIndexConfig(
        root_dir=repo_root,
        index_dir=index_dir,
        include_paths=knowledge_cfg.get(
            "include_paths",
            ["src", "docs", "config", "scripts", "pyproject.toml"],
        ),
        exclude_globs=knowledge_cfg.get(
            "exclude_globs",
            [".env*", "data/**", "logs/**", "tests/artifacts/**", ".venv/**", "ibkr/**", ".git/**"],
        ),
        max_file_size_kb=int(knowledge_cfg.get("max_file_size_kb", 512)),
        chunk_max_chars=int(knowledge_cfg.get("chunk_max_chars", 2000)),
        chunk_overlap_chars=int(knowledge_cfg.get("chunk_overlap_chars", 200)),
        embedding_provider=str(knowledge_cfg.get("embedding_provider", "auto")),
        embedding_model=str(knowledge_cfg.get("embedding_model", "text-embedding-3-small")),
        embedding_dim=int(knowledge_cfg.get("embedding_dim", 384)),
        use_faiss=bool(knowledge_cfg.get("use_faiss", False)),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the repo knowledge index")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild index (same as sync for now)")
    args = parser.parse_args()

    index_config = _load_config()
    indexer = KnowledgeIndexer(index_config)
    stats = indexer.sync_index()
    print(f"Index complete: {stats}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
