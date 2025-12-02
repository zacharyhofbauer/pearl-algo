"""
Tests for all LLM providers (Groq, OpenAI, Anthropic).
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import Mock, patch

from pearlalgo.agents.quant_research_agent import QuantResearchAgent
from pearlalgo.agents.langgraph_state import MarketData, Signal


@pytest.fixture
def sample_market_data():
    """Create sample market data."""
    from datetime import datetime, timezone
    return MarketData(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        open=4500.0,
        high=4510.0,
        low=4495.0,
        close=4505.0,
        volume=1000.0,
    )


@pytest.fixture
def sample_signal():
    """Create sample signal."""
    from datetime import datetime, timezone
    return Signal(
        symbol="ES",
        timestamp=datetime.now(timezone.utc),
        side="long",
        strategy_name="sr",
        confidence=0.75,
    )


def test_groq_initialization():
    """Test Groq LLM provider initialization."""
    groq_key = os.getenv("GROQ_API_KEY")
    config = {
        "llm": {
            "provider": "groq",
            "groq": {
                "api_key": groq_key if groq_key else "",  # Use empty string if not set
                "model": "mixtral-8x7b-32768",
            },
        },
        "strategy": {"default": "sr"},
    }
    
    agent = QuantResearchAgent(symbols=["ES"], strategy="sr", config=config)
    
    # If API key is set in environment, agent may initialize with LLM
    # If not set, should gracefully disable
    if groq_key:
        # Agent should initialize, use_llm may be True or False depending on key validity
        assert isinstance(agent.use_llm, bool)  # Should be a boolean
    else:
        # Without key, should gracefully disable
        assert agent.use_llm == False


def test_openai_initialization():
    """Test OpenAI LLM provider initialization."""
    config = {
        "llm": {
            "provider": "openai",
            "openai": {
                "api_key": os.getenv("OPENAI_API_KEY", "test_key"),
                "model": "gpt-4o",
            },
        },
        "strategy": {"default": "sr"},
    }
    
    agent = QuantResearchAgent(symbols=["ES"], strategy="sr", config=config)
    
    # Should handle missing key gracefully
    if not os.getenv("OPENAI_API_KEY"):
        assert agent.use_llm == False


def test_anthropic_initialization():
    """Test Anthropic LLM provider initialization."""
    config = {
        "llm": {
            "provider": "anthropic",
            "anthropic": {
                "api_key": os.getenv("ANTHROPIC_API_KEY", "test_key"),
                "model": "claude-3-opus-20240229",
            },
        },
        "strategy": {"default": "sr"},
    }
    
    agent = QuantResearchAgent(symbols=["ES"], strategy="sr", config=config)
    
    # Should handle missing key gracefully
    if not os.getenv("ANTHROPIC_API_KEY"):
        assert agent.use_llm == False


def test_llm_fallback_on_missing_key():
    """Test that LLM gracefully disables when API key is missing."""
    config = {
        "llm": {
            "provider": "groq",
            "groq": {
                "api_key": "",  # Empty key
                "model": "mixtral-8x7b-32768",
            },
        },
        "strategy": {"default": "sr"},
    }
    
    agent = QuantResearchAgent(symbols=["ES"], strategy="sr", config=config)
    # Should disable LLM when key is missing
    assert agent.use_llm == False


def test_llm_provider_switching():
    """Test switching between LLM providers."""
    symbols = ["ES"]
    strategy = "sr"
    
    # Test Groq
    config_groq = {
        "llm": {"provider": "groq", "groq": {"api_key": "test", "model": "mixtral-8x7b-32768"}},
        "strategy": {"default": "sr"},
    }
    agent_groq = QuantResearchAgent(symbols=symbols, strategy=strategy, config=config_groq)
    
    # Test OpenAI
    config_openai = {
        "llm": {"provider": "openai", "openai": {"api_key": "test", "model": "gpt-4o"}},
        "strategy": {"default": "sr"},
    }
    agent_openai = QuantResearchAgent(symbols=symbols, strategy=strategy, config=config_openai)
    
    # Test Anthropic
    config_anthropic = {
        "llm": {"provider": "anthropic", "anthropic": {"api_key": "test", "model": "claude-3-opus-20240229"}},
        "strategy": {"default": "sr"},
    }
    agent_anthropic = QuantResearchAgent(symbols=symbols, strategy=strategy, config=config_anthropic)
    
    # All should initialize (may disable LLM if keys invalid, but shouldn't crash)
    assert agent_groq is not None
    assert agent_openai is not None
    assert agent_anthropic is not None

