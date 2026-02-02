"""
Pearl AI Tools - Structured Function Calling

Defines tools for Claude function calling, enabling structured
queries with validated arguments and reliable outputs.
"""

from typing import Dict, List, Any, Optional, Callable, Awaitable, Union
from dataclasses import dataclass
import logging
import json
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


# ================================================================
# OUTPUT VALIDATION MODELS (P1.2)
# ================================================================

class RegimePerformanceData(BaseModel):
    """Validated output for regime performance tool."""
    regime: str
    days: int = 30
    total_trades: int = 0
    wins: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    message: Optional[str] = None

    @field_validator("win_rate", mode="before")
    @classmethod
    def clamp_win_rate(cls, v):
        """Ensure win rate is between 0 and 1."""
        if v is None:
            return 0.0
        return max(0.0, min(1.0, float(v)))


class TradeRecord(BaseModel):
    """Validated trade record."""
    direction: str = "unknown"
    pnl: float = 0.0
    is_win: bool = False
    exit_reason: str = "unknown"
    timestamp: Optional[str] = None


class SimilarTradesData(BaseModel):
    """Validated output for similar trades tool."""
    trades: List[TradeRecord] = Field(default_factory=list)
    count: int = 0
    message: Optional[str] = None


class DirectionPerformanceData(BaseModel):
    """Validated output for direction performance tool."""
    long: Optional[Dict[str, Any]] = None
    short: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class HourlyStats(BaseModel):
    """Statistics for a single hour."""
    trades: int = 0
    wins: int = 0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0


class HourlyPerformanceData(BaseModel):
    """Validated output for hourly performance tool."""
    hourly_data: Dict[str, HourlyStats] = Field(default_factory=dict)
    best_hour: Optional[Dict[str, Any]] = None
    worst_hour: Optional[Dict[str, Any]] = None
    message: Optional[str] = None


class PerformanceSummaryData(BaseModel):
    """Validated output for performance summary tool."""
    days: int = 7
    total_trades: int = 0
    wins: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0
    message: Optional[str] = None


class RejectionExplanationData(BaseModel):
    """Validated output for rejection explanation tool."""
    explanation: Optional[str] = None
    rejections_24h: Dict[str, int] = Field(default_factory=dict)
    ml_skipped: int = 0
    ml_passed: int = 0


class StreakStatsData(BaseModel):
    """Validated output for streak stats tool."""
    max_win_streak: int = 0
    max_loss_streak: int = 0
    current_streak: int = 0
    streak_type: str = "none"
    message: Optional[str] = None


# Union of all valid tool output types
ValidatedToolOutput = Union[
    RegimePerformanceData,
    SimilarTradesData,
    DirectionPerformanceData,
    HourlyPerformanceData,
    PerformanceSummaryData,
    RejectionExplanationData,
    StreakStatsData,
    Dict[str, Any],  # Fallback for other tools
]


def validate_tool_output(tool_name: str, data: Any) -> ValidatedToolOutput:
    """
    Validate tool output against the appropriate schema (P1.2).

    Args:
        tool_name: Name of the tool
        data: Raw output data

    Returns:
        Validated data model or original data if no validator exists
    """
    validators = {
        "get_regime_performance": RegimePerformanceData,
        "get_similar_trades": SimilarTradesData,
        "get_direction_performance": DirectionPerformanceData,
        "get_hourly_performance": HourlyPerformanceData,
        "get_performance_summary": PerformanceSummaryData,
        "explain_rejection": RejectionExplanationData,
        "get_streak_stats": StreakStatsData,
    }

    validator_class = validators.get(tool_name)
    if validator_class and isinstance(data, dict):
        try:
            return validator_class(**data)
        except Exception as e:
            logger.warning(f"Tool output validation failed for {tool_name}: {e}")
            return data

    return data


@dataclass
class ToolDefinition:
    """Definition of a Pearl AI tool."""
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for parameters

    def to_claude_format(self) -> Dict[str, Any]:
        """Convert to Claude API tool format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": self.parameters,
                "required": list(self.parameters.keys()),
            }
        }


@dataclass
class ToolResult:
    """Result of a tool execution."""
    success: bool
    data: Any
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
        }


# Tool Definitions
PEARL_TOOLS: List[ToolDefinition] = [
    ToolDefinition(
        name="get_regime_performance",
        description="Get win rate and P&L performance statistics for a specific market regime. "
                   "Use when user asks about performance in trending, ranging, or volatile markets.",
        parameters={
            "regime": {
                "type": "string",
                "description": "Market regime to analyze",
                "enum": ["trending", "ranging", "volatile", "low_volatility", "high_volatility"],
            },
            "days": {
                "type": "integer",
                "description": "Number of days to look back (default 30)",
                "default": 30,
            },
        },
    ),

    ToolDefinition(
        name="get_similar_trades",
        description="Find historical trades similar to the current context. "
                   "Use when user asks about similar setups, patterns, or past trades like this.",
        parameters={
            "direction": {
                "type": "string",
                "description": "Trade direction to filter by",
                "enum": ["long", "short"],
            },
            "regime": {
                "type": "string",
                "description": "Optional market regime filter",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of trades to return (default 5)",
                "default": 5,
            },
        },
    ),

    ToolDefinition(
        name="get_direction_performance",
        description="Compare performance between long and short trades. "
                   "Use when user asks about which direction performs better.",
        parameters={
            "days": {
                "type": "integer",
                "description": "Number of days to look back (default 30)",
                "default": 30,
            },
        },
    ),

    ToolDefinition(
        name="get_hourly_performance",
        description="Get performance breakdown by hour of day. "
                   "Use when user asks about best times to trade or performance by time.",
        parameters={
            "days": {
                "type": "integer",
                "description": "Number of days to look back (default 30)",
                "default": 30,
            },
        },
    ),

    ToolDefinition(
        name="get_performance_summary",
        description="Get overall trading performance summary. "
                   "Use when user asks about general performance, how they're doing, or stats.",
        parameters={
            "days": {
                "type": "integer",
                "description": "Number of days to look back (default 7)",
                "default": 7,
            },
        },
    ),

    ToolDefinition(
        name="explain_rejection",
        description="Explain why signals were rejected today. "
                   "Use when user asks why trades weren't taken or signals were skipped.",
        parameters={},
    ),

    ToolDefinition(
        name="get_regime_breakdown",
        description="Get performance breakdown across all market regimes. "
                   "Use when comparing performance across different market conditions.",
        parameters={
            "days": {
                "type": "integer",
                "description": "Number of days to look back (default 30)",
                "default": 30,
            },
        },
    ),

    ToolDefinition(
        name="get_streak_stats",
        description="Get win/loss streak statistics. "
                   "Use when user asks about streaks, best/worst runs.",
        parameters={
            "days": {
                "type": "integer",
                "description": "Number of days to look back (default 30)",
                "default": 30,
            },
        },
    ),
]


class ToolExecutor:
    """
    Executes Pearl AI tools with data access and state.

    Connects tool definitions to actual data sources.
    """

    def __init__(
        self,
        data_access: Any = None,  # TradeDataAccess
        current_state_getter: Optional[Callable[[], Dict[str, Any]]] = None,
        rejection_explainer: Optional[Callable[[Dict[str, Any]], str]] = None,
    ):
        """
        Initialize tool executor.

        Args:
            data_access: TradeDataAccess instance for historical queries
            current_state_getter: Function to get current trading state
            rejection_explainer: Function to explain signal rejections
        """
        self.data_access = data_access
        self.get_current_state = current_state_getter or (lambda: {})
        self.explain_rejections = rejection_explainer

        # Map tool names to executor methods
        self._executors: Dict[str, Callable[[Dict[str, Any]], ToolResult]] = {
            "get_regime_performance": self._exec_regime_performance,
            "get_similar_trades": self._exec_similar_trades,
            "get_direction_performance": self._exec_direction_performance,
            "get_hourly_performance": self._exec_hourly_performance,
            "get_performance_summary": self._exec_performance_summary,
            "explain_rejection": self._exec_explain_rejection,
            "get_regime_breakdown": self._exec_regime_breakdown,
            "get_streak_stats": self._exec_streak_stats,
        }

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Get tool definitions in Claude API format."""
        return [tool.to_claude_format() for tool in PEARL_TOOLS]

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResult:
        """
        Execute a tool by name with output validation (P1.2).

        Args:
            tool_name: Name of the tool to execute
            arguments: Tool arguments

        Returns:
            ToolResult with success/data/error (data is validated)
        """
        executor = self._executors.get(tool_name)

        if not executor:
            return ToolResult(
                success=False,
                data=None,
                error=f"Unknown tool: {tool_name}",
            )

        try:
            result = executor(arguments)

            # Validate output (P1.2)
            if result.success and result.data:
                validated_data = validate_tool_output(tool_name, result.data)
                # Convert Pydantic model to dict if needed
                if hasattr(validated_data, "model_dump"):
                    result.data = validated_data.model_dump()
                elif hasattr(validated_data, "dict"):
                    result.data = validated_data.dict()

            return result
        except Exception as e:
            logger.error(f"Tool execution error ({tool_name}): {e}")
            return ToolResult(
                success=False,
                data=None,
                error=str(e),
            )

    def _exec_regime_performance(self, args: Dict[str, Any]) -> ToolResult:
        """Execute get_regime_performance tool."""
        if not self.data_access:
            return ToolResult(False, None, "Data access not configured")

        regime = args.get("regime", "trending")
        days = args.get("days", 30)

        data = self.data_access.get_regime_performance(regime, days)

        if not data or data.get("total_trades", 0) == 0:
            return ToolResult(
                success=True,
                data={"message": f"No trades found in {regime} markets in the last {days} days"},
            )

        return ToolResult(success=True, data=data)

    def _exec_similar_trades(self, args: Dict[str, Any]) -> ToolResult:
        """Execute get_similar_trades tool."""
        if not self.data_access:
            return ToolResult(False, None, "Data access not configured")

        direction = args.get("direction", "long")
        regime = args.get("regime")
        limit = args.get("limit", 5)

        trades = self.data_access.get_similar_trades(direction, regime, limit=limit)

        if not trades:
            return ToolResult(
                success=True,
                data={"message": f"No similar {direction} trades found"},
            )

        return ToolResult(success=True, data={"trades": trades, "count": len(trades)})

    def _exec_direction_performance(self, args: Dict[str, Any]) -> ToolResult:
        """Execute get_direction_performance tool."""
        if not self.data_access:
            return ToolResult(False, None, "Data access not configured")

        days = args.get("days", 30)
        data = self.data_access.get_direction_performance(days)

        if not data:
            return ToolResult(
                success=True,
                data={"message": f"No trades found in the last {days} days"},
            )

        return ToolResult(success=True, data=data)

    def _exec_hourly_performance(self, args: Dict[str, Any]) -> ToolResult:
        """Execute get_hourly_performance tool."""
        if not self.data_access:
            return ToolResult(False, None, "Data access not configured")

        days = args.get("days", 30)
        data = self.data_access.get_hourly_performance(days)

        if not data:
            return ToolResult(
                success=True,
                data={"message": f"No trades found in the last {days} days"},
            )

        # Find best and worst hours
        best_hour = max(data.items(), key=lambda x: x[1].get("avg_pnl", 0))
        worst_hour = min(data.items(), key=lambda x: x[1].get("avg_pnl", 0))

        return ToolResult(
            success=True,
            data={
                "hourly_data": data,
                "best_hour": {"hour": best_hour[0], **best_hour[1]},
                "worst_hour": {"hour": worst_hour[0], **worst_hour[1]},
            },
        )

    def _exec_performance_summary(self, args: Dict[str, Any]) -> ToolResult:
        """Execute get_performance_summary tool."""
        if not self.data_access:
            return ToolResult(False, None, "Data access not configured")

        days = args.get("days", 7)
        data = self.data_access.get_performance_summary(days)

        if not data or data.get("total_trades", 0) == 0:
            return ToolResult(
                success=True,
                data={"message": f"No trades found in the last {days} days"},
            )

        return ToolResult(success=True, data=data)

    def _exec_explain_rejection(self, args: Dict[str, Any]) -> ToolResult:
        """Execute explain_rejection tool."""
        state = self.get_current_state()

        if self.explain_rejections:
            explanation = self.explain_rejections(state)
            return ToolResult(success=True, data={"explanation": explanation})

        # Fallback: parse state for rejection info
        rejections = state.get("signal_rejections_24h", {})
        ml_filter = state.get("ai_status", {}).get("ml_filter", {})

        return ToolResult(
            success=True,
            data={
                "rejections_24h": rejections,
                "ml_skipped": ml_filter.get("skipped", 0),
                "ml_passed": ml_filter.get("passed", 0),
            },
        )

    def _exec_regime_breakdown(self, args: Dict[str, Any]) -> ToolResult:
        """Execute get_regime_breakdown tool."""
        if not self.data_access:
            return ToolResult(False, None, "Data access not configured")

        days = args.get("days", 30)
        data = self.data_access.get_regime_breakdown(days)

        if not data:
            return ToolResult(
                success=True,
                data={"message": f"No regime data found in the last {days} days"},
            )

        return ToolResult(success=True, data=data)

    def _exec_streak_stats(self, args: Dict[str, Any]) -> ToolResult:
        """Execute get_streak_stats tool."""
        if not self.data_access:
            return ToolResult(False, None, "Data access not configured")

        days = args.get("days", 30)
        data = self.data_access.get_streak_stats(days)

        return ToolResult(success=True, data=data)


def format_tool_result_for_llm(tool_name: str, result: ToolResult) -> str:
    """
    Format tool result as string for LLM context.

    Args:
        tool_name: Name of the tool that was executed
        result: ToolResult from execution

    Returns:
        Formatted string for LLM consumption
    """
    if not result.success:
        return f"[Tool {tool_name} failed: {result.error}]"

    if isinstance(result.data, dict):
        if "message" in result.data:
            return result.data["message"]

        # Format nicely based on tool type
        if tool_name == "get_regime_performance":
            d = result.data
            wr = d.get("win_rate", 0) * 100
            return (
                f"In {d.get('regime', 'unknown')} markets (last {d.get('days', 30)} days): "
                f"{d.get('wins', 0)}/{d.get('total_trades', 0)} wins ({wr:.0f}%), "
                f"avg P&L ${d.get('avg_pnl', 0):.2f}, total ${d.get('total_pnl', 0):.2f}"
            )

        if tool_name == "get_similar_trades":
            trades = result.data.get("trades", [])
            if not trades:
                return "No similar trades found."

            lines = ["Similar trades:"]
            for t in trades[:5]:
                result_str = "WIN" if t.get("is_win") else "LOSS"
                lines.append(
                    f"- {t.get('direction', '?').upper()} ${t.get('pnl', 0):+.2f} "
                    f"({result_str}, {t.get('exit_reason', '?')})"
                )
            return "\n".join(lines)

        if tool_name == "get_direction_performance":
            lines = []
            for direction, stats in result.data.items():
                wr = stats.get("win_rate", 0) * 100
                lines.append(
                    f"{direction.upper()}: {stats.get('wins', 0)}/{stats.get('total_trades', 0)} wins "
                    f"({wr:.0f}%), ${stats.get('total_pnl', 0):.2f} total"
                )
            return "\n".join(lines) if lines else "No direction data available."

        if tool_name == "get_performance_summary":
            d = result.data
            wr = d.get("win_rate", 0) * 100
            return (
                f"Last {d.get('days', 7)} days: {d.get('total_trades', 0)} trades, "
                f"{wr:.0f}% win rate, ${d.get('total_pnl', 0):.2f} total P&L, "
                f"best trade ${d.get('best_trade', 0):.2f}, worst ${d.get('worst_trade', 0):.2f}"
            )

        # Default: JSON format
        return json.dumps(result.data, indent=2)

    return str(result.data)
