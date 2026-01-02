"""
Tests for DataQualityChecker.

Verifies freshness checks work with both timestamp column and DatetimeIndex.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from pearlalgo.utils.data_quality import DataQualityChecker


class TestCheckDataFreshness:
    """Tests for check_data_freshness method."""

    def test_fresh_data_from_latest_bar(self) -> None:
        """Latest bar with recent timestamp should be considered fresh."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        # Timestamp from 2 minutes ago
        recent_ts = datetime.now(timezone.utc) - timedelta(minutes=2)
        latest_bar = {"timestamp": recent_ts, "close": 17500.0}
        
        result = checker.check_data_freshness(latest_bar)
        
        assert result["is_fresh"] is True
        assert result["age_minutes"] < 10
        assert result["timestamp"] == recent_ts

    def test_stale_data_from_latest_bar(self) -> None:
        """Latest bar with old timestamp should be considered stale."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        # Timestamp from 15 minutes ago
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=15)
        latest_bar = {"timestamp": old_ts, "close": 17500.0}
        
        result = checker.check_data_freshness(latest_bar)
        
        assert result["is_fresh"] is False
        assert result["age_minutes"] > 10

    def test_fresh_data_from_df_timestamp_column(self) -> None:
        """DataFrame with timestamp column should be used when latest_bar is None."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        # Create DataFrame with timestamp column
        recent_ts = datetime.now(timezone.utc) - timedelta(minutes=3)
        df = pd.DataFrame({
            "timestamp": [
                recent_ts - timedelta(minutes=10),
                recent_ts - timedelta(minutes=5),
                recent_ts,  # Latest
            ],
            "close": [17500.0, 17505.0, 17510.0],
        })
        
        result = checker.check_data_freshness(None, df)
        
        assert result["is_fresh"] is True
        assert result["age_minutes"] < 10
        assert result["timestamp"] is not None

    def test_fresh_data_from_df_datetime_index(self) -> None:
        """DataFrame with DatetimeIndex should be used as fallback."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        # Create DataFrame with DatetimeIndex (no timestamp column)
        recent_ts = datetime.now(timezone.utc) - timedelta(minutes=3)
        timestamps = pd.DatetimeIndex([
            recent_ts - timedelta(minutes=10),
            recent_ts - timedelta(minutes=5),
            recent_ts,  # Latest
        ])
        df = pd.DataFrame({
            "close": [17500.0, 17505.0, 17510.0],
        }, index=timestamps)
        
        result = checker.check_data_freshness(None, df)
        
        assert result["is_fresh"] is True
        assert result["age_minutes"] < 10
        assert result["timestamp"] is not None

    def test_stale_data_from_df_datetime_index(self) -> None:
        """Old DatetimeIndex should be detected as stale."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        # Create DataFrame with old DatetimeIndex
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=20)
        timestamps = pd.DatetimeIndex([
            old_ts - timedelta(minutes=10),
            old_ts - timedelta(minutes=5),
            old_ts,  # Latest is still 20 minutes ago
        ])
        df = pd.DataFrame({
            "close": [17500.0, 17505.0, 17510.0],
        }, index=timestamps)
        
        result = checker.check_data_freshness(None, df)
        
        assert result["is_fresh"] is False
        assert result["age_minutes"] > 10

    def test_latest_bar_takes_precedence_over_df(self) -> None:
        """Latest bar timestamp should be used even when df is provided."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        # Fresh latest_bar
        fresh_ts = datetime.now(timezone.utc) - timedelta(minutes=1)
        latest_bar = {"timestamp": fresh_ts, "close": 17520.0}
        
        # Stale DataFrame (should be ignored)
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=30)
        df = pd.DataFrame({
            "timestamp": [old_ts],
            "close": [17500.0],
        })
        
        result = checker.check_data_freshness(latest_bar, df)
        
        assert result["is_fresh"] is True
        assert result["age_minutes"] < 5

    def test_string_timestamp_parsing(self) -> None:
        """String timestamps should be parsed correctly."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        # ISO format string timestamp
        recent_ts = datetime.now(timezone.utc) - timedelta(minutes=2)
        latest_bar = {"timestamp": recent_ts.isoformat(), "close": 17500.0}
        
        result = checker.check_data_freshness(latest_bar)
        
        assert result["is_fresh"] is True
        assert result["timestamp"] is not None

    def test_pd_timestamp_in_latest_bar(self) -> None:
        """pd.Timestamp in latest_bar should be handled correctly."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        # pd.Timestamp from 2 minutes ago
        recent_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=2)
        latest_bar = {"timestamp": recent_ts, "close": 17500.0}
        
        result = checker.check_data_freshness(latest_bar)
        
        assert result["is_fresh"] is True
        assert result["age_minutes"] < 10

    def test_empty_df_returns_not_fresh(self) -> None:
        """Empty DataFrame should return default (not fresh based on 0 age)."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        result = checker.check_data_freshness(None, pd.DataFrame())
        
        # With 0 age_minutes, it should be considered "fresh" (age < threshold)
        # But timestamp should be None
        assert result["timestamp"] is None
        assert result["age_minutes"] == 0.0

    def test_none_inputs_returns_fresh_with_zero_age(self) -> None:
        """No inputs should return fresh=True with 0 age (edge case)."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        result = checker.check_data_freshness(None, None)
        
        assert result["timestamp"] is None
        assert result["age_minutes"] == 0.0
        # 0 < 10, so technically "fresh" but no actual data
        assert result["is_fresh"] is True


class TestValidateMarketData:
    """Tests for validate_market_data method."""

    def test_valid_market_data(self) -> None:
        """Fresh data with adequate buffer should be valid."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        recent_ts = datetime.now(timezone.utc) - timedelta(minutes=2)
        market_data = {
            "df": pd.DataFrame({
                "timestamp": [recent_ts - timedelta(minutes=i) for i in range(20, 0, -1)],
                "open": [17500.0] * 20,
                "high": [17510.0] * 20,
                "low": [17490.0] * 20,
                "close": [17505.0] * 20,
                "volume": [1000] * 20,
            }),
            "latest_bar": {"timestamp": recent_ts, "close": 17505.0},
        }
        
        result = checker.validate_market_data(market_data)
        
        assert result["is_valid"] is True
        assert len(result["issues"]) == 0

    def test_stale_data_flagged(self) -> None:
        """Stale data should be flagged as an issue."""
        checker = DataQualityChecker(stale_data_threshold_minutes=10)
        
        old_ts = datetime.now(timezone.utc) - timedelta(minutes=30)
        market_data = {
            "df": pd.DataFrame({
                "timestamp": [old_ts],
                "close": [17500.0],
            }),
            "latest_bar": {"timestamp": old_ts, "close": 17500.0},
        }
        
        result = checker.validate_market_data(market_data)
        
        assert result["is_valid"] is False
        assert any("stale" in issue.lower() for issue in result["issues"])













