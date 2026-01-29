#!/usr/bin/env python3
# ============================================================================
# Category: Knowledge
# Purpose: Watch repo changes and refresh knowledge index
# Usage:
#   python3 scripts/knowledge/watch_repo.py --interval 30
# ============================================================================
from __future__ import annotations

import argparse
import time
from pathlib import Path

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.knowledge.indexer import KnowledgeIndexConfig, KnowledgeIndexer

try:
    from watchdog.events import FileSystemEventHandler  # type: ignore
    from watchdog.observers import Observer  # type: ignore
    WATCHDOG_AVAILABLE = True
except Exception:
    FileSystemEventHandler = object  # type: ignore
    Observer = None  # type: ignore
    WATCHDOG_AVAILABLE = False


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
    parser = argparse.ArgumentParser(description="Watch repo and refresh knowledge index")
    parser.add_argument("--interval", type=int, default=30, help="Polling interval in seconds")
    parser.add_argument("--debounce", type=int, default=5, help="Debounce seconds for watcher events")
    args = parser.parse_args()

    index_config = _load_config()
    indexer = KnowledgeIndexer(index_config)

    if WATCHDOG_AVAILABLE and Observer is not None:
        class _Handler(FileSystemEventHandler):  # type: ignore
            def __init__(self) -> None:
                self._last_run = 0.0

            def on_any_event(self, event) -> None:  # noqa: D401
                now = time.time()
                if now - self._last_run < float(args.debounce):
                    return
                self._last_run = now
                stats = indexer.sync_index()
                if stats.get("indexed", 0) > 0:
                    print(f"[indexer] Updated: {stats}")

        observer = Observer()
        observer.schedule(_Handler(), str(index_config.root_dir), recursive=True)
        observer.start()
        print("Knowledge index watcher started (watchdog mode).")
        try:
            while True:
                time.sleep(max(5, int(args.interval)))
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    else:
        print("Knowledge index watcher started (polling mode).")
        while True:
            stats = indexer.sync_index()
            if stats.get("indexed", 0) > 0:
                print(f"[indexer] Updated: {stats}")
            time.sleep(max(5, int(args.interval)))


if __name__ == "__main__":
    raise SystemExit(main())
