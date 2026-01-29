"""
Memory Store - Persistent storage for Pearl's memory system.

Provides SQLite-based storage for episodic, semantic, and procedural memories
with semantic search capabilities using embeddings.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, List, Optional, Union

from pearlalgo.memory.types import (
    Episode,
    Knowledge,
    Procedure,
    MemoryType,
    MemoryQuery,
)
from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir


class PearlMemory:
    """
    Pearl's persistent memory system.
    
    Features:
    - Store episodic memories (specific events)
    - Accumulate semantic knowledge (patterns, rules)
    - Learn procedural behaviors (when to do what)
    - Semantic search using embeddings
    - Memory decay and consolidation
    
    Usage:
        memory = PearlMemory()
        
        # Remember an episode
        episode = Episode(
            event_type="trade_win",
            context={"direction": "LONG", "regime": "trending_up"},
            outcome={"pnl": 125.00},
            lesson="LONG in trending_up works"
        )
        await memory.remember(episode)
        
        # Recall relevant memories
        memories = await memory.recall("trending_up LONG")
        
        # Synthesize knowledge
        insight = await memory.synthesize("regime performance")
    """
    
    def __init__(
        self,
        db_path: Optional[Path] = None,
        embedding_dim: int = 384,
        max_episodes: int = 10000,
        max_knowledge: int = 5000,
    ):
        """
        Initialize Pearl memory.
        
        Args:
            db_path: Path to SQLite database
            embedding_dim: Dimension of embeddings for semantic search
            max_episodes: Maximum episodic memories to retain
            max_knowledge: Maximum semantic memories to retain
        """
        self.db_path = db_path or (ensure_state_dir(None) / "pearl_memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self._embedding_dim = embedding_dim
        self._max_episodes = max_episodes
        self._max_knowledge = max_knowledge
        
        # Embedding provider (lazy loaded)
        self._embedder = None
        
        self._init_schema()
        
        logger.info(f"PearlMemory initialized: {self.db_path}")
    
    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def _init_schema(self) -> None:
        """Initialize database schema."""
        with self._get_connection() as conn:
            conn.executescript("""
                -- Episodic memories
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    event_type TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    context_json TEXT,
                    outcome_json TEXT,
                    lesson TEXT,
                    importance REAL DEFAULT 0.5,
                    embedding BLOB,
                    recall_count INTEGER DEFAULT 0,
                    last_recalled TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
                
                CREATE INDEX IF NOT EXISTS idx_episodes_event_type ON episodes(event_type);
                CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp);
                CREATE INDEX IF NOT EXISTS idx_episodes_importance ON episodes(importance);
                
                -- Semantic knowledge
                CREATE TABLE IF NOT EXISTS knowledge (
                    id TEXT PRIMARY KEY,
                    topic TEXT NOT NULL,
                    insight TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    evidence_count INTEGER DEFAULT 0,
                    source_episodes_json TEXT,
                    embedding BLOB,
                    created_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL
                );
                
                CREATE INDEX IF NOT EXISTS idx_knowledge_topic ON knowledge(topic);
                CREATE INDEX IF NOT EXISTS idx_knowledge_confidence ON knowledge(confidence);
                
                -- Procedural behaviors
                CREATE TABLE IF NOT EXISTS procedures (
                    id TEXT PRIMARY KEY,
                    trigger TEXT NOT NULL,
                    action TEXT NOT NULL,
                    success_rate REAL DEFAULT 0.5,
                    times_applied INTEGER DEFAULT 0,
                    times_successful INTEGER DEFAULT 0,
                    examples_json TEXT,
                    created_at TEXT NOT NULL,
                    last_applied TEXT,
                    enabled INTEGER DEFAULT 1
                );
                
                CREATE INDEX IF NOT EXISTS idx_procedures_enabled ON procedures(enabled);
                CREATE INDEX IF NOT EXISTS idx_procedures_success_rate ON procedures(success_rate);
                
                -- Memory statistics
                CREATE TABLE IF NOT EXISTS memory_stats (
                    stat_key TEXT PRIMARY KEY,
                    stat_value TEXT,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
    
    def _get_embedding(self, text: str) -> Optional[list[float]]:
        """Get embedding for text (using hash-based fallback if no embedder)."""
        # Simple hash-based embedding for now
        # In production, would use OpenAI or local embeddings
        import hashlib
        
        hash_bytes = hashlib.sha256(text.encode()).digest()
        # Convert to float vector (simple hash-based embedding)
        embedding = [
            (b / 255.0) * 2 - 1  # Normalize to [-1, 1]
            for b in hash_bytes[:self._embedding_dim]
        ]
        
        # Pad if needed
        while len(embedding) < self._embedding_dim:
            embedding.append(0.0)
        
        return embedding[:self._embedding_dim]
    
    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        import math
        
        dot_product = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return dot_product / (norm_a * norm_b)
    
    async def remember(self, memory: Union[Episode, Knowledge, Procedure]) -> str:
        """
        Store a memory.
        
        Args:
            memory: Episode, Knowledge, or Procedure to store
            
        Returns:
            ID of the stored memory
        """
        if isinstance(memory, Episode):
            return await self._remember_episode(memory)
        elif isinstance(memory, Knowledge):
            return await self._remember_knowledge(memory)
        elif isinstance(memory, Procedure):
            return await self._remember_procedure(memory)
        else:
            raise ValueError(f"Unknown memory type: {type(memory)}")
    
    async def _remember_episode(self, episode: Episode) -> str:
        """Store an episodic memory."""
        if not episode.id:
            episode.id = f"ep-{uuid.uuid4().hex[:12]}"
        
        # Generate embedding
        search_text = episode.get_searchable_text()
        episode.embedding = self._get_embedding(search_text)
        
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO episodes (
                    id, event_type, timestamp, context_json, outcome_json,
                    lesson, importance, embedding, recall_count, last_recalled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                episode.id,
                episode.event_type,
                episode.timestamp.isoformat(),
                json.dumps(episode.context),
                json.dumps(episode.outcome),
                episode.lesson,
                episode.importance,
                json.dumps(episode.embedding) if episode.embedding else None,
                episode.recall_count,
                episode.last_recalled.isoformat() if episode.last_recalled else None,
            ))
            
            # Prune old episodes if needed
            count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            if count > self._max_episodes:
                # Delete oldest, least important episodes
                conn.execute("""
                    DELETE FROM episodes
                    WHERE id IN (
                        SELECT id FROM episodes
                        ORDER BY importance ASC, timestamp ASC
                        LIMIT ?
                    )
                """, (count - self._max_episodes,))
            
            conn.commit()
        
        logger.debug(f"Stored episode {episode.id}: {episode.event_type}")
        return episode.id
    
    async def _remember_knowledge(self, knowledge: Knowledge) -> str:
        """Store semantic knowledge."""
        if not knowledge.id:
            knowledge.id = f"kn-{uuid.uuid4().hex[:12]}"
        
        # Generate embedding
        search_text = knowledge.get_searchable_text()
        knowledge.embedding = self._get_embedding(search_text)
        
        with self._get_connection() as conn:
            # Check for existing knowledge on same topic
            existing = conn.execute(
                "SELECT id FROM knowledge WHERE topic = ? AND id != ?",
                (knowledge.topic, knowledge.id)
            ).fetchone()
            
            if existing:
                # Update existing knowledge
                conn.execute("""
                    UPDATE knowledge
                    SET insight = ?,
                        confidence = ?,
                        evidence_count = ?,
                        source_episodes_json = ?,
                        embedding = ?,
                        last_updated = ?
                    WHERE id = ?
                """, (
                    knowledge.insight,
                    knowledge.confidence,
                    knowledge.evidence_count,
                    json.dumps(knowledge.source_episodes),
                    json.dumps(knowledge.embedding) if knowledge.embedding else None,
                    knowledge.last_updated.isoformat(),
                    existing["id"],
                ))
                knowledge.id = existing["id"]
            else:
                # Insert new knowledge
                conn.execute("""
                    INSERT INTO knowledge (
                        id, topic, insight, confidence, evidence_count,
                        source_episodes_json, embedding, created_at, last_updated
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    knowledge.id,
                    knowledge.topic,
                    knowledge.insight,
                    knowledge.confidence,
                    knowledge.evidence_count,
                    json.dumps(knowledge.source_episodes),
                    json.dumps(knowledge.embedding) if knowledge.embedding else None,
                    knowledge.created_at.isoformat(),
                    knowledge.last_updated.isoformat(),
                ))
            
            conn.commit()
        
        logger.debug(f"Stored knowledge {knowledge.id}: {knowledge.topic}")
        return knowledge.id
    
    async def _remember_procedure(self, procedure: Procedure) -> str:
        """Store a procedural memory."""
        if not procedure.id:
            procedure.id = f"pr-{uuid.uuid4().hex[:12]}"
        
        with self._get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO procedures (
                    id, trigger, action, success_rate, times_applied,
                    times_successful, examples_json, created_at, last_applied, enabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                procedure.id,
                procedure.trigger,
                procedure.action,
                procedure.success_rate,
                procedure.times_applied,
                procedure.times_successful,
                json.dumps(procedure.examples),
                procedure.created_at.isoformat(),
                procedure.last_applied.isoformat() if procedure.last_applied else None,
                1 if procedure.enabled else 0,
            ))
            conn.commit()
        
        logger.debug(f"Stored procedure {procedure.id}: {procedure.trigger}")
        return procedure.id
    
    async def recall(
        self,
        query: Union[str, MemoryQuery],
        k: int = 5,
    ) -> list[Union[Episode, Knowledge, Procedure]]:
        """
        Recall memories relevant to a query.
        
        Args:
            query: Query string or MemoryQuery object
            k: Maximum number of results
            
        Returns:
            List of relevant memories
        """
        if isinstance(query, str):
            query = MemoryQuery(query_text=query, top_k=k)
        
        # Get query embedding
        query_embedding = self._get_embedding(query.query_text)
        
        results = []
        
        with self._get_connection() as conn:
            # Search episodes
            if MemoryType.EPISODIC in query.memory_types:
                episodes = self._search_episodes(conn, query, query_embedding)
                results.extend(episodes)
            
            # Search knowledge
            if MemoryType.SEMANTIC in query.memory_types:
                knowledge = self._search_knowledge(conn, query, query_embedding)
                results.extend(knowledge)
            
            # Search procedures
            if MemoryType.PROCEDURAL in query.memory_types:
                procedures = self._search_procedures(conn, query, query_embedding)
                results.extend(procedures)
        
        # Sort by relevance and return top k
        # For now, just return as-is (would sort by similarity score)
        return results[:query.top_k]
    
    def _search_episodes(
        self,
        conn: sqlite3.Connection,
        query: MemoryQuery,
        query_embedding: list[float],
    ) -> list[Episode]:
        """Search episodic memories."""
        conditions = ["1=1"]
        params = []
        
        if query.event_types:
            placeholders = ",".join("?" * len(query.event_types))
            conditions.append(f"event_type IN ({placeholders})")
            params.extend(query.event_types)
        
        if query.min_importance > 0:
            conditions.append("importance >= ?")
            params.append(query.min_importance)
        
        if query.start_time:
            conditions.append("timestamp >= ?")
            params.append(query.start_time.isoformat())
        
        if query.end_time:
            conditions.append("timestamp <= ?")
            params.append(query.end_time.isoformat())
        
        where_clause = " AND ".join(conditions)
        
        rows = conn.execute(f"""
            SELECT * FROM episodes
            WHERE {where_clause}
            ORDER BY importance DESC, timestamp DESC
            LIMIT ?
        """, params + [query.top_k * 2]).fetchall()  # Get extra for filtering
        
        episodes = []
        for row in rows:
            episode = Episode(
                id=row["id"],
                event_type=row["event_type"],
                timestamp=datetime.fromisoformat(row["timestamp"]),
                context=json.loads(row["context_json"]) if row["context_json"] else {},
                outcome=json.loads(row["outcome_json"]) if row["outcome_json"] else {},
                lesson=row["lesson"] or "",
                importance=row["importance"],
                embedding=json.loads(row["embedding"]) if row["embedding"] else None,
                recall_count=row["recall_count"],
                last_recalled=datetime.fromisoformat(row["last_recalled"]) if row["last_recalled"] else None,
            )
            
            # Calculate similarity if we have embeddings
            if episode.embedding and query_embedding:
                similarity = self._cosine_similarity(query_embedding, episode.embedding)
                if similarity > 0.3:  # Threshold
                    episodes.append(episode)
            else:
                episodes.append(episode)
            
            # Update recall count
            conn.execute("""
                UPDATE episodes
                SET recall_count = recall_count + 1, last_recalled = ?
                WHERE id = ?
            """, (datetime.now(timezone.utc).isoformat(), episode.id))
        
        conn.commit()
        return episodes[:query.top_k]
    
    def _search_knowledge(
        self,
        conn: sqlite3.Connection,
        query: MemoryQuery,
        query_embedding: list[float],
    ) -> list[Knowledge]:
        """Search semantic knowledge."""
        conditions = ["1=1"]
        params = []
        
        if query.topics:
            placeholders = ",".join("?" * len(query.topics))
            conditions.append(f"topic IN ({placeholders})")
            params.extend(query.topics)
        
        if query.min_confidence > 0:
            conditions.append("confidence >= ?")
            params.append(query.min_confidence)
        
        where_clause = " AND ".join(conditions)
        
        rows = conn.execute(f"""
            SELECT * FROM knowledge
            WHERE {where_clause}
            ORDER BY confidence DESC, last_updated DESC
            LIMIT ?
        """, params + [query.top_k]).fetchall()
        
        return [
            Knowledge(
                id=row["id"],
                topic=row["topic"],
                insight=row["insight"],
                confidence=row["confidence"],
                evidence_count=row["evidence_count"],
                source_episodes=json.loads(row["source_episodes_json"]) if row["source_episodes_json"] else [],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_updated=datetime.fromisoformat(row["last_updated"]),
                embedding=json.loads(row["embedding"]) if row["embedding"] else None,
            )
            for row in rows
        ]
    
    def _search_procedures(
        self,
        conn: sqlite3.Connection,
        query: MemoryQuery,
        query_embedding: list[float],
    ) -> list[Procedure]:
        """Search procedural memories."""
        rows = conn.execute("""
            SELECT * FROM procedures
            WHERE enabled = 1
            ORDER BY success_rate DESC, times_applied DESC
            LIMIT ?
        """, (query.top_k,)).fetchall()
        
        return [
            Procedure(
                id=row["id"],
                trigger=row["trigger"],
                action=row["action"],
                success_rate=row["success_rate"],
                times_applied=row["times_applied"],
                times_successful=row["times_successful"],
                examples=json.loads(row["examples_json"]) if row["examples_json"] else [],
                created_at=datetime.fromisoformat(row["created_at"]),
                last_applied=datetime.fromisoformat(row["last_applied"]) if row["last_applied"] else None,
                enabled=bool(row["enabled"]),
            )
            for row in rows
        ]
    
    async def synthesize(self, topic: str) -> str:
        """
        Generate a summary insight on a topic.
        
        Args:
            topic: Topic to synthesize
            
        Returns:
            Synthesized insight string
        """
        # Get relevant memories
        query = MemoryQuery(
            query_text=topic,
            memory_types=[MemoryType.EPISODIC, MemoryType.SEMANTIC],
            top_k=20,
        )
        memories = await self.recall(query)
        
        if not memories:
            return f"No memories found for topic: {topic}"
        
        # Build synthesis
        episodes = [m for m in memories if isinstance(m, Episode)]
        knowledge = [m for m in memories if isinstance(m, Knowledge)]
        
        lines = [f"Synthesis for '{topic}':"]
        
        # Add existing knowledge
        if knowledge:
            lines.append("\nKnown insights:")
            for k in knowledge:
                lines.append(f"  - {k.insight} (confidence: {k.confidence:.0%})")
        
        # Summarize episodes
        if episodes:
            event_types = {}
            for ep in episodes:
                event_types[ep.event_type] = event_types.get(ep.event_type, 0) + 1
            
            lines.append(f"\nBased on {len(episodes)} episodes:")
            for event_type, count in sorted(event_types.items(), key=lambda x: -x[1]):
                lines.append(f"  - {event_type}: {count} occurrences")
            
            # Extract lessons
            lessons = [ep.lesson for ep in episodes if ep.lesson]
            if lessons:
                lines.append("\nKey lessons:")
                for lesson in lessons[:5]:
                    lines.append(f"  - {lesson}")
        
        return "\n".join(lines)
    
    async def forget(
        self,
        criteria: dict[str, Any],
        require_approval: bool = True,
    ) -> int:
        """
        Remove memories matching criteria.
        
        Args:
            criteria: Filter criteria
            require_approval: Whether to require approval (stub for now)
            
        Returns:
            Number of memories removed
        """
        if require_approval:
            logger.warning("Memory deletion requires approval (not implemented)")
            return 0
        
        # This would implement memory deletion with various criteria
        # For safety, returning 0 for now
        return 0
    
    def get_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        with self._get_connection() as conn:
            episode_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            knowledge_count = conn.execute("SELECT COUNT(*) FROM knowledge").fetchone()[0]
            procedure_count = conn.execute("SELECT COUNT(*) FROM procedures").fetchone()[0]
            
            # Recent activity
            recent_episodes = conn.execute("""
                SELECT COUNT(*) FROM episodes
                WHERE timestamp > datetime('now', '-7 days')
            """).fetchone()[0]
            
            return {
                "total_episodes": episode_count,
                "total_knowledge": knowledge_count,
                "total_procedures": procedure_count,
                "recent_episodes_7d": recent_episodes,
            }


# Global memory instance
_memory: Optional[PearlMemory] = None


def get_pearl_memory() -> PearlMemory:
    """Get the global Pearl memory instance."""
    global _memory
    if _memory is None:
        _memory = PearlMemory()
    return _memory
