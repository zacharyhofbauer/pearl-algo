from __future__ import annotations

from pathlib import Path

from pearlalgo.knowledge.indexer import KnowledgeIndexConfig, KnowledgeIndexer
from pearlalgo.knowledge.retriever import KnowledgeRetriever, RetrieverConfig


def test_repo_indexer_excludes_and_indexes(tmp_path: Path) -> None:
    # Create mock repo structure
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "src" / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    (tmp_path / "docs" / "readme.md").write_text("# Title\nSome docs\n", encoding="utf-8")
    (tmp_path / "data" / "secret.txt").write_text("SECRET", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=123", encoding="utf-8")

    index_dir = tmp_path / "index"
    cfg = KnowledgeIndexConfig(
        root_dir=tmp_path,
        index_dir=index_dir,
        include_paths=["src", "docs"],
        exclude_globs=["data/**", ".env*"],
        embedding_provider="hash",
        embedding_dim=64,
    )
    indexer = KnowledgeIndexer(cfg)
    stats = indexer.sync_index()

    files = indexer.store.list_indexed_files()
    assert "src/app.py" in files
    assert "docs/readme.md" in files
    assert not any("data/" in f for f in files)
    assert not any(".env" in f for f in files)
    assert stats["indexed"] >= 1


def test_retriever_returns_context(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    index_dir = tmp_path / "index"
    cfg = KnowledgeIndexConfig(
        root_dir=tmp_path,
        index_dir=index_dir,
        include_paths=["src"],
        exclude_globs=[],
        embedding_provider="hash",
        embedding_dim=64,
    )
    indexer = KnowledgeIndexer(cfg)
    indexer.sync_index()

    retriever = KnowledgeRetriever(
        RetrieverConfig(
            index_dir=index_dir,
            embedding_provider="hash",
            embedding_dim=64,
            top_k=3,
        )
    )
    results = retriever.search("add two numbers")
    assert results
