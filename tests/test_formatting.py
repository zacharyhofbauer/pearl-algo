"""Tests for pearlalgo.utils.formatting — pure functions, no mocking."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from pearlalgo.utils.formatting import (
    fmt_price,
    fmt_int,
    fmt_percent,
    fmt_number,
    fmt_number_commas,
    fmt_currency,
    fmt_pct_direct,
    pnl_emoji,
    format_pnl,
    format_duration,
    format_duration_short,
    format_hold_duration,
    format_time_ago,
    format_uptime,
    fmt_time_et,
)


# ---------------------------------------------------------------------------
# fmt_price
# ---------------------------------------------------------------------------

class TestFmtPrice:
    def test_valid_price(self):
        assert fmt_price(17500.25) == "$17500.25"

    def test_integer_price(self):
        assert fmt_price(100) == "$100.00"

    def test_none(self):
        assert fmt_price(None) == "N/A"

    def test_nan(self):
        assert fmt_price(float("nan")) == "N/A"

    def test_inf(self):
        assert fmt_price(float("inf")) == "N/A"

    def test_string_number(self):
        assert fmt_price("17500") == "$17500.00"

    def test_invalid_string(self):
        assert fmt_price("abc") == "N/A"

    def test_custom_default(self):
        assert fmt_price(None, default="?") == "?"


# ---------------------------------------------------------------------------
# fmt_int
# ---------------------------------------------------------------------------

class TestFmtInt:
    def test_valid_int(self):
        assert fmt_int(42) == "42"

    def test_float_truncated(self):
        assert fmt_int(42.7) == "42"

    def test_none(self):
        assert fmt_int(None) == "N/A"

    def test_nan(self):
        assert fmt_int(float("nan")) == "N/A"

    def test_inf(self):
        assert fmt_int(float("inf")) == "N/A"

    def test_string_int(self):
        assert fmt_int("99") == "99"

    def test_invalid_string(self):
        assert fmt_int("abc") == "N/A"

    def test_custom_default(self):
        assert fmt_int(None, default="?") == "?"


# ---------------------------------------------------------------------------
# fmt_percent
# ---------------------------------------------------------------------------

class TestFmtPercent:
    def test_half(self):
        assert fmt_percent(0.5) == "50.0%"

    def test_decimals(self):
        assert fmt_percent(0.1234, decimals=2) == "12.34%"

    def test_none(self):
        assert fmt_percent(None) == "N/A"

    def test_nan(self):
        assert fmt_percent(float("nan")) == "N/A"

    def test_inf(self):
        assert fmt_percent(float("inf")) == "N/A"

    def test_invalid(self):
        assert fmt_percent("abc") == "N/A"


# ---------------------------------------------------------------------------
# fmt_number
# ---------------------------------------------------------------------------

class TestFmtNumber:
    def test_basic(self):
        assert fmt_number(123.456) == "123.46"

    def test_decimals(self):
        assert fmt_number(123.456, decimals=1) == "123.5"

    def test_none(self):
        assert fmt_number(None) == "N/A"

    def test_nan(self):
        assert fmt_number(float("nan")) == "N/A"

    def test_invalid(self):
        assert fmt_number("abc") == "N/A"


# ---------------------------------------------------------------------------
# fmt_number_commas
# ---------------------------------------------------------------------------

class TestFmtNumberCommas:
    def test_basic(self):
        assert fmt_number_commas(1234.5) == "1,234.50"

    def test_show_sign_positive(self):
        assert fmt_number_commas(100, show_sign=True) == "+100.00"

    def test_show_sign_negative(self):
        result = fmt_number_commas(-100, show_sign=True)
        assert result == "-100.00"

    def test_none(self):
        assert fmt_number_commas(None) == "N/A"

    def test_nan(self):
        assert fmt_number_commas(float("nan")) == "N/A"

    def test_inf(self):
        assert fmt_number_commas(float("inf")) == "N/A"

    def test_invalid(self):
        assert fmt_number_commas("abc") == "N/A"


# ---------------------------------------------------------------------------
# fmt_currency
# ---------------------------------------------------------------------------

class TestFmtCurrency:
    def test_positive(self):
        assert fmt_currency(1234.56) == "$1,234.56"

    def test_negative(self):
        # Implementation produces $-50.25 (sign inside dollar)
        assert fmt_currency(-50.25) == "$-50.25"

    def test_show_sign(self):
        assert fmt_currency(100, show_sign=True) == "+$100.00"

    def test_none(self):
        assert fmt_currency(None) == "$0.00"

    def test_nan(self):
        assert fmt_currency(float("nan")) == "$0.00"

    def test_inf(self):
        assert fmt_currency(float("inf")) == "$0.00"

    def test_invalid(self):
        assert fmt_currency("abc") == "$0.00"


# ---------------------------------------------------------------------------
# fmt_pct_direct
# ---------------------------------------------------------------------------

class TestFmtPctDirect:
    def test_basic(self):
        assert fmt_pct_direct(50.5) == "50.5%"

    def test_none(self):
        assert fmt_pct_direct(None) == "0%"

    def test_nan(self):
        assert fmt_pct_direct(float("nan")) == "0%"

    def test_invalid(self):
        assert fmt_pct_direct("abc") == "0%"


# ---------------------------------------------------------------------------
# pnl_emoji / format_pnl
# ---------------------------------------------------------------------------

class TestPnlEmoji:
    def test_positive(self):
        assert pnl_emoji(100) == "🟢"

    def test_zero(self):
        assert pnl_emoji(0) == "🟢"

    def test_negative(self):
        assert pnl_emoji(-1) == "🔴"


class TestFormatPnl:
    def test_positive(self):
        emoji, text = format_pnl(125.50)
        assert emoji == "🟢"
        assert text == "+$125.50"

    def test_negative(self):
        emoji, text = format_pnl(-42.75)
        assert emoji == "🔴"
        assert text == "-$42.75"

    def test_zero(self):
        emoji, text = format_pnl(0)
        assert emoji == "🟢"
        assert text == "+$0.00"


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------

class TestFormatDuration:
    def test_none(self):
        assert format_duration(None) == "?"

    def test_none_with_suffix(self):
        assert format_duration(None, suffix=" ago") == "? ago"

    def test_invalid_string(self):
        assert format_duration("abc") == "?"

    def test_negative(self):
        assert format_duration(-1) == "?"

    def test_seconds(self):
        assert format_duration(45) == "45s"

    def test_minutes(self):
        assert format_duration(120) == "2m"

    def test_hours_with_minutes(self):
        assert format_duration(3 * 3600 + 15 * 60) == "3h 15m"

    def test_hours_with_minutes_compact(self):
        assert format_duration(3 * 3600 + 15 * 60, compact=True) == "3h15m"

    def test_hours_no_minutes(self):
        assert format_duration(3600) == "1h"

    def test_days_with_hours(self):
        assert format_duration(86400 + 3600) == "1d 1h"

    def test_days_with_hours_compact(self):
        assert format_duration(86400 + 3600, compact=True) == "1d1h"

    def test_days_no_hours(self):
        assert format_duration(86400) == "1d"

    def test_suffix(self):
        assert format_duration(45, suffix=" ago") == "45s ago"


class TestFormatDurationShort:
    def test_uses_compact(self):
        assert format_duration_short(3 * 3600 + 15 * 60) == "3h15m"

    def test_none(self):
        assert format_duration_short(None) == "?"


class TestFormatHoldDuration:
    def test_minutes(self):
        assert format_hold_duration(45) == "45m"

    def test_hours_and_minutes(self):
        assert format_hold_duration(135) == "2h 15m"


# ---------------------------------------------------------------------------
# format_time_ago
# ---------------------------------------------------------------------------

class TestFormatTimeAgo:
    def test_empty(self):
        assert format_time_ago(None) == ""
        assert format_time_ago("") == ""

    def test_recent(self):
        now = datetime.now(timezone.utc)
        ts = now.isoformat()
        result = format_time_ago(ts)
        assert "ago" in result or result == ""

    def test_invalid(self):
        assert format_time_ago("not-a-timestamp") == ""


# ---------------------------------------------------------------------------
# format_uptime
# ---------------------------------------------------------------------------

class TestFormatUptime:
    def test_hours_and_minutes(self):
        assert format_uptime({"hours": 3, "minutes": 15}) == "3h15m"

    def test_minutes_only(self):
        assert format_uptime({"minutes": 45}) == "45m"

    def test_empty(self):
        assert format_uptime({}) == "0s"


# ---------------------------------------------------------------------------
# fmt_time_et
# ---------------------------------------------------------------------------

class TestFmtTimeEt:
    def test_none(self):
        assert fmt_time_et(None) == "N/A"

    def test_custom_fallback(self):
        assert fmt_time_et(None, fallback="?") == "?"

    def test_utc_to_eastern(self):
        dt = datetime(2024, 1, 15, 15, 35, tzinfo=timezone.utc)
        result = fmt_time_et(dt)
        assert "ET" in result
        assert "10:35" in result

    def test_naive_datetime(self):
        dt = datetime(2024, 1, 15, 15, 35)
        result = fmt_time_et(dt)
        assert "ET" in result or "UTC" in result
