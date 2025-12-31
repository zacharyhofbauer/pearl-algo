"""
Tests for market-aware staleness thresholds in DataQualityChecker.

Verifies that:
- Market-closed periods use relaxed threshold (60 min)
- Market-open periods use strict threshold (default 10 min)
- Default behavior (market_open=None) uses strict threshold
"""

import pytest
from datetime import datetime, timezone, timedelta

import pandas as pd


class TestMarketAwareStaleness:
    """Tests for market-aware staleness checking."""

    def test_market_closed_allows_longer_staleness(self):
        """When market is closed, 30-minute-old data should be considered fresh."""
        from pearlalgo.utils.data_quality import DataQualityChecker

        checker = DataQualityChecker(stale_data_threshold_minutes=10)

        # Data that is 30 minutes old
        now = datetime.now(timezone.utc)
        old_timestamp = now - timedelta(minutes=30)

        latest_bar = {"timestamp": old_timestamp}

        # With market closed, 30 min should be fresh (threshold is 60 min)
        result = checker.check_data_freshness(latest_bar, market_open=False)

        assert result["is_fresh"] is True
        assert result["age_minutes"] == pytest.approx(30.0, abs=0.5)
        assert result["threshold_minutes"] == 60.0
        assert result["market_aware"] is True

    def test_market_open_enforces_strict_threshold(self):
        """When market is open, 30-minute-old data should be considered stale."""
        from pearlalgo.utils.data_quality import DataQualityChecker

        checker = DataQualityChecker(stale_data_threshold_minutes=10)

        # Data that is 30 minutes old
        now = datetime.now(timezone.utc)
        old_timestamp = now - timedelta(minutes=30)

        latest_bar = {"timestamp": old_timestamp}

        # With market open, 30 min should be stale (threshold is 10 min)
        result = checker.check_data_freshness(latest_bar, market_open=True)

        assert result["is_fresh"] is False
        assert result["age_minutes"] == pytest.approx(30.0, abs=0.5)
        assert result["threshold_minutes"] == 10.0
        assert result["market_aware"] is True

    def test_market_unknown_uses_strict_threshold(self):
        """When market status is unknown (None), use strict threshold."""
        from pearlalgo.utils.data_quality import DataQualityChecker

        checker = DataQualityChecker(stale_data_threshold_minutes=10)

        # Data that is 15 minutes old
        now = datetime.now(timezone.utc)
        old_timestamp = now - timedelta(minutes=15)

        latest_bar = {"timestamp": old_timestamp}

        # With market status unknown, 15 min should be stale (threshold is 10 min)
        result = checker.check_data_freshness(latest_bar, market_open=None)

        assert result["is_fresh"] is False
        assert result["age_minutes"] == pytest.approx(15.0, abs=0.5)
        assert result["threshold_minutes"] == 10.0
        assert result["market_aware"] is False

    def test_fresh_data_is_fresh_regardless_of_market(self):
        """Very fresh data (<5 min) should be fresh regardless of market status."""
        from pearlalgo.utils.data_quality import DataQualityChecker

        checker = DataQualityChecker(stale_data_threshold_minutes=10)

        # Data that is 5 minutes old
        now = datetime.now(timezone.utc)
        fresh_timestamp = now - timedelta(minutes=5)

        latest_bar = {"timestamp": fresh_timestamp}

        # Fresh data should be fresh with market open
        result_open = checker.check_data_freshness(latest_bar, market_open=True)
        assert result_open["is_fresh"] is True

        # Fresh data should be fresh with market closed
        result_closed = checker.check_data_freshness(latest_bar, market_open=False)
        assert result_closed["is_fresh"] is True

        # Fresh data should be fresh with market unknown
        result_unknown = checker.check_data_freshness(latest_bar, market_open=None)
        assert result_unknown["is_fresh"] is True

    def test_very_stale_data_is_stale_regardless_of_market(self):
        """Very stale data (>60 min) should be stale even when market is closed."""
        from pearlalgo.utils.data_quality import DataQualityChecker

        checker = DataQualityChecker(stale_data_threshold_minutes=10)

        # Data that is 90 minutes old
        now = datetime.now(timezone.utc)
        very_old_timestamp = now - timedelta(minutes=90)

        latest_bar = {"timestamp": very_old_timestamp}

        # 90 min stale should be stale even with market closed (60 min threshold)
        result = checker.check_data_freshness(latest_bar, market_open=False)

        assert result["is_fresh"] is False
        assert result["age_minutes"] == pytest.approx(90.0, abs=0.5)
        assert result["threshold_minutes"] == 60.0

    def test_backward_compatibility_without_market_open(self):
        """Calling without market_open parameter should work (backward compatible)."""
        from pearlalgo.utils.data_quality import DataQualityChecker

        checker = DataQualityChecker(stale_data_threshold_minutes=10)

        now = datetime.now(timezone.utc)
        timestamp = now - timedelta(minutes=5)

        latest_bar = {"timestamp": timestamp}

        # Should work without market_open parameter (defaults to None)
        result = checker.check_data_freshness(latest_bar)

        assert result["is_fresh"] is True
        assert result["age_minutes"] == pytest.approx(5.0, abs=0.5)
        assert result["threshold_minutes"] == 10.0  # Strict threshold
        assert result["market_aware"] is False  # No market info provided

    def test_constant_threshold_value(self):
        """Verify the market-closed threshold constant is 60 minutes."""
        from pearlalgo.utils.data_quality import DataQualityChecker

        assert DataQualityChecker.MARKET_CLOSED_STALE_THRESHOLD_MINUTES == 60


