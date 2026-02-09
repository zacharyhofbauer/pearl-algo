"""
Pearl AI Types - TypedDict definitions for common return types.

Enables IDE completion and type checking throughout the codebase.
"""

from typing import TypedDict, Optional, Dict, List, Any, Literal
from datetime import datetime


class TradingContextSummary(TypedDict):
    """Summary of current trading context for UI display."""
    daily_pnl: float
    win_count: int
    loss_count: int
    trade_count: int
    win_rate: float
    active_positions: int
    position_info: Optional[str]
    market_regime: str
    last_signal_time: Optional[str]
    consecutive_wins: int
    consecutive_losses: int


class MetricsSummary(TypedDict):
    """Summary of Pearl AI metrics."""
    period_hours: int
    total_requests: int
    total_tokens: int
    total_cost_usd: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    cache_hit_rate: float
    error_rate: float
    fallback_rate: float
    by_endpoint: Dict[str, Any]
    by_model: Dict[str, Any]


class CostSummary(TypedDict):
    """Cost summary for API."""
    today_usd: float
    month_usd: float
    limit_usd: Optional[float]


class CacheStats(TypedDict):
    """Cache statistics."""
    size: int
    max_size: int
    hits: int
    misses: int
    hit_rate: float
    evictions: int
    avg_entry_age_seconds: float


class CacheEntryInfo(TypedDict):
    """Information about a cache entry."""
    key: str
    age_seconds: float
    ttl_seconds: int
    hit_count: int
    expired: bool
    response_preview: str


class ToolResultData(TypedDict, total=False):
    """Data returned from a tool execution."""
    message: str
    trades: List[Dict[str, Any]]
    count: int
    regime: str
    days: int
    wins: int
    total_trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    explanation: str
    hourly_data: Dict[str, Any]
    best_hour: Dict[str, Any]
    worst_hour: Dict[str, Any]
    best_trade: float
    worst_trade: float


class LLMRequestDict(TypedDict):
    """Serialized LLM request."""
    timestamp: str
    endpoint: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    cost_usd: float
    cache_hit: bool
    success: bool
    error: Optional[str]
    fallback_used: bool
    tool_calls: Optional[List[Dict[str, Any]]]


class ChatResponseDict(TypedDict):
    """Response from chat with source indicator."""
    response: str
    timestamp: str
    complexity: str
    source: Literal["cache", "local", "claude", "template"]


class NarrationDetailsDict(TypedDict, total=False):
    """Expanded narration payload for dropdown/expanded UI."""
    title: str
    lines: List[str]
    text: str
    fields: Dict[str, Any]
    kv: List[Dict[str, Any]]
    sections: List[Dict[str, Any]]
    truncated: bool


class NarrationOutputDict(TypedDict):
    """Narration headline + expanded details."""
    headline: str
    details: NarrationDetailsDict


class MarketRegimeInfo(TypedDict, total=False):
    """Market regime information."""
    regime: str
    allowed_direction: str
    confidence: float
    volatility: str


class AIStatusInfo(TypedDict, total=False):
    """AI status information."""
    ml_filter: Dict[str, Any]
    direction_gating: Dict[str, Any]


class CircuitBreakerInfo(TypedDict, total=False):
    """Circuit breaker status."""
    in_cooldown: bool
    trip_reason: Optional[str]
    cooldown_remaining_seconds: Optional[int]
    blocks: int


class RiskMetricsInfo(TypedDict, total=False):
    """Risk metrics information."""
    expectancy: float
    sharpe_ratio: Optional[float]
    max_drawdown: float
    largest_win: float
    largest_loss: float


class TradingState(TypedDict, total=False):
    """Full trading state dictionary."""
    running: bool
    daily_pnl: float
    daily_trades: int
    daily_wins: int
    daily_losses: int
    active_trades_count: int
    last_trade_direction: str
    last_entry_price: float
    consecutive_wins: int
    consecutive_losses: int
    recent_exits: List[Dict[str, Any]]
    market_regime: MarketRegimeInfo
    ai_status: AIStatusInfo
    circuit_breaker: CircuitBreakerInfo
    risk_metrics: RiskMetricsInfo
    signal_rejections_24h: Dict[str, int]
    buy_sell_pressure: Dict[str, Any]
    last_signal_time: Optional[str]
    quiet_period_minutes: int


class PearlMessageDict(TypedDict):
    """Serialized Pearl message."""
    content: str
    timestamp: str
    type: Literal["narration", "insight", "alert", "coaching", "response"]
    priority: Literal["low", "normal", "high", "critical"]
    trade_id: Optional[str]
    metadata: Dict[str, Any]


class SanitizationResult(TypedDict):
    """Result of input sanitization."""
    sanitized: str
    was_modified: bool
    warnings: List[str]
