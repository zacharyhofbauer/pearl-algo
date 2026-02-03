"""
Tests for PearlAIChat - Conversational AI for Telegram.

Tests cover:
- Configuration and initialization
- Rate limiting
- Context building for system prompts
- Error handling when OpenAI is unavailable
"""

from __future__ import annotations

import pytest
import time
from unittest.mock import MagicMock, patch, AsyncMock


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    def test_rate_limiter_allows_initial_request(self):
        """Rate limiter should allow requests under the limit."""
        from pearlalgo.ai.chat import RateLimiter
        
        limiter = RateLimiter(max_requests=5, window_seconds=60.0)
        assert limiter.is_allowed() is True

    def test_rate_limiter_blocks_after_limit(self):
        """Rate limiter should block requests after hitting the limit."""
        from pearlalgo.ai.chat import RateLimiter
        
        limiter = RateLimiter(max_requests=3, window_seconds=60.0)
        
        # Record 3 requests
        for _ in range(3):
            assert limiter.is_allowed() is True
            limiter.record()
        
        # 4th request should be blocked
        assert limiter.is_allowed() is False

    def test_rate_limiter_time_until_allowed(self):
        """Time until allowed should be positive when blocked."""
        from pearlalgo.ai.chat import RateLimiter
        
        limiter = RateLimiter(max_requests=1, window_seconds=60.0)
        limiter.record()
        
        wait_time = limiter.time_until_allowed()
        assert wait_time > 0
        assert wait_time <= 60.0

    def test_rate_limiter_resets_after_window(self):
        """Rate limiter should allow requests after window expires."""
        from pearlalgo.ai.chat import RateLimiter
        
        # Use very short window for testing
        limiter = RateLimiter(max_requests=1, window_seconds=0.1)
        limiter.record()
        
        assert limiter.is_allowed() is False
        
        # Wait for window to expire
        time.sleep(0.15)
        
        assert limiter.is_allowed() is True


class TestAIConfig:
    """Tests for AIConfig class."""

    def test_default_config(self):
        """Default config should have sensible values."""
        from pearlalgo.ai.chat import AIConfig
        
        config = AIConfig()
        assert config.enabled is True
        assert config.model == "gpt-4o-mini"
        assert config.max_response_length == 280
        assert config.rate_limit_per_minute == 5
        assert 0.0 <= config.temperature <= 1.0

    def test_config_from_dict(self):
        """Config should be creatable from dictionary."""
        from pearlalgo.ai.chat import AIConfig
        
        config_dict = {
            "enabled": False,
            "model": "gpt-4",
            "max_response_length": 500,
            "rate_limit_per_minute": 10,
            "temperature": 0.5,
        }
        
        config = AIConfig.from_dict(config_dict)
        
        assert config.enabled is False
        assert config.model == "gpt-4"
        assert config.max_response_length == 500
        assert config.rate_limit_per_minute == 10
        assert config.temperature == 0.5

    def test_config_from_empty_dict(self):
        """Config from empty dict should use defaults."""
        from pearlalgo.ai.chat import AIConfig
        
        config = AIConfig.from_dict({})
        
        assert config.enabled is True
        assert config.model == "gpt-4o-mini"


class TestPearlAIChat:
    """Tests for PearlAIChat class."""

    def test_initialization_with_default_config(self):
        """Should initialize with default configuration."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        
        assert chat.config.enabled is True
        assert chat.state_dir is None
        assert chat.rate_limiter is not None

    def test_initialization_with_custom_config(self):
        """Should initialize with custom configuration."""
        from pearlalgo.ai.chat import PearlAIChat, AIConfig
        
        config = AIConfig(enabled=False, rate_limit_per_minute=10)
        chat = PearlAIChat(config=config, state_dir="/tmp/test")
        
        assert chat.config.enabled is False
        assert chat.config.rate_limit_per_minute == 10
        assert chat.state_dir == "/tmp/test"

    def test_enabled_property_with_no_api_key(self):
        """Should report disabled when no API key is set."""
        from pearlalgo.ai.chat import PearlAIChat, AIConfig
        
        # Ensure no API key is set
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            # Reset the global client
            import pearlalgo.ai.chat as chat_module
            chat_module._openai_client = None
            
            chat = PearlAIChat()
            # The enabled property checks both config and API availability
            # With no API key, it should return False
            assert chat.enabled is False

    def test_enabled_property_when_disabled_in_config(self):
        """Should report disabled when disabled in config."""
        from pearlalgo.ai.chat import PearlAIChat, AIConfig
        
        config = AIConfig(enabled=False)
        chat = PearlAIChat(config=config)
        
        assert chat.enabled is False

    def test_build_system_prompt_with_empty_context(self):
        """Should build system prompt with default context."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        prompt = chat._build_system_prompt({})
        
        assert "Pearl" in prompt
        assert "trading" in prompt.lower()
        assert "Current trading context:" in prompt

    def test_build_system_prompt_with_pnl_context(self):
        """Should include P&L in system prompt."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        context = {
            "daily_pnl": 150.50,
            "wins_today": 3,
            "losses_today": 1,
        }
        prompt = chat._build_system_prompt(context)
        
        assert "+$150.50" in prompt
        assert "4" in prompt  # total trades
        assert "75%" in prompt  # win rate

    def test_build_system_prompt_with_streak(self):
        """Should include streak information in system prompt."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        context = {
            "win_streak": 3,
            "streak_type": "win",
        }
        prompt = chat._build_system_prompt(context)
        
        assert "3 wins in a row" in prompt

    def test_build_system_prompt_with_active_positions(self):
        """Should include active positions in system prompt."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        context = {"active_positions": 2}
        prompt = chat._build_system_prompt(context)
        
        assert "Active positions: 2" in prompt

    def test_build_system_prompt_with_session_status(self):
        """Should include session status in system prompt."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        
        # Test session open
        context = {"session_open": True}
        prompt = chat._build_system_prompt(context)
        assert "OPEN" in prompt
        
        # Test session closed
        context = {"session_open": False}
        prompt = chat._build_system_prompt(context)
        assert "CLOSED" in prompt

    def test_build_system_prompt_with_recent_trades(self):
        """Should include recent trades in system prompt."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        context = {
            "recent_trades": [
                {"direction": "long", "pnl": 50},
                {"direction": "short", "pnl": -25},
            ]
        }
        prompt = chat._build_system_prompt(context)
        
        assert "Recent trades:" in prompt
        assert "long +$50" in prompt
        # The format uses $-25 for negative values
        assert "short $-25" in prompt or "short -$25" in prompt


class TestPearlAIChatAsync:
    """Async tests for PearlAIChat."""

    @pytest.mark.asyncio
    async def test_chat_when_disabled(self):
        """Should return disabled message when AI is disabled."""
        from pearlalgo.ai.chat import PearlAIChat, AIConfig
        
        config = AIConfig(enabled=False)
        chat = PearlAIChat(config=config)
        
        response = await chat.chat("Hello")
        
        assert "disabled" in response.lower()

    @pytest.mark.asyncio
    async def test_chat_rate_limited(self):
        """Should return rate limit message when limit exceeded."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        chat.config.enabled = True
        
        # Exhaust rate limit
        for _ in range(chat.config.rate_limit_per_minute):
            chat.rate_limiter.record()
        
        response = await chat.chat("Hello")
        
        assert "try again" in response.lower() or "easy there" in response.lower()

    @pytest.mark.asyncio
    async def test_chat_without_api_key(self):
        """Should return unavailable message when API key is missing."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        chat.config.enabled = True
        
        # Reset global client and ensure no API key
        import pearlalgo.ai.chat as chat_module
        chat_module._openai_client = None
        
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}, clear=False):
            response = await chat.chat("Hello")
            assert "unavailable" in response.lower() or "api" in response.lower()

    @pytest.mark.asyncio
    async def test_chat_success_with_mock(self):
        """Should return AI response when OpenAI call succeeds."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        chat.config.enabled = True
        
        # Mock the OpenAI client
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Test response from AI"
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        
        import pearlalgo.ai.chat as chat_module
        chat_module._openai_client = mock_client
        
        response = await chat.chat("Hello", context={"daily_pnl": 100})
        
        assert response == "Test response from AI"
        assert chat._last_error is None

    @pytest.mark.asyncio
    async def test_chat_truncates_long_response(self):
        """Should truncate responses exceeding max length."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        chat.config.enabled = True
        chat.config.max_response_length = 50
        
        # Mock a long response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "A" * 100  # 100 chars
        
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = mock_response
        
        import pearlalgo.ai.chat as chat_module
        chat_module._openai_client = mock_client
        
        response = await chat.chat("Hello")
        
        assert len(response) <= 50
        assert response.endswith("...")

    @pytest.mark.asyncio
    async def test_chat_handles_api_error(self):
        """Should handle API errors gracefully."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        chat.config.enabled = True
        
        # Mock client that raises exception
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API Error")
        
        import pearlalgo.ai.chat as chat_module
        chat_module._openai_client = mock_client
        
        response = await chat.chat("Hello")
        
        assert "hiccup" in response.lower() or "error" in response.lower() or "again" in response.lower()
        assert chat._last_error is not None

    @pytest.mark.asyncio
    async def test_generate_insight_when_disabled(self):
        """Should return None when AI is disabled."""
        from pearlalgo.ai.chat import PearlAIChat, AIConfig
        
        config = AIConfig(enabled=False)
        chat = PearlAIChat(config=config)
        
        result = await chat.generate_insight("morning_briefing", {})
        
        assert result is None

    @pytest.mark.asyncio
    async def test_generate_insight_unknown_type(self):
        """Should return None for unknown insight types."""
        from pearlalgo.ai.chat import PearlAIChat
        
        chat = PearlAIChat()
        chat.config.enabled = True
        
        # Mock enabled check
        import pearlalgo.ai.chat as chat_module
        chat_module._openai_client = MagicMock()
        
        result = await chat.generate_insight("unknown_type", {})
        
        assert result is None


class TestGetAIChat:
    """Tests for the get_ai_chat singleton function."""

    def test_get_ai_chat_creates_instance(self):
        """Should create a new instance when none exists."""
        import pearlalgo.ai.chat as chat_module
        
        # Reset singleton
        chat_module._chat_instance = None
        
        chat = chat_module.get_ai_chat()
        
        assert chat is not None
        assert isinstance(chat, chat_module.PearlAIChat)

    def test_get_ai_chat_returns_same_instance(self):
        """Should return the same instance on subsequent calls."""
        import pearlalgo.ai.chat as chat_module
        
        # Reset singleton
        chat_module._chat_instance = None
        
        chat1 = chat_module.get_ai_chat()
        chat2 = chat_module.get_ai_chat()
        
        assert chat1 is chat2

    def test_get_ai_chat_with_config(self):
        """Should use provided config when creating instance."""
        import pearlalgo.ai.chat as chat_module
        
        # Reset singleton
        chat_module._chat_instance = None
        
        config = {"model": "gpt-4", "temperature": 0.5}
        chat = chat_module.get_ai_chat(config=config)
        
        assert chat.config.model == "gpt-4"
        assert chat.config.temperature == 0.5
