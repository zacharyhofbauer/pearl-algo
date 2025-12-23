from __future__ import annotations

from pearlalgo.utils.telegram_alerts import (
    TELEGRAM_TEXT_LIMIT,
    _truncate_telegram_text,
    format_signal_status,
    format_signal_direction,
    format_signal_confidence_tier,
    format_pnl,
    format_time_ago,
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

