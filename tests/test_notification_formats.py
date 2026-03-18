"""Tests for pearlalgo.notifications.formats — pure/near-pure functions."""

from __future__ import annotations

import math

import pytest

from pearlalgo.notifications.formats import (
    # Mobile-first helpers
    truncate_for_mobile,
    format_button_label,
    format_header,
    format_alert_headline,
    # Footer / separators
    format_transparency_footer,
    _truncate_telegram_text,
    _format_separator,
    _format_uptime,
    _format_number,
    # Signal helpers
    format_signal_status,
    format_signal_direction,
    format_signal_confidence_tier,
    # Markdown helpers
    sanitize_telegram_markdown,
    _escape_markdown_underscores_in_words,
    format_bot_name,
    escape_subprocess_output,
    # Activity helpers
    format_activity_pulse,
    format_session_window,
    format_signal_action_cue,
    format_performance_trend,
    # Gate/service helpers
    format_gate_status,
    format_service_status,
    format_activity_line,
    _format_pressure_badge,
    # Compact helpers
    format_compact_status,
    format_compact_ratio,
    format_compact_metric,
    # Stale callout
    format_stale_callout,
    # Execution
    _format_execution_status,
    # Performance
    format_performance_line,
    # Constants
    TELEGRAM_TEXT_LIMIT,
    EMOJI_OK,
    EMOJI_ERROR,
)


# ---------------------------------------------------------------------------
# Mobile-first helpers
# ---------------------------------------------------------------------------

class TestTruncateForMobile:
    def test_short_text(self):
        assert truncate_for_mobile("Hello", 10) == "Hello"

    def test_exact_limit(self):
        assert truncate_for_mobile("Hello", 5) == "Hello"

    def test_truncated(self):
        assert truncate_for_mobile("Hello World", 8) == "Hello W…"

    def test_empty(self):
        assert truncate_for_mobile("", 10) == ""


class TestFormatButtonLabel:
    def test_short_text(self):
        assert format_button_label("Status") == "Status"

    def test_with_count(self):
        result = format_button_label("Trades", count=3)
        assert "3" in result

    def test_count_zero_ignored(self):
        assert format_button_label("Trades", count=0) == "Trades"

    def test_long_text_truncated(self):
        result = format_button_label("Very Long Button Label Text")
        assert len(result) <= 16


class TestFormatHeader:
    def test_short(self):
        assert format_header("Status") == "Status"

    def test_long_truncated(self):
        long = "A" * 50
        result = format_header(long)
        assert len(result) <= 40


class TestFormatAlertHeadline:
    def test_short(self):
        assert format_alert_headline("Alert!") == "Alert!"

    def test_long_truncated(self):
        long = "A" * 80
        result = format_alert_headline(long)
        assert len(result) <= 60


# ---------------------------------------------------------------------------
# Footer / separator / wrappers
# ---------------------------------------------------------------------------

class TestTruncateTelegramText:
    def test_short_text(self):
        assert _truncate_telegram_text("Hello") == "Hello"

    def test_long_text_truncated(self):
        text = "x" * 5000
        result = _truncate_telegram_text(text)
        assert len(result) <= TELEGRAM_TEXT_LIMIT
        assert "truncated" in result


class TestFormatSeparator:
    def test_returns_empty(self):
        assert _format_separator() == ""


class TestFormatUptime:
    def test_hours_minutes(self):
        assert _format_uptime({"hours": 2, "minutes": 30}) == "2h30m"


class TestFormatNumber:
    def test_basic(self):
        result = _format_number(1234.5)
        assert "1,234.50" in result


class TestTransparencyFooter:
    def test_all_data(self):
        result = format_transparency_footer(
            agent_uptime_seconds=3600,
            gateway_ok=True,
            data_age_seconds=30,
            agent_running=True,
        )
        assert "Agent:" in result
        assert "Gateway: OK" in result
        assert "Data:" in result

    def test_agent_off(self):
        result = format_transparency_footer(agent_running=False)
        assert "Agent: OFF" in result

    def test_agent_unknown(self):
        result = format_transparency_footer()
        assert "Agent: ?" in result

    def test_gateway_down(self):
        result = format_transparency_footer(gateway_ok=False)
        assert "Gateway: DOWN" in result

    def test_gateway_unknown(self):
        result = format_transparency_footer(gateway_ok=None)
        assert "Gateway: ?" in result

    def test_data_na(self):
        result = format_transparency_footer(data_age_seconds=None)
        assert "Data: N/A" in result

    def test_data_stale(self):
        result = format_transparency_footer(data_age_seconds=600, data_stale=True)
        assert EMOJI_ERROR in result


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------

class TestFormatSignalStatus:
    def test_generated(self):
        emoji, label = format_signal_status("generated")
        assert emoji == "🆕"
        assert label == "Pending"

    def test_entered(self):
        emoji, label = format_signal_status("entered")
        assert emoji == "🎯"
        assert label == "In Trade"

    def test_exited_win(self):
        emoji, label = format_signal_status("exited", is_win=True)
        assert emoji == "✅"
        assert label == "Win"

    def test_exited_loss(self):
        emoji, label = format_signal_status("exited", is_win=False)
        assert emoji == "❌"
        assert label == "Loss"

    def test_exited_no_result(self):
        emoji, label = format_signal_status("exited")
        assert emoji == "🏁"

    def test_expired(self):
        emoji, label = format_signal_status("expired")
        assert emoji == "⏰"

    def test_unknown(self):
        emoji, label = format_signal_status("something_else")
        assert emoji == "⚪"

    def test_none(self):
        emoji, label = format_signal_status("")
        assert emoji == "⚪"


class TestFormatSignalDirection:
    def test_long(self):
        emoji, label = format_signal_direction("long")
        assert emoji == "🟢"
        assert label == "LONG"

    def test_short(self):
        emoji, label = format_signal_direction("short")
        assert emoji == "🔴"
        assert label == "SHORT"

    def test_empty(self):
        emoji, label = format_signal_direction("")
        assert emoji == "⚪"

    def test_none(self):
        emoji, label = format_signal_direction(None)
        assert emoji == "⚪"


class TestFormatSignalConfidenceTier:
    def test_high(self):
        emoji, tier = format_signal_confidence_tier(0.85)
        assert emoji == "🟢"
        assert tier == "High"

    def test_moderate(self):
        emoji, tier = format_signal_confidence_tier(0.60)
        assert emoji == "🟡"
        assert tier == "Moderate"

    def test_low(self):
        emoji, tier = format_signal_confidence_tier(0.40)
        assert emoji == "🔴"
        assert tier == "Low"


# ---------------------------------------------------------------------------
# Markdown helpers
# ---------------------------------------------------------------------------

class TestSanitizeTelegramMarkdown:
    def test_empty(self):
        assert sanitize_telegram_markdown("") == ""

    def test_no_underscores(self):
        assert sanitize_telegram_markdown("Hello world") == "Hello world"

    def test_preserves_code_blocks(self):
        text = "Check `file_name.py` here"
        result = sanitize_telegram_markdown(text)
        assert "file_name.py" in result


class TestEscapeMarkdownUnderscoresInWords:
    def test_empty(self):
        assert _escape_markdown_underscores_in_words("") == ""


class TestFormatBotName:
    def test_underscore_bot(self):
        assert format_bot_name("pearl_bot_auto") == "Pearl Bot Auto"

    def test_simple(self):
        assert format_bot_name("scanner") == "Scanner"

    def test_empty(self):
        assert format_bot_name("") == "Scanner"


class TestEscapeSubprocessOutput:
    def test_empty(self):
        assert escape_subprocess_output("") == ""

    def test_underscores_escaped(self):
        assert "\\_" in escape_subprocess_output("agent_NQ.pid")

    def test_asterisks_escaped(self):
        assert "\\*" in escape_subprocess_output("*bold*")

    def test_ansi_stripped(self):
        assert escape_subprocess_output("\x1b[31mred\x1b[0m") == "red"


# ---------------------------------------------------------------------------
# Activity helpers
# ---------------------------------------------------------------------------

class TestFormatActivityPulse:
    def test_paused(self):
        emoji, text = format_activity_pulse(30, is_paused=True)
        assert text == "Paused"

    def test_none(self):
        emoji, text = format_activity_pulse(None)
        assert text == "Unknown"

    def test_negative(self):
        emoji, text = format_activity_pulse(-1)
        assert text == "Unknown"

    def test_active(self):
        emoji, text = format_activity_pulse(30)
        assert "Active" in text
        assert emoji == "🟢"

    def test_slow(self):
        emoji, text = format_activity_pulse(180)
        assert "Slow" in text
        assert emoji == "🟡"

    def test_stale(self):
        emoji, text = format_activity_pulse(400)
        assert "Stale" in text
        assert emoji == "🔴"

    def test_hours_format(self):
        emoji, text = format_activity_pulse(7200)
        assert "h" in text


class TestFormatSessionWindow:
    def test_normal(self):
        assert format_session_window("18:00", "16:10") == "18:00–16:10 ET"

    def test_missing_start(self):
        assert "Config" in format_session_window(None, "16:10")

    def test_missing_end(self):
        assert "Config" in format_session_window("18:00", None)


class TestFormatSignalActionCue:
    def test_generated_long(self):
        result = format_signal_action_cue("generated", "long")
        assert "BUY" in result

    def test_generated_short(self):
        result = format_signal_action_cue("generated", "short")
        assert "SELL" in result

    def test_entered(self):
        result = format_signal_action_cue("entered", "long")
        assert "ACTIVE" in result

    def test_exited(self):
        result = format_signal_action_cue("exited", "long")
        assert "completed" in result

    def test_expired(self):
        result = format_signal_action_cue("expired", "long")
        assert "expired" in result

    def test_unknown(self):
        assert format_signal_action_cue("unknown", "long") == ""


class TestFormatPerformanceTrend:
    def test_no_previous(self):
        assert format_performance_trend(100, None) == ""

    def test_positive(self):
        result = format_performance_trend(150, 100)
        assert "↗️" in result
        assert "+$50.00" in result

    def test_negative(self):
        result = format_performance_trend(50, 100)
        assert "↘️" in result

    def test_equal(self):
        result = format_performance_trend(100, 100)
        assert "➡️" in result


# ---------------------------------------------------------------------------
# Gate / service helpers
# ---------------------------------------------------------------------------

class TestFormatGateStatus:
    def test_both_open(self):
        result = format_gate_status(True, True)
        assert "OPEN" in result
        assert "🟢" in result

    def test_both_closed(self):
        result = format_gate_status(False, False)
        assert "CLOSED" in result
        assert "🔴" in result

    def test_unknown(self):
        result = format_gate_status(None, None)
        assert "?" in result


class TestFormatServiceStatus:
    def test_running(self):
        result = format_service_status(True, True)
        assert "RUNNING" in result
        assert "🟢" in result

    def test_stopped(self):
        result = format_service_status(False, False)
        assert "STOPPED" in result
        assert "🔴" in result

    def test_paused(self):
        result = format_service_status(True, True, paused=True)
        assert "PAUSED" in result


class TestFormatActivityLine:
    def test_basic(self):
        result = format_activity_line(
            cycles_session=100,
            cycles_total=500,
            signals_generated=3,
            signals_sent=2,
            errors=0,
            buffer_size=80,
            buffer_target=100,
        )
        assert "scans" in result
        assert "gen" in result
        assert "sent" in result
        assert "bars" in result
        assert "errors" in result

    def test_no_session_cycles(self):
        result = format_activity_line(
            cycles_session=None,
            cycles_total=500,
            signals_generated=0,
            signals_sent=0,
            errors=1,
            buffer_size=50,
        )
        assert "500" in result

    def test_send_failures(self):
        result = format_activity_line(
            cycles_session=None,
            cycles_total=10,
            signals_generated=2,
            signals_sent=1,
            errors=0,
            buffer_size=50,
            signal_send_failures=1,
        )
        assert "fail" in result


class TestFormatPressureBadge:
    def test_buyers_strong(self):
        result = _format_pressure_badge("buyers", "strong")
        assert "BUYERS" in result
        assert "▲▲▲" in result

    def test_sellers_moderate(self):
        result = _format_pressure_badge("sellers", "moderate")
        assert "SELLERS" in result
        assert "▼▼" in result

    def test_mixed(self):
        result = _format_pressure_badge("mixed", "light")
        assert "MIXED" in result

    def test_none_bias(self):
        assert _format_pressure_badge(None, "strong") is None


# ---------------------------------------------------------------------------
# Compact helpers
# ---------------------------------------------------------------------------

class TestFormatCompactStatus:
    def test_none(self):
        assert format_compact_status(None) == "⚪"

    def test_good(self):
        assert format_compact_status(0.9) == "🟢"

    def test_warn(self):
        assert format_compact_status(0.6) == "🟡"

    def test_bad(self):
        assert format_compact_status(0.3) == "🔴"

    def test_lower_is_better(self):
        assert format_compact_status(0.3, higher_is_better=False) == "🟢"
        assert format_compact_status(0.9, higher_is_better=False) == "🔴"

    def test_nan(self):
        assert format_compact_status(float("nan")) == "⚪"

    def test_invalid(self):
        assert format_compact_status("abc") == "⚪"


class TestFormatCompactRatio:
    def test_with_bar(self):
        result = format_compact_ratio(80, 100, "bars", show_bar=True)
        assert "80/100" in result
        assert "bars" in result

    def test_without_bar(self):
        result = format_compact_ratio(80, 100, "bars", show_bar=False)
        assert "80/100" in result

    def test_no_target(self):
        result = format_compact_ratio(50, None, "bars")
        assert "50" in result

    def test_zero_target(self):
        result = format_compact_ratio(50, 0, "bars")
        assert "50" in result


class TestFormatCompactMetric:
    def test_multiplier(self):
        result = format_compact_metric(1.3, 1.0, "vol", unit="x")
        assert "1.3x" in result

    def test_percentage(self):
        result = format_compact_metric(15, 1.0, "Δ", unit="%")
        assert "+15%" in result

    def test_none_value(self):
        assert format_compact_metric(None, 1.0, "vol") is None

    def test_nan_value(self):
        assert format_compact_metric(float("nan"), 1.0, "vol") is None

    def test_invalid_value(self):
        assert format_compact_metric("abc", 1.0, "vol") is None


# ---------------------------------------------------------------------------
# Stale callout
# ---------------------------------------------------------------------------

class TestFormatStaleCallout:
    def test_minutes(self):
        result = format_stale_callout(11)
        assert "11m" in result
        assert "stale" in result.lower()

    def test_hours(self):
        result = format_stale_callout(120)
        assert "h" in result

    def test_with_threshold(self):
        result = format_stale_callout(15, threshold_minutes=10)
        assert "15m/10m" in result


# ---------------------------------------------------------------------------
# Execution status
# ---------------------------------------------------------------------------

class TestFormatExecutionStatus:
    def test_disabled(self):
        result = _format_execution_status(False, False, None)
        assert "OFF" in result

    def test_paper_armed(self):
        result = _format_execution_status(True, True, "paper")
        assert "PAPER" in result
        assert "ARMED" in result

    def test_dry_run_disarmed(self):
        result = _format_execution_status(True, False, "dry_run")
        assert "DISARMED" in result

    def test_live_armed(self):
        result = _format_execution_status(True, True, "live")
        assert "LIVE" in result
        assert "ARMED" in result


# ---------------------------------------------------------------------------
# Performance line
# ---------------------------------------------------------------------------

class TestFormatPerformanceLine:
    def test_basic(self):
        result = format_performance_line(5, 2, 71.4, 350.00)
        assert "5W" in result
        assert "2L" in result
        assert "350" in result
