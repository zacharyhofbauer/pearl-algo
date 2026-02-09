"""
Regression tests for Pearl AI config defaults.
"""

from pearlalgo.pearl_ai.config import get_config


def test_default_cache_config_values():
    config = get_config()
    assert config.cache.TTL_SHORT == 300
    assert config.cache.TTL_MEDIUM == 1800
    assert config.cache.TTL_LONG == 3600
    assert config.cache.MAX_SIZE == 100
    assert config.cache.MIN_RESPONSE_LENGTH == 20
    assert "coaching" in config.cache.NO_CACHE_PATTERNS


def test_default_llm_token_limits():
    config = get_config()
    assert config.llm.MAX_NARRATION_TOKENS == 60
    assert config.llm.MAX_QUICK_RESPONSE_TOKENS == 300
    assert config.llm.MAX_DEEP_RESPONSE_TOKENS == 1000
    assert config.llm.MAX_INSIGHT_TOKENS == 100
    assert config.llm.MAX_COACHING_TOKENS == 150
    assert config.llm.MAX_DAILY_REVIEW_TOKENS == 300
    assert config.llm.MAX_STREAM_TOKENS == 1000


def test_default_narration_cooldowns():
    config = get_config()
    assert config.narration.NARRATION_COOLDOWN == 5
    assert config.narration.INSIGHT_COOLDOWN == 1800
    assert config.narration.ML_WARNING_COOLDOWN == 7200
    assert config.narration.COACHING_COOLDOWN == 900
    assert config.narration.QUIET_ENGAGEMENT_THRESHOLD == 900
    assert config.narration.LOSING_STREAK_TRIGGER == 2
