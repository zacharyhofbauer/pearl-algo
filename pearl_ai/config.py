"""
Pearl AI Configuration - Centralized Settings

All configurable values for Pearl AI in one place.
Enables easy tuning, testing, and A/B experimentation.
"""

from dataclasses import dataclass, field
from typing import List, Set


@dataclass(frozen=True)
class CacheConfig:
    """Cache configuration settings."""

    # TTL values (seconds)
    TTL_SHORT: int = 300        # 5 minutes - state-dependent queries
    TTL_MEDIUM: int = 1800      # 30 minutes - general questions
    TTL_LONG: int = 3600        # 1 hour - static content

    # Cache size
    MAX_SIZE: int = 100

    # Minimum response length to cache
    MIN_RESPONSE_LENGTH: int = 20

    # Patterns that should skip cache (personalized/dynamic content)
    NO_CACHE_PATTERNS: tuple = (
        "coaching",
        "advice",
        "suggest",
        "should i",
        "what should",
        "help me",
        "streak",
        "consecutive",
    )

    # Request deduplication (milliseconds)
    DEDUP_ENABLED: bool = True
    DEDUP_WINDOW_MS: int = 2000


@dataclass(frozen=True)
class NarrationConfig:
    """Narration and proactive message configuration."""

    # Cooldowns (seconds)
    NARRATION_COOLDOWN: int = 5
    INSIGHT_COOLDOWN: int = 1800        # 30 minutes
    ML_WARNING_COOLDOWN: int = 7200     # 2 hours
    COACHING_COOLDOWN: int = 900        # 15 minutes
    QUIET_ENGAGEMENT_THRESHOLD: int = 900  # 15 minutes

    # Extra long cooldown for neutral ML warnings (seconds)
    ML_NEUTRAL_WARNING_COOLDOWN: int = 14400  # 4 hours

    # Losing streak trigger threshold
    LOSING_STREAK_TRIGGER: int = 2

    # Events that always trigger narration regardless of cooldown
    ALWAYS_NARRATE_EVENTS: frozenset = frozenset({
        "signal_generated",
        "trade_entered",
        "trade_exited",
        "circuit_breaker_triggered",
        "direction_blocked",
    })


@dataclass(frozen=True)
class LLMConfig:
    """LLM configuration settings."""

    # Default models
    DEFAULT_LOCAL_MODEL: str = "llama3.1:8b"
    DEFAULT_OLLAMA_HOST: str = "http://localhost:11434"

    # Token limits
    MAX_NARRATION_TOKENS: int = 60
    MAX_QUICK_RESPONSE_TOKENS: int = 300
    MAX_DEEP_RESPONSE_TOKENS: int = 1000
    MAX_INSIGHT_TOKENS: int = 100
    MAX_COACHING_TOKENS: int = 150
    MAX_DAILY_REVIEW_TOKENS: int = 300
    MAX_STREAM_TOKENS: int = 1000


@dataclass(frozen=True)
class InputSanitizationConfig:
    """Input sanitization configuration."""

    # Maximum message length (characters)
    MAX_MESSAGE_LENGTH: int = 4000

    # Patterns to strip from input (potential injection markers)
    INJECTION_PATTERNS: tuple = (
        "```system",
        "```assistant",
        "```user",
        "[INST]",
        "[/INST]",
        "<<SYS>>",
        "<</SYS>>",
        "<|im_start|>",
        "<|im_end|>",
        "Human:",
        "Assistant:",
        "System:",
    )

    # Additional patterns that indicate injection attempts
    SUSPICIOUS_PATTERNS: tuple = (
        "ignore previous",
        "ignore all previous",
        "disregard previous",
        "forget your instructions",
        "new instructions",
        "override your",
        "you are now",
        "act as if",
        "pretend you are",
    )


@dataclass(frozen=True)
class MetricsConfig:
    """Metrics configuration settings."""

    # History limits
    MAX_HISTORY: int = 1000

    # Persistence frequency (save every N requests)
    PERSISTENCE_FREQUENCY: int = 100

    # Cost warning threshold (percentage of daily limit)
    COST_WARNING_THRESHOLD: float = 0.8


@dataclass(frozen=True)
class QueryClassificationConfig:
    """Query classification settings."""

    # Keywords that indicate deep analysis needed
    DEEP_KEYWORDS: tuple = (
        "why", "explain", "analyze", "should i", "what if",
        "strategy", "improve", "pattern", "trend", "review",
        "coaching", "advice", "recommend", "optimize", "backtest",
        "compare", "similar", "history", "regime", "performance",
    )

    # Keywords that indicate quick response is sufficient
    QUICK_KEYWORDS: tuple = (
        "what is", "current", "status", "how many", "last",
        "price", "position", "pnl", "today",
    )

    # Word count threshold for auto-classification
    WORD_COUNT_THRESHOLD: int = 10


@dataclass
class PearlConfig:
    """Master configuration for Pearl AI."""

    cache: CacheConfig = field(default_factory=CacheConfig)
    narration: NarrationConfig = field(default_factory=NarrationConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    sanitization: InputSanitizationConfig = field(default_factory=InputSanitizationConfig)
    metrics: MetricsConfig = field(default_factory=MetricsConfig)
    query_classification: QueryClassificationConfig = field(default_factory=QueryClassificationConfig)


# Default configuration instance
DEFAULT_CONFIG = PearlConfig()


def get_config() -> PearlConfig:
    """Get the current configuration."""
    return DEFAULT_CONFIG
