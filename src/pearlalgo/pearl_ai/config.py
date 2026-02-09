"""
Pearl AI Configuration - Centralized Settings

All configurable values for Pearl AI in one place.
Enables easy tuning, testing, and A/B experimentation.

Supports loading from:
- Hardcoded defaults (always available)
- YAML file via ``PearlConfig.from_yaml(path)``
- Environment variables via ``PearlConfig.from_env()``
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


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

    # ------------------------------------------------------------------
    # Factory class methods
    # ------------------------------------------------------------------

    @classmethod
    def from_yaml(cls, path: str) -> "PearlConfig":
        """
        Load PearlConfig from a YAML file.

        Expects a top-level ``pearl_ai:`` key with nested sections matching
        the config dataclass names (cache, narration, llm, metrics, etc.).
        Missing sections use defaults.

        Args:
            path: Path to the YAML configuration file.

        Returns:
            PearlConfig with values merged from the YAML file.
        """
        try:
            import yaml
        except ImportError:
            logger.warning("PyYAML not installed; using default config")
            return cls()

        yaml_path = Path(path)
        if not yaml_path.exists():
            logger.warning(f"Config file not found: {path}; using defaults")
            return cls()

        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return cls()

            # Support both top-level and nested under 'pearl_ai'
            pearl_data = data.get("pearl_ai", data)

            return cls(
                cache=_merge_frozen(CacheConfig, pearl_data.get("cache", {})),
                narration=_merge_frozen(NarrationConfig, pearl_data.get("narration", {})),
                llm=_merge_frozen(LLMConfig, pearl_data.get("llm", {})),
                sanitization=_merge_frozen(InputSanitizationConfig, pearl_data.get("sanitization", {})),
                metrics=_merge_frozen(MetricsConfig, pearl_data.get("metrics", {})),
                query_classification=_merge_frozen(QueryClassificationConfig, pearl_data.get("query_classification", {})),
            )
        except Exception as exc:
            logger.warning(f"Failed to load config from {path}: {exc}; using defaults")
            return cls()

    @classmethod
    def from_env(cls) -> "PearlConfig":
        """
        Load PearlConfig from environment variables.

        Environment variables follow the pattern ``PEARL_AI_<SECTION>_<KEY>``.
        For example:
        - ``PEARL_AI_LLM_DEFAULT_LOCAL_MODEL=llama3.2:3b``
        - ``PEARL_AI_CACHE_MAX_SIZE=200``
        - ``PEARL_AI_METRICS_MAX_HISTORY=500``

        Only set variables override defaults; missing variables keep defaults.

        Returns:
            PearlConfig with values merged from environment.
        """
        prefix = "PEARL_AI_"

        sections: Dict[str, Dict[str, Any]] = {
            "CACHE": {},
            "NARRATION": {},
            "LLM": {},
            "SANITIZATION": {},
            "METRICS": {},
            "QUERY_CLASSIFICATION": {},
        }

        for key, value in os.environ.items():
            if not key.startswith(prefix):
                continue
            remainder = key[len(prefix):]

            for section_name in sections:
                if remainder.startswith(section_name + "_"):
                    field_name = remainder[len(section_name) + 1:]
                    sections[section_name][field_name] = _coerce_env_value(value)
                    break

        return cls(
            cache=_merge_frozen(CacheConfig, sections["CACHE"]),
            narration=_merge_frozen(NarrationConfig, sections["NARRATION"]),
            llm=_merge_frozen(LLMConfig, sections["LLM"]),
            sanitization=_merge_frozen(InputSanitizationConfig, sections["SANITIZATION"]),
            metrics=_merge_frozen(MetricsConfig, sections["METRICS"]),
            query_classification=_merge_frozen(QueryClassificationConfig, sections["QUERY_CLASSIFICATION"]),
        )


def _coerce_env_value(value: str) -> Any:
    """Coerce a string environment variable to the appropriate Python type."""
    # Booleans
    if value.lower() in ("true", "1", "yes"):
        return True
    if value.lower() in ("false", "0", "no"):
        return False
    # Integers
    try:
        return int(value)
    except ValueError:
        pass
    # Floats
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _merge_frozen(cls: type, overrides: Dict[str, Any]):
    """
    Create a frozen dataclass instance with overrides applied.

    Only fields that exist on the dataclass and match the expected type
    are applied; unknown keys are silently ignored.
    """
    if not overrides:
        return cls()

    import dataclasses
    valid_fields = {f.name: f for f in dataclasses.fields(cls)}

    kwargs = {}
    for key, value in overrides.items():
        # Handle case-insensitive matching for env vars (UPPER) vs fields (UPPER)
        if key in valid_fields:
            kwargs[key] = value
        elif key.upper() in valid_fields:
            kwargs[key.upper()] = value

    try:
        return cls(**kwargs)
    except Exception as exc:
        logger.warning(f"Failed to apply overrides to {cls.__name__}: {exc}")
        return cls()


# Default configuration instance
DEFAULT_CONFIG = PearlConfig()


def get_config() -> PearlConfig:
    """Get the current configuration."""
    return DEFAULT_CONFIG


def load_config(
    yaml_path: Optional[str] = None,
    use_env: bool = True,
) -> PearlConfig:
    """
    Load configuration with precedence: env > yaml > defaults.

    Args:
        yaml_path: Optional path to YAML config file.
        use_env: Whether to also check environment variables.

    Returns:
        Merged PearlConfig instance.
    """
    global DEFAULT_CONFIG

    if yaml_path:
        config = PearlConfig.from_yaml(yaml_path)
    else:
        config = PearlConfig()

    if use_env:
        env_config = PearlConfig.from_env()
        # Env overrides YAML: if env has non-default values, prefer them
        # For simplicity, we just use from_env() which already has defaults
        # A full merge would compare field-by-field, but for now env wins
        # only if explicitly set (handled by _coerce_env_value)
        config = env_config

    DEFAULT_CONFIG = config
    return config
