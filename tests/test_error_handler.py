"""
Tests for Error Handler.

Validates error detection and handling utilities.
"""

import pytest
from unittest.mock import Mock
from datetime import datetime, timezone

from pearlalgo.utils.error_handler import ErrorHandler


class TestIsConnectionError:
    """Test connection error detection."""

    def test_connection_error_detected(self):
        """Should detect ConnectionError."""
        error = ConnectionError("Connection refused")
        assert ErrorHandler.is_connection_error(error) is True

    def test_timeout_error_detected(self):
        """Should detect TimeoutError as connection error."""
        error = TimeoutError("Request timed out")
        assert ErrorHandler.is_connection_error(error) is True

    def test_network_keyword_detected(self):
        """Should detect network errors by keyword."""
        error = Exception("Network unreachable")
        assert ErrorHandler.is_connection_error(error) is True

    def test_reset_keyword_detected(self):
        """Should detect connection reset errors."""
        error = Exception("Connection reset by peer")
        assert ErrorHandler.is_connection_error(error) is True

    def test_regular_error_not_detected(self):
        """Should not detect regular errors as connection errors."""
        error = ValueError("Invalid data")
        assert ErrorHandler.is_connection_error(error) is False

    def test_empty_error_message(self):
        """Should handle empty error message."""
        error = Exception("")
        assert ErrorHandler.is_connection_error(error) is False


class TestIsConnectionErrorFromData:
    """Test connection error detection from data state."""

    def test_mock_provider_returns_false(self):
        """Should return False for mock providers."""
        provider = Mock()
        type(provider).__name__ = "MockDataProvider"
        
        market_data = {"df": Mock(empty=True), "latest_bar": None}
        
        result = ErrorHandler.is_connection_error_from_data(
            market_data, 
            data_provider=provider
        )
        assert result is False

    def test_no_provider_returns_false(self):
        """Should return False when no provider given."""
        market_data = {"df": Mock(empty=True), "latest_bar": None}
        
        result = ErrorHandler.is_connection_error_from_data(market_data)
        assert result is False

    def test_ibkr_provider_disconnected(self):
        """Should detect disconnected IBKR provider."""
        provider = Mock()
        type(provider).__name__ = "IBKRProvider"
        provider._executor = Mock()
        provider._executor.is_connected = Mock(return_value=False)
        
        market_data = {"df": Mock(empty=True), "latest_bar": None}
        
        result = ErrorHandler.is_connection_error_from_data(
            market_data,
            data_provider=provider
        )
        assert result is True

    def test_ibkr_provider_connected(self):
        """Should not flag connected IBKR provider."""
        provider = Mock()
        type(provider).__name__ = "IBKRProvider"
        provider._executor = Mock()
        provider._executor.is_connected = Mock(return_value=True)
        
        market_data = {"df": Mock(empty=False), "latest_bar": {"close": 17500}}
        
        result = ErrorHandler.is_connection_error_from_data(
            market_data,
            data_provider=provider
        )
        assert result is False


class TestHandleDataFetchError:
    """Test data fetch error handling."""

    def test_returns_error_info(self):
        """Should return error info dictionary."""
        error = ValueError("Bad data")
        
        result = ErrorHandler.handle_data_fetch_error(error)
        
        assert "error" in result
        assert "error_type" in result
        assert "is_connection_error" in result
        assert result["error"] == "Bad data"
        assert result["error_type"] == "ValueError"
        assert result["is_connection_error"] is False

    def test_connection_error_flagged(self):
        """Should flag connection errors."""
        error = ConnectionError("Connection refused")
        
        result = ErrorHandler.handle_data_fetch_error(error)
        
        assert result["is_connection_error"] is True

    def test_includes_context(self):
        """Should include context in error info."""
        error = ValueError("Error")
        context = {"symbol": "NQ", "attempt": 3}
        
        result = ErrorHandler.handle_data_fetch_error(error, context=context)
        
        assert result["context"] == context

    def test_handles_none_context(self):
        """Should handle None context."""
        error = ValueError("Error")
        
        result = ErrorHandler.handle_data_fetch_error(error, context=None)
        
        assert result["context"] == {}


class TestHandleTelegramError:
    """Test Telegram error handling."""

    def test_handles_telegram_error(self):
        """Should handle telegram errors without raising."""
        error = Exception("Telegram API error")
        
        # Should not raise
        ErrorHandler.handle_telegram_error(error, "signal_notification")

    def test_handles_various_notification_types(self):
        """Should handle various notification types."""
        error = Exception("Error")
        
        for notification_type in ["signal", "dashboard", "heartbeat", "error_alert"]:
            ErrorHandler.handle_telegram_error(error, notification_type)
