"""
Memory Types - Data structures for Pearl's memory system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class MemoryType(Enum):
    """Types of memories."""
    EPISODIC = "episodic"      # Specific events
    SEMANTIC = "semantic"      # Accumulated knowledge
    PROCEDURAL = "procedural"  # Learned behaviors


@dataclass
class Episode:
    """
    An episodic memory - a specific event and its context.
    
    Episodic memories capture:
    - What happened (event_type, outcome)
    - When it happened (timestamp)
    - The context (market conditions, indicators, etc.)
    - What was learned (lesson)
    """
    # Event identification
    event_type: str  # trade_win, trade_loss, filter_block, error, insight, etc.
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Event context
    context: dict[str, Any] = field(default_factory=dict)
    
    # What happened
    outcome: dict[str, Any] = field(default_factory=dict)
    
    # Learning extracted
    lesson: str = ""
    
    # Metadata
    id: str = ""
    importance: float = 0.5  # 0-1, affects retention
    embedding: Optional[list[float]] = None  # For semantic search
    
    # Recall tracking
    recall_count: int = 0
    last_recalled: Optional[datetime] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "outcome": self.outcome,
            "lesson": self.lesson,
            "importance": self.importance,
            "recall_count": self.recall_count,
            "last_recalled": self.last_recalled.isoformat() if self.last_recalled else None,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Episode":
        return cls(
            id=data.get("id", ""),
            event_type=data["event_type"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(timezone.utc),
            context=data.get("context", {}),
            outcome=data.get("outcome", {}),
            lesson=data.get("lesson", ""),
            importance=data.get("importance", 0.5),
            recall_count=data.get("recall_count", 0),
            last_recalled=datetime.fromisoformat(data["last_recalled"]) if data.get("last_recalled") else None,
        )
    
    def get_searchable_text(self) -> str:
        """Get text representation for semantic search."""
        parts = [
            f"Event: {self.event_type}",
            f"Lesson: {self.lesson}",
        ]
        
        # Add key context
        for key, value in self.context.items():
            parts.append(f"{key}: {value}")
        
        # Add key outcomes
        for key, value in self.outcome.items():
            parts.append(f"{key}: {value}")
        
        return " | ".join(parts)


@dataclass
class Knowledge:
    """
    A semantic memory - accumulated knowledge about a topic.
    
    Semantic memories capture:
    - What is known (topic, insight)
    - How confident we are (confidence, evidence_count)
    - How it was learned (source_episodes)
    """
    # Knowledge identification
    topic: str  # e.g., "session_performance", "filter_effectiveness", "regime_behavior"
    insight: str  # The actual knowledge
    
    # Confidence and evidence
    confidence: float = 0.5  # 0-1
    evidence_count: int = 0  # How many observations support this
    
    # Source tracking
    source_episodes: list[str] = field(default_factory=list)  # Episode IDs
    
    # Metadata
    id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Embedding for semantic search
    embedding: Optional[list[float]] = None
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "topic": self.topic,
            "insight": self.insight,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "source_episodes": self.source_episodes,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Knowledge":
        return cls(
            id=data.get("id", ""),
            topic=data["topic"],
            insight=data["insight"],
            confidence=data.get("confidence", 0.5),
            evidence_count=data.get("evidence_count", 0),
            source_episodes=data.get("source_episodes", []),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            last_updated=datetime.fromisoformat(data["last_updated"]) if data.get("last_updated") else datetime.now(timezone.utc),
        )
    
    def update_with_evidence(self, episode_id: str, new_confidence: float) -> None:
        """Update knowledge with new evidence."""
        self.evidence_count += 1
        self.source_episodes.append(episode_id)
        
        # Update confidence with exponential moving average
        alpha = 0.2  # Weight for new evidence
        self.confidence = (1 - alpha) * self.confidence + alpha * new_confidence
        
        self.last_updated = datetime.now(timezone.utc)
    
    def get_searchable_text(self) -> str:
        """Get text representation for semantic search."""
        return f"Topic: {self.topic} | Insight: {self.insight}"


@dataclass
class Procedure:
    """
    A procedural memory - a learned behavior/action pattern.
    
    Procedural memories capture:
    - When to apply (trigger conditions)
    - What to do (action)
    - How well it works (success_rate)
    """
    # Procedure identification
    trigger: str  # When to apply, e.g., "regime is trending_up and confidence > 0.7"
    action: str  # What to do, e.g., "increase position size by 1.5x"
    
    # Performance tracking
    success_rate: float = 0.5  # 0-1
    times_applied: int = 0
    times_successful: int = 0
    
    # Examples
    examples: list[str] = field(default_factory=list)  # Episode IDs that demonstrate this
    
    # Metadata
    id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_applied: Optional[datetime] = None
    enabled: bool = True
    
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "trigger": self.trigger,
            "action": self.action,
            "success_rate": self.success_rate,
            "times_applied": self.times_applied,
            "times_successful": self.times_successful,
            "examples": self.examples,
            "created_at": self.created_at.isoformat(),
            "last_applied": self.last_applied.isoformat() if self.last_applied else None,
            "enabled": self.enabled,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Procedure":
        return cls(
            id=data.get("id", ""),
            trigger=data["trigger"],
            action=data["action"],
            success_rate=data.get("success_rate", 0.5),
            times_applied=data.get("times_applied", 0),
            times_successful=data.get("times_successful", 0),
            examples=data.get("examples", []),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(timezone.utc),
            last_applied=datetime.fromisoformat(data["last_applied"]) if data.get("last_applied") else None,
            enabled=data.get("enabled", True),
        )
    
    def record_application(self, successful: bool, episode_id: Optional[str] = None) -> None:
        """Record an application of this procedure."""
        self.times_applied += 1
        if successful:
            self.times_successful += 1
        self.success_rate = self.times_successful / self.times_applied
        self.last_applied = datetime.now(timezone.utc)
        
        if episode_id:
            self.examples.append(episode_id)
            # Keep only recent examples
            if len(self.examples) > 10:
                self.examples = self.examples[-10:]
    
    def get_searchable_text(self) -> str:
        """Get text representation for semantic search."""
        return f"Trigger: {self.trigger} | Action: {self.action}"


@dataclass
class MemoryQuery:
    """Query for memory retrieval."""
    query_text: str
    memory_types: list[MemoryType] = field(default_factory=lambda: list(MemoryType))
    
    # Filters
    event_types: Optional[list[str]] = None
    topics: Optional[list[str]] = None
    min_confidence: float = 0.0
    min_importance: float = 0.0
    
    # Time filters
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    
    # Result options
    top_k: int = 5
    include_embeddings: bool = False
