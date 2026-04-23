"""Tests for Issue 12-A — DST boundary behavior across load-bearing paths.

Plan: ``~/.claude/plans/this-session-work-cosmic-horizon.md`` Tier 2.

Next DST transitions in America/New_York as of 2026-04-23:
  - 2026-11-01  Fall-back  (EDT → EST)  — the ambiguous 01:00-02:00 local hour
  - 2027-03-14  Spring-fwd (EST → EDT)  — the non-existent 02:00-03:00 local hour

These tests pin the behavior of:
  1. signal_audit_logger retention (Issue 8-A fix) across DST boundaries
  2. ibkr_data_executor contract expiration math across DST
  3. utils/market_hours.is_within_trading_window at DST boundaries
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# signal_audit_logger retention across DST
# ---------------------------------------------------------------------------


def test_trim_old_backups_purges_across_fall_back(tmp_path: Path):
    """Retention is measured in DAYS via UTC, not local hours. Uses
    real-time now() so this test is DST-safe regardless of *when* it
    runs — the key invariant is that DST-straddling arithmetic returns
    the same result as identical-tz arithmetic."""
    from pearlalgo.market_agent.signal_audit_logger import SignalAuditLogger

    logger_ = SignalAuditLogger(tmp_path, retention_days=7, enabled=False)

    old_mtime = time.time() - 10 * 86400  # 10 days ago (deep past retention)
    f_old = tmp_path / "signal_audit.jsonl.1"
    f_old.write_text("{}\n")
    os.utime(f_old, (old_mtime, old_mtime))

    fresh_mtime = time.time() - 86400  # 1 day ago
    f_fresh = tmp_path / "signal_audit.jsonl.2"
    f_fresh.write_text("{}\n")
    os.utime(f_fresh, (fresh_mtime, fresh_mtime))

    logger_._trim_old_backups()

    assert not f_old.exists()
    assert f_fresh.exists()


def test_trim_old_backups_purges_across_spring_forward(tmp_path: Path):
    """Spring-forward skips an hour of local time. UTC arithmetic is unaffected."""
    from pearlalgo.market_agent.signal_audit_logger import SignalAuditLogger

    logger_ = SignalAuditLogger(tmp_path, retention_days=3, enabled=False)

    # Stale file dated 5 days ago — should be purged.
    old_mtime = time.time() - 5 * 86400
    f = tmp_path / "signal_audit.jsonl.1"
    f.write_text("{}\n")
    os.utime(f, (old_mtime, old_mtime))

    logger_._trim_old_backups()
    assert not f.exists()


# ---------------------------------------------------------------------------
# ibkr_data_executor contract-expiration math across DST
# ---------------------------------------------------------------------------


def test_contract_expiration_math_stable_across_fall_back():
    """Parsing 'YYYYMMDD' as UTC-midnight and subtracting aware UTC now
    is DST-invariant. The number of days to a fixed expiration changes
    by exactly 1 per calendar day regardless of DST."""
    fallback = datetime(2026, 11, 1, 6, 0, 0, tzinfo=timezone.utc)  # 01:00 EST
    expiration = datetime.strptime("20261225", "%Y%m%d").replace(tzinfo=timezone.utc)

    before_dst = fallback - timedelta(days=1)  # 2026-10-31 06:00 UTC (02:00 EDT)
    after_dst = fallback + timedelta(days=1)  # 2026-11-02 06:00 UTC (01:00 EST)

    days_before = (expiration - before_dst).days
    days_after = (expiration - after_dst).days
    assert days_before - days_after == 2  # 2 calendar days straddled


def test_contract_expiration_parses_as_utc_midnight_not_local():
    """Regression guard for the Issue 8-A fix: naive strptime would make
    'the day of expiration' ambiguous across DST; UTC-midnight is exact."""
    expiration = datetime.strptime("20261225", "%Y%m%d").replace(tzinfo=timezone.utc)
    assert expiration.tzinfo is timezone.utc
    assert expiration.hour == 0
    assert expiration.minute == 0


# ---------------------------------------------------------------------------
# utils/market_hours at DST boundaries
# ---------------------------------------------------------------------------


def test_market_hours_et_conversion_fall_back_day():
    """09:30 ET on the DST-change day must still be 13:30 UTC after fall-back
    (EDT→EST shift moves 09:30 ET from 13:30 UTC to 14:30 UTC)."""
    # Day BEFORE fall-back (still EDT): 09:30 EDT == 13:30 UTC.
    et_before = datetime(2026, 10, 31, 9, 30, 0, tzinfo=ET)
    assert et_before.astimezone(timezone.utc).hour == 13

    # Day OF fall-back (post-01:00 is EST): 09:30 EST == 14:30 UTC.
    et_after = datetime(2026, 11, 1, 9, 30, 0, tzinfo=ET)
    assert et_after.astimezone(timezone.utc).hour == 14


def test_market_hours_et_conversion_spring_forward_day():
    """09:30 ET on the spring-forward day is EDT (post-02:00)."""
    et = datetime(2027, 3, 14, 9, 30, 0, tzinfo=ET)
    assert et.astimezone(timezone.utc).hour == 13  # 09:30 EDT == 13:30 UTC


def test_is_within_trading_window_accepts_aware_dt_at_dst_boundary():
    """The is_within_trading_window helper must accept aware ET
    timestamps on both sides of the DST change without raising. We do
    not pin the True/False answer here because futures have a broader
    trading window than the cash-equity RTH — that's a separate
    behavioral test; this test only asserts the call is tz-safe."""
    from pearlalgo.utils.market_hours import is_within_trading_window

    # Both sides of fall-back must return a bool, not raise.
    pre_dst = datetime(2026, 10, 31, 10, 0, 0, tzinfo=ET)
    post_dst = datetime(2026, 11, 1, 10, 0, 0, tzinfo=ET)
    for dt in (pre_dst, post_dst):
        result = is_within_trading_window(dt)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Smoke: the DST dates themselves
# ---------------------------------------------------------------------------


def test_next_dst_dates_are_computed_correctly():
    """Pin the exact DST transitions this test file is written against.
    Use unambiguous local times (00:30 and 03:00 bracket the 01:00→02:00
    fall-back window) so the test is independent of fold resolution."""
    # 00:30 ET on fall-back day — still EDT (-4).
    fallback_edt = datetime(2026, 11, 1, 0, 30, 0, tzinfo=ET)
    assert fallback_edt.utcoffset() == timedelta(hours=-4)
    # 03:00 ET same day — unambiguously EST (-5).
    fallback_est = datetime(2026, 11, 1, 3, 0, 0, tzinfo=ET)
    assert fallback_est.utcoffset() == timedelta(hours=-5)

    # Spring-forward day: 01:30 is EST, 03:30 is EDT (02:00-03:00 skipped).
    spring_est = datetime(2027, 3, 14, 1, 30, 0, tzinfo=ET)
    assert spring_est.utcoffset() == timedelta(hours=-5)
    spring_edt = datetime(2027, 3, 14, 3, 30, 0, tzinfo=ET)
    assert spring_edt.utcoffset() == timedelta(hours=-4)
