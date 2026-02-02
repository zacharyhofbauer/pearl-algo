"""
Pearl Memory - Context and Pattern Storage

Maintains conversation history, learns user patterns,
and provides context for AI responses.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from pathlib import Path
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ConversationMessage:
    """A single message in conversation history."""
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationMessage":
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=data.get("metadata", {}),
        )


@dataclass
class UserPattern:
    """Observed pattern in user behavior."""
    pattern_type: str  # "trading_time", "question_type", "preference", etc.
    observation: str
    confidence: float  # 0.0 to 1.0
    occurrences: int = 1
    first_seen: datetime = field(default_factory=datetime.now)
    last_seen: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pattern_type": self.pattern_type,
            "observation": self.observation,
            "confidence": self.confidence,
            "occurrences": self.occurrences,
            "first_seen": self.first_seen.isoformat(),
            "last_seen": self.last_seen.isoformat(),
        }


class PearlMemory:
    """
    Long-term and short-term memory for Pearl AI.

    Stores:
    - Conversation history
    - Pearl's messages (narrations, insights)
    - User patterns and preferences
    - Trading session summaries
    """

    def __init__(self, storage_path: Optional[Path] = None):
        self.storage_path = storage_path or Path.home() / ".pearl" / "memory"
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Short-term: current session
        self.conversation_history: List[ConversationMessage] = []
        self.pearl_messages: List[Any] = []  # PearlMessage instances

        # Long-term: persisted
        self.user_patterns: Dict[str, UserPattern] = {}
        self.session_summaries: List[Dict[str, Any]] = []
        self.preferences: Dict[str, Any] = {}

        # Analytics
        self.question_counts: Dict[str, int] = defaultdict(int)
        self.topic_frequency: Dict[str, int] = defaultdict(int)

        # Load persisted data
        self._load_memory()

    def _load_memory(self):
        """Load persisted memory from disk."""
        try:
            patterns_file = self.storage_path / "patterns.json"
            if patterns_file.exists():
                data = json.loads(patterns_file.read_text())
                for key, pattern_data in data.items():
                    pattern_data["first_seen"] = datetime.fromisoformat(pattern_data["first_seen"])
                    pattern_data["last_seen"] = datetime.fromisoformat(pattern_data["last_seen"])
                    self.user_patterns[key] = UserPattern(**pattern_data)

            prefs_file = self.storage_path / "preferences.json"
            if prefs_file.exists():
                self.preferences = json.loads(prefs_file.read_text())

            summaries_file = self.storage_path / "session_summaries.json"
            if summaries_file.exists():
                self.session_summaries = json.loads(summaries_file.read_text())

            logger.info(f"Loaded memory: {len(self.user_patterns)} patterns, {len(self.session_summaries)} summaries")

        except Exception as e:
            logger.error(f"Error loading memory: {e}")

    def _save_memory(self):
        """Persist memory to disk."""
        try:
            patterns_data = {k: v.to_dict() for k, v in self.user_patterns.items()}
            (self.storage_path / "patterns.json").write_text(json.dumps(patterns_data, indent=2))

            (self.storage_path / "preferences.json").write_text(json.dumps(self.preferences, indent=2))

            # Keep only last 30 days of summaries
            cutoff = datetime.now() - timedelta(days=30)
            recent_summaries = [
                s for s in self.session_summaries
                if datetime.fromisoformat(s.get("date", "2020-01-01")) > cutoff
            ]
            (self.storage_path / "session_summaries.json").write_text(json.dumps(recent_summaries, indent=2))

        except Exception as e:
            logger.error(f"Error saving memory: {e}")

    def add_user_message(self, content: str, metadata: Optional[Dict] = None):
        """Add a user message to conversation history."""
        message = ConversationMessage(
            role="user",
            content=content,
            metadata=metadata or {},
        )
        self.conversation_history.append(message)

        # Analyze for patterns
        self._analyze_user_message(content)

        # Keep history manageable
        if len(self.conversation_history) > 100:
            self.conversation_history = self.conversation_history[-50:]

    def add_assistant_message(self, content: str, metadata: Optional[Dict] = None):
        """Add Pearl's response to conversation history."""
        message = ConversationMessage(
            role="assistant",
            content=content,
            metadata=metadata or {},
        )
        self.conversation_history.append(message)

    def add_message(self, pearl_message: Any):
        """Add a PearlMessage to the message history."""
        self.pearl_messages.append(pearl_message)

        # Keep manageable
        if len(self.pearl_messages) > 500:
            self.pearl_messages = self.pearl_messages[-250:]

    def get_recent_messages(self, count: int = 10) -> List[Dict[str, Any]]:
        """Get recent conversation messages for context."""
        return [msg.to_dict() for msg in self.conversation_history[-count:]]

    def get_messages_by_type(self, message_type: str, limit: int = 10) -> List[Any]:
        """Get recent Pearl messages of a specific type."""
        filtered = [
            m for m in reversed(self.pearl_messages)
            if m.message_type == message_type
        ]
        return filtered[:limit]

    def get_user_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Get all observed user patterns."""
        return {k: v.to_dict() for k, v in self.user_patterns.items()}

    def _analyze_user_message(self, content: str):
        """Analyze user message for patterns."""
        content_lower = content.lower()

        # Track question types
        if "why" in content_lower:
            self._update_pattern("question_type", "why_questions", 0.7)
            self.question_counts["why"] += 1

        if "how" in content_lower:
            self._update_pattern("question_type", "how_questions", 0.7)
            self.question_counts["how"] += 1

        if any(word in content_lower for word in ["should", "would", "could"]):
            self._update_pattern("question_type", "advice_seeking", 0.6)
            self.question_counts["advice"] += 1

        # Track topics of interest
        topics = {
            "performance": ["pnl", "profit", "loss", "win rate", "performance"],
            "risk": ["risk", "drawdown", "stop", "position size"],
            "strategy": ["strategy", "setup", "signal", "entry", "exit"],
            "ai": ["ml", "filter", "prediction", "probability"],
        }

        for topic, keywords in topics.items():
            if any(kw in content_lower for kw in keywords):
                self.topic_frequency[topic] += 1
                self._update_pattern("topic_interest", f"interested_in_{topic}", 0.5)

        # Track timing patterns
        hour = datetime.now().hour
        if 6 <= hour < 10:
            self._update_pattern("active_time", "morning_active", 0.5)
        elif 10 <= hour < 14:
            self._update_pattern("active_time", "midday_active", 0.5)
        elif 14 <= hour < 18:
            self._update_pattern("active_time", "afternoon_active", 0.5)

    def _update_pattern(self, pattern_type: str, observation: str, confidence_delta: float):
        """Update or create a user pattern."""
        key = f"{pattern_type}:{observation}"

        if key in self.user_patterns:
            pattern = self.user_patterns[key]
            pattern.occurrences += 1
            pattern.last_seen = datetime.now()
            # Increase confidence with more observations (asymptotic to 1.0)
            pattern.confidence = min(0.95, pattern.confidence + (1 - pattern.confidence) * confidence_delta * 0.1)
        else:
            self.user_patterns[key] = UserPattern(
                pattern_type=pattern_type,
                observation=observation,
                confidence=confidence_delta,
            )

        # Periodically save
        if len(self.user_patterns) % 10 == 0:
            self._save_memory()

    def set_preference(self, key: str, value: Any):
        """Set a user preference."""
        self.preferences[key] = value
        self._save_memory()

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a user preference."""
        return self.preferences.get(key, default)

    def add_session_summary(self, summary: Dict[str, Any]):
        """Add a trading session summary."""
        summary["date"] = datetime.now().isoformat()
        self.session_summaries.append(summary)
        self._save_memory()

    def get_context_for_query(self, query: str) -> Dict[str, Any]:
        """
        Build rich context for answering a query.
        Includes relevant history, patterns, and preferences.
        """
        return {
            "recent_conversation": self.get_recent_messages(5),
            "user_patterns": self.get_user_patterns(),
            "preferences": self.preferences,
            "topic_interests": dict(self.topic_frequency),
            "question_history": dict(self.question_counts),
            "recent_insights": [
                m.to_dict() for m in self.get_messages_by_type("insight", 3)
            ],
        }

    def get_personality_context(self) -> str:
        """
        Generate personality context based on learned patterns.
        Used to customize Pearl's communication style.
        """
        context_parts = []

        # Check question patterns
        if self.question_counts.get("why", 0) > 5:
            context_parts.append("The user often asks 'why' questions - provide reasoning.")

        if self.question_counts.get("advice", 0) > 3:
            context_parts.append("The user seeks advice - be more prescriptive.")

        # Check topic interests
        if self.topic_frequency.get("risk", 0) > 3:
            context_parts.append("User is risk-conscious - emphasize risk management.")

        if self.topic_frequency.get("ai", 0) > 3:
            context_parts.append("User is interested in AI/ML - explain model decisions.")

        # Check time patterns
        active_patterns = [
            p for k, p in self.user_patterns.items()
            if p.pattern_type == "active_time" and p.confidence > 0.6
        ]
        if active_patterns:
            most_active = max(active_patterns, key=lambda p: p.confidence)
            context_parts.append(f"User is most active during {most_active.observation.replace('_', ' ')}.")

        return " ".join(context_parts) if context_parts else ""

    def clear_session(self):
        """Clear short-term memory (conversation) but keep patterns."""
        self.conversation_history = []
        self.pearl_messages = []

    def export_memory(self) -> Dict[str, Any]:
        """Export all memory for backup or analysis."""
        return {
            "patterns": {k: v.to_dict() for k, v in self.user_patterns.items()},
            "preferences": self.preferences,
            "session_summaries": self.session_summaries,
            "topic_frequency": dict(self.topic_frequency),
            "question_counts": dict(self.question_counts),
        }
