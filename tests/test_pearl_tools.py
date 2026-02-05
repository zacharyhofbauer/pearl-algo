"""
Tests for Pearl AI Tools (P2.1)

Tests tool execution, result formatting, output validation,
and error handling.
"""

import pytest
from unittest.mock import MagicMock, patch

from pearl_ai.tools import (
    ToolDefinition,
    ToolResult,
    ToolExecutor,
    PEARL_TOOLS,
    format_tool_result_for_llm,
    validate_tool_output,
    RegimePerformanceData,
    SimilarTradesData,
    PerformanceSummaryData,
)


class TestToolDefinition:
    """Tests for ToolDefinition dataclass."""

    def test_to_claude_format(self):
        """Should convert to Claude API format."""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={
                "param1": {"type": "string", "description": "A param"},
                "param2": {"type": "string", "description": "Optional param", "default": "value"},
            }
        )

        result = tool.to_claude_format()

        assert result["name"] == "test_tool"
        assert result["description"] == "A test tool"
        assert "input_schema" in result
        assert result["input_schema"]["type"] == "object"
        assert "param1" in result["input_schema"]["properties"]
        assert result["input_schema"]["required"] == ["param1"]

    def test_to_claude_format_respects_required_override(self):
        """Explicit required list should be honored."""
        tool = ToolDefinition(
            name="test_tool",
            description="A test tool",
            parameters={
                "param1": {"type": "string", "description": "A param"},
                "param2": {"type": "string", "description": "Another param"},
            },
            required=["param2"],
        )

        result = tool.to_claude_format()

        assert result["input_schema"]["required"] == ["param2"]


class TestToolResult:
    """Tests for ToolResult dataclass."""

    def test_to_dict_success(self):
        """Should serialize successful result."""
        result = ToolResult(success=True, data={"key": "value"})
        d = result.to_dict()

        assert d["success"] is True
        assert d["data"]["key"] == "value"
        assert d["error"] is None

    def test_to_dict_failure(self):
        """Should serialize failed result."""
        result = ToolResult(success=False, data=None, error="Something went wrong")
        d = result.to_dict()

        assert d["success"] is False
        assert d["data"] is None
        assert d["error"] == "Something went wrong"


class TestPearlToolsDefinitions:
    """Tests for PEARL_TOOLS definitions."""

    def test_all_tools_have_name(self):
        """All tools should have a name."""
        for tool in PEARL_TOOLS:
            assert tool.name
            assert len(tool.name) > 0

    def test_all_tools_have_description(self):
        """All tools should have a description."""
        for tool in PEARL_TOOLS:
            assert tool.description
            assert len(tool.description) > 10

    def test_expected_tools_exist(self):
        """Should have all expected tools defined."""
        tool_names = {t.name for t in PEARL_TOOLS}

        expected = {
            "get_regime_performance",
            "get_similar_trades",
            "get_direction_performance",
            "get_hourly_performance",
            "get_performance_summary",
            "explain_rejection",
            "get_regime_breakdown",
            "get_streak_stats",
        }

        assert expected.issubset(tool_names)

    def test_tool_required_fields(self):
        """Required fields should match tool definitions."""
        by_name = {tool.name: tool.to_claude_format() for tool in PEARL_TOOLS}
        assert by_name["get_regime_performance"]["input_schema"]["required"] == ["regime"]
        assert by_name["get_similar_trades"]["input_schema"]["required"] == ["direction"]


class TestToolExecutor:
    """Tests for ToolExecutor."""

    @pytest.fixture
    def mock_data_access(self):
        """Create a mock data access."""
        mock = MagicMock()
        mock.get_regime_performance.return_value = {
            "regime": "trending",
            "days": 30,
            "total_trades": 20,
            "wins": 12,
            "win_rate": 0.6,
            "avg_pnl": 15.5,
            "total_pnl": 310.0,
        }
        mock.get_similar_trades.return_value = [
            {"direction": "long", "pnl": 50, "is_win": True, "exit_reason": "target"},
            {"direction": "long", "pnl": -25, "is_win": False, "exit_reason": "stop"},
        ]
        mock.get_performance_summary.return_value = {
            "days": 7,
            "total_trades": 15,
            "wins": 9,
            "win_rate": 0.6,
            "total_pnl": 225.0,
            "best_trade": 75.0,
            "worst_trade": -50.0,
        }
        return mock

    @pytest.fixture
    def executor(self, mock_data_access):
        """Create a tool executor with mock data."""
        return ToolExecutor(
            data_access=mock_data_access,
            current_state_getter=lambda: {"signal_rejections_24h": {}},
        )

    def test_get_tool_definitions(self, executor):
        """Should return tool definitions in Claude format."""
        definitions = executor.get_tool_definitions()

        assert len(definitions) > 0
        assert all("name" in d for d in definitions)
        assert all("description" in d for d in definitions)
        assert all("input_schema" in d for d in definitions)

    def test_execute_unknown_tool(self, executor):
        """Should return error for unknown tool."""
        result = executor.execute("nonexistent_tool", {})

        assert result.success is False
        assert "Unknown tool" in result.error

    def test_execute_regime_performance(self, executor):
        """Should execute regime performance tool."""
        result = executor.execute("get_regime_performance", {
            "regime": "trending",
            "days": 30,
        })

        assert result.success is True
        assert result.data["regime"] == "trending"
        assert result.data["total_trades"] == 20

    def test_execute_similar_trades(self, executor):
        """Should execute similar trades tool."""
        result = executor.execute("get_similar_trades", {
            "direction": "long",
            "limit": 5,
        })

        assert result.success is True
        assert "trades" in result.data
        assert len(result.data["trades"]) == 2

    def test_execute_performance_summary(self, executor):
        """Should execute performance summary tool."""
        result = executor.execute("get_performance_summary", {"days": 7})

        assert result.success is True
        assert result.data["total_trades"] == 15

    def test_execute_explain_rejection(self, executor):
        """Should execute explain rejection tool."""
        result = executor.execute("explain_rejection", {})

        assert result.success is True
        # Returns rejection info from state

    def test_handles_data_access_not_configured(self):
        """Should handle missing data access gracefully."""
        executor = ToolExecutor(data_access=None)

        result = executor.execute("get_regime_performance", {"regime": "trending"})

        assert result.success is False
        assert "not configured" in result.error

    def test_handles_exception_in_execution(self, executor, mock_data_access):
        """Should handle exceptions during tool execution."""
        mock_data_access.get_regime_performance.side_effect = Exception("DB error")

        result = executor.execute("get_regime_performance", {"regime": "trending"})

        assert result.success is False
        assert "DB error" in result.error


class TestOutputValidation:
    """Tests for output schema validation (P1.2)."""

    def test_validate_regime_performance(self):
        """Should validate regime performance output."""
        data = {
            "regime": "trending",
            "days": 30,
            "total_trades": 20,
            "wins": 12,
            "win_rate": 0.6,
            "avg_pnl": 15.5,
            "total_pnl": 310.0,
        }

        result = validate_tool_output("get_regime_performance", data)

        assert isinstance(result, RegimePerformanceData)
        assert result.regime == "trending"
        assert result.win_rate == 0.6

    def test_validate_clamps_win_rate(self):
        """Should clamp win rate to valid range."""
        data = {"regime": "trending", "win_rate": 1.5}  # Invalid > 1

        result = validate_tool_output("get_regime_performance", data)

        assert result.win_rate == 1.0  # Clamped

    def test_validate_similar_trades(self):
        """Should validate similar trades output."""
        data = {
            "trades": [
                {"direction": "long", "pnl": 50, "is_win": True, "exit_reason": "target"},
            ],
            "count": 1,
        }

        result = validate_tool_output("get_similar_trades", data)

        assert isinstance(result, SimilarTradesData)
        assert len(result.trades) == 1

    def test_validate_performance_summary(self):
        """Should validate performance summary output."""
        data = {
            "days": 7,
            "total_trades": 15,
            "wins": 9,
            "win_rate": 0.6,
            "total_pnl": 225.0,
        }

        result = validate_tool_output("get_performance_summary", data)

        assert isinstance(result, PerformanceSummaryData)

    def test_validate_returns_original_on_error(self):
        """Should return original data if validation fails."""
        invalid_data = {"unexpected": "format"}

        result = validate_tool_output("get_regime_performance", invalid_data)

        # Should return original dict, not raise
        assert result == invalid_data

    def test_validate_unknown_tool(self):
        """Should pass through data for unknown tools."""
        data = {"custom": "data"}

        result = validate_tool_output("unknown_tool", data)

        assert result == data


class TestFormatToolResult:
    """Tests for tool result formatting."""

    def test_format_failed_result(self):
        """Should format failed result with error."""
        result = ToolResult(success=False, data=None, error="API error")

        formatted = format_tool_result_for_llm("test_tool", result)

        assert "failed" in formatted.lower()
        assert "API error" in formatted

    def test_format_regime_performance(self):
        """Should format regime performance nicely."""
        result = ToolResult(
            success=True,
            data={
                "regime": "trending",
                "days": 30,
                "total_trades": 20,
                "wins": 12,
                "win_rate": 0.6,
                "avg_pnl": 15.5,
                "total_pnl": 310.0,
            }
        )

        formatted = format_tool_result_for_llm("get_regime_performance", result)

        assert "trending" in formatted.lower()
        assert "60%" in formatted or "12/20" in formatted
        assert "$310" in formatted

    def test_format_similar_trades(self):
        """Should format similar trades as list."""
        result = ToolResult(
            success=True,
            data={
                "trades": [
                    {"direction": "long", "pnl": 50, "is_win": True, "exit_reason": "target"},
                    {"direction": "long", "pnl": -25, "is_win": False, "exit_reason": "stop"},
                ],
                "count": 2,
            }
        )

        formatted = format_tool_result_for_llm("get_similar_trades", result)

        assert "Similar trades" in formatted
        assert "LONG" in formatted
        # Format is ${pnl:+.2f} so it outputs "$+50.00" format
        assert "$" in formatted and "50" in formatted

    def test_format_performance_summary(self):
        """Should format performance summary."""
        result = ToolResult(
            success=True,
            data={
                "days": 7,
                "total_trades": 15,
                "wins": 9,
                "win_rate": 0.6,
                "total_pnl": 225.0,
                "best_trade": 75.0,
                "worst_trade": -50.0,
            }
        )

        formatted = format_tool_result_for_llm("get_performance_summary", result)

        assert "7" in formatted and "days" in formatted.lower()
        assert "15" in formatted and "trades" in formatted.lower()
        assert "$225" in formatted

    def test_format_message_only(self):
        """Should return message if present in data."""
        result = ToolResult(
            success=True,
            data={"message": "No trades found in trending markets"}
        )

        formatted = format_tool_result_for_llm("get_regime_performance", result)

        assert formatted == "No trades found in trending markets"

    def test_format_unknown_tool_as_json(self):
        """Should format unknown tools as JSON."""
        result = ToolResult(
            success=True,
            data={"custom": "data", "number": 42}
        )

        formatted = format_tool_result_for_llm("custom_tool", result)

        assert '"custom"' in formatted
        assert "42" in formatted


class TestToolExecutorWithValidation:
    """Tests for tool executor with output validation integration."""

    @pytest.fixture
    def mock_data_access(self):
        mock = MagicMock()
        mock.get_regime_performance.return_value = {
            "regime": "trending",
            "win_rate": 1.5,  # Invalid value - should be clamped
        }
        return mock

    @pytest.fixture
    def executor(self, mock_data_access):
        return ToolExecutor(data_access=mock_data_access)

    def test_validates_output(self, executor):
        """Should validate and potentially fix output."""
        result = executor.execute("get_regime_performance", {"regime": "trending"})

        assert result.success is True
        # Win rate should be clamped to valid range
        assert result.data.get("win_rate", 0) <= 1.0
