from __future__ import annotations

from pearlalgo.utils.telegram_alerts import (
    TELEGRAM_TEXT_LIMIT,
    _truncate_telegram_text,
    format_signal_status,
    format_signal_direction,
    format_signal_confidence_tier,
    format_pnl,
    format_time_ago,
    escape_markdown,
    safe_label,
    format_gate_status,
    format_service_status,
    format_activity_line,
    format_performance_line,
    format_home_card,
)


def test_truncate_telegram_text_noop_when_under_limit() -> None:
    msg = "hello"
    assert _truncate_telegram_text(msg) == msg


def test_truncate_telegram_text_truncates_and_marks() -> None:
    msg = "x" * (TELEGRAM_TEXT_LIMIT + 100)
    truncated = _truncate_telegram_text(msg)

    assert len(truncated) <= TELEGRAM_TEXT_LIMIT
    assert truncated.endswith("…(truncated)")


# ---------------------------------------------------------------------------
# Signal status semantics tests
# ---------------------------------------------------------------------------

def test_format_signal_status_generated() -> None:
    emoji, label = format_signal_status("generated")
    assert emoji == "🆕"
    assert label == "Pending"


def test_format_signal_status_entered() -> None:
    emoji, label = format_signal_status("entered")
    assert emoji == "🎯"
    assert label == "In Trade"


def test_format_signal_status_exited_win() -> None:
    emoji, label = format_signal_status("exited", is_win=True)
    assert emoji == "✅"
    assert label == "Win"


def test_format_signal_status_exited_loss() -> None:
    emoji, label = format_signal_status("exited", is_win=False)
    assert emoji == "❌"
    assert label == "Loss"


def test_format_signal_status_expired() -> None:
    emoji, label = format_signal_status("expired")
    assert emoji == "⏰"
    assert label == "Expired"


def test_format_signal_status_unknown() -> None:
    emoji, label = format_signal_status("some_unknown_status")
    assert emoji == "⚪"
    assert label == "Some_Unknown_Status"


def test_format_signal_direction_long() -> None:
    emoji, label = format_signal_direction("long")
    assert emoji == "🟢"
    assert label == "LONG"


def test_format_signal_direction_short() -> None:
    emoji, label = format_signal_direction("short")
    assert emoji == "🔴"
    assert label == "SHORT"


def test_format_signal_direction_unknown() -> None:
    emoji, label = format_signal_direction("sideways")
    assert emoji == "⚪"
    assert label == "SIDEWAYS"


def test_format_signal_confidence_tier_high() -> None:
    emoji, tier = format_signal_confidence_tier(0.75)
    assert emoji == "🟢"
    assert tier == "High"


def test_format_signal_confidence_tier_moderate() -> None:
    emoji, tier = format_signal_confidence_tier(0.60)
    assert emoji == "🟡"
    assert tier == "Moderate"


def test_format_signal_confidence_tier_low() -> None:
    emoji, tier = format_signal_confidence_tier(0.40)
    assert emoji == "🔴"
    assert tier == "Low"


def test_format_pnl_positive() -> None:
    emoji, formatted = format_pnl(125.50)
    assert emoji == "🟢"
    assert formatted == "+$125.50"


def test_format_pnl_negative() -> None:
    emoji, formatted = format_pnl(-50.25)
    assert emoji == "🔴"
    assert formatted == "-$50.25"


def test_format_pnl_zero() -> None:
    emoji, formatted = format_pnl(0.0)
    assert emoji == "🟢"
    assert formatted == "+$0.00"


def test_format_time_ago_empty() -> None:
    assert format_time_ago(None) == ""
    assert format_time_ago("") == ""


# ---------------------------------------------------------------------------
# Template length tests (ensure messages stay under Telegram limit)
# ---------------------------------------------------------------------------

def test_compact_signal_template_under_limit() -> None:
    """Test that the compact signal template stays under Telegram's 4096 char limit."""
    from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
    
    # Create a signal with maximum reasonable content
    signal = {
        "symbol": "MNQ",
        "type": "momentum_breakout_continuation",
        "direction": "long",
        "entry_price": 21234.50,
        "stop_loss": 21200.00,
        "take_profit": 21300.00,
        "confidence": 0.72,
        "signal_id": "momentum_breakout_continuation_1703347200.123456",
        "reason": "Strong momentum with MTF alignment, breaking above key resistance level with volume confirmation. VWAP support and institutional flow alignment detected. " * 2,
        "regime": {
            "regime": "trending_bullish",
            "volatility": "high",
            "session": "morning_trend",
        },
        "mtf_analysis": {
            "alignment": "aligned",
            "alignment_score": 0.85,
        },
    }
    
    # Create notifier instance (won't actually send)
    notifier = NQAgentTelegramNotifier.__new__(NQAgentTelegramNotifier)
    message = notifier._format_compact_signal(signal)
    
    # Assert under limit with comfortable margin
    assert len(message) < TELEGRAM_TEXT_LIMIT, f"Message too long: {len(message)} chars"
    assert len(message) < 2000, f"Message should be compact: {len(message)} chars"


def test_minimal_signal_template_under_limit() -> None:
    """Test that the minimal signal template stays well under Telegram's limit."""
    from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
    
    signal = {
        "symbol": "MNQ",
        "type": "momentum_breakout",
        "direction": "long",
        "entry_price": 21234.50,
        "stop_loss": 21200.00,
        "take_profit": 21300.00,
        "confidence": 0.72,
        "signal_id": "momentum_breakout_1703347200.123456",
    }
    
    notifier = NQAgentTelegramNotifier.__new__(NQAgentTelegramNotifier)
    message = notifier._format_minimal_signal(signal)
    
    # Minimal should be very short
    assert len(message) < 500, f"Minimal message too long: {len(message)} chars"


def test_professional_signal_template_under_limit() -> None:
    """Test that the professional signal template stays under Telegram's limit."""
    from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
    
    # Create a signal with maximum content (all optional fields populated)
    signal = {
        "symbol": "MNQ",
        "type": "momentum_breakout_continuation",
        "direction": "long",
        "entry_price": 21234.50,
        "stop_loss": 21200.00,
        "take_profit": 21300.00,
        "confidence": 0.72,
        "reason": "Strong momentum with MTF alignment, breaking above key resistance level with volume confirmation. " * 3,
        "regime": {
            "regime": "trending_bullish",
            "volatility": "high",
            "session": "morning_trend",
        },
        "mtf_analysis": {
            "alignment": "aligned",
            "alignment_score": 0.85,
        },
        "vwap_data": {
            "vwap": 21220.00,
            "distance_from_vwap": 14.50,
            "distance_pct": 0.07,
        },
        "order_book": {
            "imbalance": 0.25,
            "bid_depth": 150,
            "ask_depth": 100,
            "data_level": "level2",
        },
        "indicators": {
            "volume_ratio": 1.8,
            "atr": 25.5,
        },
    }
    
    notifier = NQAgentTelegramNotifier.__new__(NQAgentTelegramNotifier)
    message = notifier._format_professional_signal(signal)
    
    # Should stay under limit
    assert len(message) < TELEGRAM_TEXT_LIMIT, f"Professional message too long: {len(message)} chars"


# ---------------------------------------------------------------------------
# Markdown safety helper tests
# ---------------------------------------------------------------------------

def test_escape_markdown_underscores() -> None:
    """Test that underscores are escaped for Telegram Markdown."""
    result = escape_markdown("hello_world_test")
    assert result == "hello\\_world\\_test"


def test_escape_markdown_asterisks() -> None:
    """Test that asterisks are escaped for Telegram Markdown."""
    result = escape_markdown("hello*world*test")
    assert result == "hello\\*world\\*test"


def test_escape_markdown_mixed() -> None:
    """Test that mixed special chars are escaped."""
    result = escape_markdown("test_value*bold*`code`[link]")
    assert "\\_" in result
    assert "\\*" in result
    assert "\\`" in result
    assert "\\[" in result


def test_escape_markdown_empty() -> None:
    """Test that empty string returns empty."""
    assert escape_markdown("") == ""
    assert escape_markdown(None) == ""


def test_safe_label_underscores_to_spaces() -> None:
    """Test that safe_label replaces underscores with spaces."""
    result = safe_label("trending_bullish")
    assert result == "trending bullish"


def test_safe_label_preserves_other_chars() -> None:
    """Test that safe_label preserves non-underscore characters."""
    result = safe_label("Hello World 123!")
    assert result == "Hello World 123!"


def test_safe_label_empty() -> None:
    """Test that empty string returns empty."""
    assert safe_label("") == ""
    assert safe_label(None) == ""


# ---------------------------------------------------------------------------
# Home Card layout helper tests
# ---------------------------------------------------------------------------

def test_format_gate_status_open() -> None:
    """Test gate status formatting when both gates are open."""
    result = format_gate_status(
        futures_market_open=True,
        strategy_session_open=True,
    )
    assert "🟢 Futures: OPEN" in result
    assert "🟢 Session: OPEN" in result


def test_format_gate_status_closed() -> None:
    """Test gate status formatting when both gates are closed."""
    result = format_gate_status(
        futures_market_open=False,
        strategy_session_open=False,
    )
    assert "🔴 Futures: CLOSED" in result
    assert "🔴 Session: CLOSED" in result


def test_format_gate_status_unknown() -> None:
    """Test gate status formatting when status is unknown."""
    result = format_gate_status(
        futures_market_open=None,
        strategy_session_open=None,
    )
    assert "⚪ Futures: ?" in result
    assert "⚪ Session: ?" in result


def test_format_service_status_running() -> None:
    """Test service status when both services are running."""
    result = format_service_status(
        agent_running=True,
        gateway_running=True,
    )
    assert "🟢 Agent: RUNNING" in result
    assert "🟢 Gateway: RUNNING" in result


def test_format_service_status_stopped() -> None:
    """Test service status when both services are stopped."""
    result = format_service_status(
        agent_running=False,
        gateway_running=False,
    )
    assert "🔴 Agent: STOPPED" in result
    assert "🔴 Gateway: STOPPED" in result


def test_format_service_status_paused() -> None:
    """Test service status when agent is paused."""
    result = format_service_status(
        agent_running=True,
        gateway_running=True,
        paused=True,
    )
    assert "⏸️ Agent: PAUSED" in result


def test_format_activity_line() -> None:
    """Test activity line formatting."""
    result = format_activity_line(
        cycles_session=100,
        cycles_total=500,
        signals_generated=10,
        signals_sent=8,
        errors=2,
        buffer_size=85,
        buffer_target=100,
    )
    assert "100/500 cycles" in result
    assert "10/8 signals" in result
    assert "85/100 bars" in result
    assert "2 errors" in result


def test_format_activity_line_no_session() -> None:
    """Test activity line when session cycles not available."""
    result = format_activity_line(
        cycles_session=None,
        cycles_total=500,
        signals_generated=10,
        signals_sent=8,
        errors=0,
        buffer_size=85,
        buffer_target=None,
    )
    assert "500 cycles" in result
    assert "85 bars" in result


def test_format_performance_line() -> None:
    """Test performance line formatting."""
    result = format_performance_line(
        wins=5,
        losses=2,
        win_rate=71.4,
        total_pnl=350.50,
    )
    assert "5W/2L" in result
    assert "71% WR" in result
    assert "🟢" in result
    assert "$350.50" in result


def test_format_performance_line_negative() -> None:
    """Test performance line with negative P&L."""
    result = format_performance_line(
        wins=2,
        losses=5,
        win_rate=28.6,
        total_pnl=-150.25,
    )
    assert "2W/5L" in result
    assert "🔴" in result
    assert "$-150.25" in result


# ---------------------------------------------------------------------------
# Home Card template tests
# ---------------------------------------------------------------------------

def test_home_card_minimal() -> None:
    """Test Home Card with minimal required fields."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
    )
    
    # Check key elements are present
    assert "📊 *MNQ*" in result
    assert "10:30 AM ET" in result
    assert "Agent: RUNNING" in result
    assert "Gateway: RUNNING" in result
    assert "Futures: OPEN" in result
    assert "Session: OPEN" in result


def test_home_card_with_price() -> None:
    """Test Home Card with price information."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        latest_price=21234.50,
        price_change_str="+0.25%",
    )
    
    assert "💰 *$21,234.50*" in result
    assert "+0.25%" in result


def test_home_card_with_performance() -> None:
    """Test Home Card with performance data."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        performance={
            "exited_signals": 10,
            "wins": 7,
            "losses": 3,
            "win_rate": 0.70,
            "total_pnl": 500.00,
        },
    )
    
    assert "*7d Performance:*" in result
    assert "7W/3L" in result
    assert "70% WR" in result


def test_home_card_paused() -> None:
    """Test Home Card when agent is paused."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        paused=True,
        pause_reason="circuit_breaker",
    )
    
    assert "PAUSED" in result
    assert "circuit breaker" in result  # safe_label converts underscore to space


def test_home_card_under_telegram_limit() -> None:
    """Test that Home Card with all fields stays under Telegram limit."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        paused=False,
        pause_reason=None,
        cycles_session=1234,
        cycles_total=5678,
        signals_generated=50,
        signals_sent=48,
        errors=5,
        buffer_size=95,
        buffer_target=100,
        latest_price=21234.50,
        performance={
            "exited_signals": 25,
            "wins": 18,
            "losses": 7,
            "win_rate": 0.72,
            "total_pnl": 1250.75,
        },
        sparkline="▁▂▃▄▅▆▇█▇▆▅▄▃▂▁",
        price_change_str="+0.35%",
        last_signal_age="5m ago",
    )
    
    # Should stay well under Telegram limit (4096 chars)
    assert len(result) < TELEGRAM_TEXT_LIMIT, f"Home Card too long: {len(result)} chars"
    # Should be compact (under 1500 chars for mobile-friendliness)
    assert len(result) < 1500, f"Home Card should be compact: {len(result)} chars"


def test_home_card_stopped_agent() -> None:
    """Test Home Card when agent is stopped."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=False,
        gateway_running=False,
        futures_market_open=None,
        strategy_session_open=None,
    )
    
    assert "Agent: STOPPED" in result
    assert "Gateway: STOPPED" in result

