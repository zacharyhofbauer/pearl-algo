"""
Tests for Pearl AI metrics tool-call tracing.
"""

from datetime import datetime

from pearl_ai.metrics import (
    MetricsCollector,
    LLMRequest,
    ToolCall,
    redact_tool_arguments,
    REDACTED_VALUE,
)


def test_redact_tool_arguments():
    """Sensitive keys should be redacted and long strings truncated."""
    args = {
        "api_key": "secret",
        "nested": {"token": "abc123", "safe": "ok"},
        "long": "x" * 500,
    }

    redacted = redact_tool_arguments(args)

    assert redacted["api_key"] == REDACTED_VALUE
    assert redacted["nested"]["token"] == REDACTED_VALUE
    assert redacted["nested"]["safe"] == "ok"
    assert redacted["long"].startswith("x")
    assert redacted["long"].endswith("...")


def test_tool_stats_aggregation():
    """Tool stats should aggregate counts, errors, and latency."""
    metrics = MetricsCollector()
    tool_calls = [
        ToolCall(name="get_similar_trades", arguments={"direction": "long"}, success=True, latency_ms=40),
        ToolCall(name="get_similar_trades", arguments={"direction": "short"}, success=False, latency_ms=120, error="fail"),
        ToolCall(name="get_regime_performance", arguments={"regime": "trending"}, success=True, latency_ms=30),
    ]

    metrics.record(LLMRequest(
        timestamp=datetime.now(),
        endpoint="chat",
        model="claude-sonnet-4-20250514",
        input_tokens=10,
        output_tokens=20,
        latency_ms=200,
        tool_calls=tool_calls,
    ))

    summary = metrics.get_summary(hours=1)
    tool_stats = summary["tool_stats"]

    assert tool_stats["total_calls"] == 3
    assert tool_stats["by_tool"]["get_similar_trades"]["count"] == 2
    assert tool_stats["by_tool"]["get_similar_trades"]["error_rate"] == 0.5


def test_record_dedupe_hit_updates_summary():
    """Dedupe hits should update summary counters."""
    metrics = MetricsCollector()
    metrics.record_dedupe_hit("claude-sonnet-4-20250514", input_tokens=1000, output_tokens=500)

    summary = metrics.get_summary(hours=1)

    assert summary["dedupe"]["hits"] == 1
    assert summary["dedupe"]["saved_tokens"] == 1500
    assert summary["dedupe"]["saved_cost_usd"] > 0
