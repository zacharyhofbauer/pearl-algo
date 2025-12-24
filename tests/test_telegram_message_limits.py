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
    # v2 labeled format: "100 scans (session) / 500 total • 10 gen / 8 sent ..."
    assert "100 scans (session)" in result
    assert "500 total" in result
    assert "10 gen" in result
    assert "8 sent" in result
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
    # v2 labeled format: "500 scans • 10 gen / 8 sent • 85 bars • 0 errors"
    assert "500 scans" in result
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


# ---------------------------------------------------------------------------
# Home Card v2 spec tests - conditional callouts
# ---------------------------------------------------------------------------

def test_home_card_degraded_state() -> None:
    """Test Home Card in fully degraded state (stale + session closed + stopped).
    
    This is the worst-case scenario: agent stopped, gateway stopped, session closed,
    stale state. Verify all conditional callouts appear and message stays under limit.
    """
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=False,
        gateway_running=False,
        futures_market_open=False,
        strategy_session_open=False,
        paused=False,
        pause_reason=None,
        cycles_session=0,
        cycles_total=100,
        signals_generated=5,
        signals_sent=3,
        errors=2,
        buffer_size=50,
        buffer_target=100,
        # v2 fields
        state_age_seconds=300.0,  # 5 minutes old = stale
        state_stale_threshold=120.0,
        signal_send_failures=2,
        gateway_unknown=False,
    )
    
    # Should show stale warning
    assert "5.0m old" in result or "may be outdated" in result
    # Should show session closed explanation
    assert "Signals suppressed" in result or "session closed" in result
    # Should show action cue
    assert "Start agent to begin" in result
    # Should show signal send failures
    assert "2 fail" in result
    # Should stay under limits
    assert len(result) < TELEGRAM_TEXT_LIMIT, f"Degraded Home Card too long: {len(result)} chars"
    assert len(result) < 2000, f"Degraded Home Card should be compact: {len(result)} chars"


def test_home_card_freshness_warning() -> None:
    """Test that freshness warning appears when state is stale."""
    # Fresh state (under threshold) - no warning
    result_fresh = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        state_age_seconds=60.0,  # 1 minute = fresh
        state_stale_threshold=120.0,
    )
    assert "may be outdated" not in result_fresh
    
    # Stale state (over threshold) - warning appears
    result_stale = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        state_age_seconds=180.0,  # 3 minutes = stale
        state_stale_threshold=120.0,
    )
    assert "may be outdated" in result_stale or "3.0m old" in result_stale


def test_home_card_gate_expectations() -> None:
    """Test that gate expectations are explained when closed."""
    # Session closed - explain signals suppressed
    result_session_closed = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=False,  # Session closed
    )
    assert "Signals suppressed" in result_session_closed
    
    # Market closed (session open/unknown) - explain data delay
    result_market_closed = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=False,  # Market closed
        strategy_session_open=None,  # Unknown
    )
    assert "Data may be delayed" in result_market_closed
    
    # Both open - no extra explanations
    result_both_open = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
    )
    assert "Signals suppressed" not in result_both_open
    assert "Data may be delayed" not in result_both_open


def test_home_card_action_cue() -> None:
    """Test that action cue appears when agent is stopped."""
    # Stopped - action cue appears
    result_stopped = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=False,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
    )
    assert "Start agent to begin" in result_stopped
    
    # Running - no action cue
    result_running = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
    )
    assert "Start agent to begin" not in result_running


def test_home_card_circuit_breaker_pause() -> None:
    """Test that circuit breaker pause shows intervention required."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        paused=True,
        pause_reason="circuit_breaker_errors",
    )
    
    assert "PAUSED" in result
    assert "circuit breaker errors" in result  # safe_label converts underscores
    assert "Manual intervention required" in result


def test_home_card_signal_send_failures() -> None:
    """Test that signal send failures are shown when non-zero."""
    # No failures - no cue
    result_no_failures = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        signal_send_failures=0,
    )
    assert "signal send failures" not in result_no_failures
    
    # Failures - cue appears
    result_with_failures = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        signal_send_failures=3,
    )
    assert "3 fail" in result_with_failures


def test_home_card_gateway_unknown() -> None:
    """Test that gateway unknown is displayed as '?' instead of false status."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=False,  # This would show STOPPED
        futures_market_open=True,
        strategy_session_open=True,
        gateway_unknown=True,  # But this overrides to show '?'
    )
    
    assert "Gateway: ?" in result
    assert "Gateway: STOPPED" not in result


def test_home_card_healthy_state_calm() -> None:
    """Test that healthy state shows minimal output (no extra warnings)."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        paused=False,
        cycles_session=100,
        cycles_total=500,
        signals_generated=10,
        signals_sent=10,
        errors=0,
        buffer_size=100,
        buffer_target=100,
        state_age_seconds=30.0,  # Fresh
        state_stale_threshold=120.0,
        signal_send_failures=0,
    )
    
    # None of the conditional callouts should appear
    assert "may be outdated" not in result
    assert "Signals suppressed" not in result
    assert "Data may be delayed" not in result
    assert "Start agent to begin" not in result
    assert "signal send failures" not in result
    assert "Manual intervention required" not in result
    
    # Should be very compact
    assert len(result) < 800, f"Healthy Home Card should be minimal: {len(result)} chars"


# ---------------------------------------------------------------------------
# Markdown safety tests
# ---------------------------------------------------------------------------

def test_home_card_markdown_safety_underscores() -> None:
    """Test that underscore-heavy pause reasons are safely rendered."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        paused=True,
        pause_reason="consecutive_errors_exceeded_limit",
    )
    
    # safe_label should convert underscores to spaces
    assert "consecutive errors exceeded limit" in result
    # The original underscore version should NOT appear (would break Markdown)
    assert "consecutive_errors_exceeded_limit" not in result


# ---------------------------------------------------------------------------
# Calm-minimal UX tests (v5)
# ---------------------------------------------------------------------------

def test_home_card_active_trades_shown_when_positive() -> None:
    """Test that active trades count appears when > 0."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        active_trades_count=2,
    )
    
    assert "2 active trades" in result
    assert "🎯" in result


def test_home_card_active_trades_hidden_when_zero() -> None:
    """Test that active trades count does NOT appear when 0 (calm-minimal)."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        active_trades_count=0,
    )
    
    assert "active trade" not in result


def test_home_card_active_trades_singular() -> None:
    """Test that active trades uses singular form for 1."""
    result = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        active_trades_count=1,
    )
    
    assert "1 active trade" in result
    assert "1 active trades" not in result


def test_home_card_last_cycle_seconds_pulse() -> None:
    """Test that last_cycle_seconds shows activity pulse when provided."""
    # Active (< 2 min)
    result_active = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        last_cycle_seconds=30.0,
    )
    assert "Active" in result_active
    assert "🟢" in result_active
    
    # Slow (2-5 min)
    result_slow = format_home_card(
        symbol="MNQ",
        time_str="10:30 AM ET",
        agent_running=True,
        gateway_running=True,
        futures_market_open=True,
        strategy_session_open=True,
        last_cycle_seconds=180.0,
    )
    assert "Slow" in result_slow
    assert "🟡" in result_slow


def test_compact_signal_calm_minimal_layout() -> None:
    """Test that compact signal uses decision-first calm-minimal layout."""
    from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
    
    signal = {
        "symbol": "MNQ",
        "type": "momentum_breakout",
        "direction": "long",
        "entry_price": 21234.50,
        "stop_loss": 21200.00,
        "take_profit": 21300.00,
        "confidence": 0.75,
        "signal_id": "momentum_breakout_1703347200.123456",
        "regime": {"regime": "trending_bullish", "volatility": "normal"},
        "mtf_analysis": {"alignment": "aligned"},
    }
    
    notifier = NQAgentTelegramNotifier.__new__(NQAgentTelegramNotifier)
    message = notifier._format_compact_signal(signal)
    
    # Should have decision-first layout
    assert "*Entry:*" in message
    assert "*Stop:*" in message
    assert "*TP:*" in message
    assert "R:R" in message
    
    # Should have action cue
    assert "Monitor" in message or "BUY" in message
    
    # Should have confidence
    assert "75%" in message or "confidence" in message.lower()
    
    # Should have compact footer
    assert "tap Details" in message
    
    # Should NOT have verbose elements (kept in Details)
    assert "Generated:" not in message  # Timestamp moved to Details
    
    # Should be compact (under 1000 chars for mobile)
    assert len(message) < 1000, f"Calm-minimal signal too long: {len(message)} chars"


def test_compact_signal_under_telegram_limit() -> None:
    """Test that calm-minimal signal stays well under Telegram limit."""
    from pearlalgo.nq_agent.telegram_notifier import NQAgentTelegramNotifier
    
    # Maximum content signal
    signal = {
        "symbol": "MNQ",
        "type": "momentum_breakout_continuation",
        "direction": "long",
        "entry_price": 21234.50,
        "stop_loss": 21200.00,
        "take_profit": 21300.00,
        "confidence": 0.72,
        "signal_id": "momentum_breakout_continuation_1703347200.123456",
        "regime": {
            "regime": "trending_bullish",
            "volatility": "high",
        },
        "mtf_analysis": {
            "alignment": "aligned",
        },
    }
    
    notifier = NQAgentTelegramNotifier.__new__(NQAgentTelegramNotifier)
    message = notifier._format_compact_signal(signal)
    
    assert len(message) < TELEGRAM_TEXT_LIMIT, f"Signal too long: {len(message)} chars"
    assert len(message) < 1000, f"Calm-minimal signal should be compact: {len(message)} chars"

