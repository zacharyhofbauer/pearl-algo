"""
Tests for market hours configuration loading from config.yaml.

Verifies that holiday_overrides and early_closes can be loaded from config
when enabled, and that the default behavior remains unchanged when disabled.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from pearlalgo.config.config_loader import load_market_hours_overrides
from pearlalgo.utils.market_hours import (
    MarketHours,
    configure_market_hours,
    get_market_hours,
    reset_market_hours,
)


def _to_utc(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    """Build an ET datetime and convert to UTC for stable assertions."""
    et = ZoneInfo("America/New_York")
    return datetime(year, month, day, hour, minute, tzinfo=et).astimezone(timezone.utc)


class TestMarketHoursConfigLoading:
    """Tests for _load_market_hours_config function."""
    
    def test_disabled_by_default(self):
        """When enable_config_overrides is False, should return empty sets."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": False,
                    "holiday_overrides": [[2025, 11, 27]],
                    "early_closes": {"2025-11-26": 13},
                }
            }
            
            holidays, early = load_market_hours_overrides()
            
            assert len(holidays) == 0
            assert len(early) == 0
    
    def test_enabled_loads_holidays(self):
        """When enabled, should load holiday_overrides from config."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": True,
                    "holiday_overrides": [
                        [2025, 11, 27],  # Thanksgiving
                        [2025, 3, 28],   # Good Friday
                    ],
                    "early_closes": {},
                }
            }
            
            holidays, early = load_market_hours_overrides()
            
            assert (2025, 11, 27) in holidays
            assert (2025, 3, 28) in holidays
            assert len(holidays) == 2
    
    def test_enabled_loads_early_closes(self):
        """When enabled, should load early_closes from config."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": True,
                    "holiday_overrides": [],
                    "early_closes": {
                        "2025-11-26": 13,  # Day before Thanksgiving
                        "2025-12-24": 13,  # Christmas Eve
                    },
                }
            }
            
            holidays, early = load_market_hours_overrides()
            
            assert (2025, 11, 26) in early
            assert early[(2025, 11, 26)] == 13
            assert (2025, 12, 24) in early
            assert early[(2025, 12, 24)] == 13
    
    def test_handles_malformed_holiday_data(self):
        """Should gracefully handle malformed holiday data."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": True,
                    "holiday_overrides": [
                        [2025, 11, 27],      # Valid
                        [2025, 11],          # Too few elements
                        "not-a-list",        # Invalid type
                        [2025, "bad", 27],   # Invalid element type
                    ],
                    "early_closes": {},
                }
            }
            
            holidays, early = load_market_hours_overrides()
            
            # Should only include the valid entry
            assert len(holidays) == 1
            assert (2025, 11, 27) in holidays
    
    def test_handles_malformed_early_close_data(self):
        """Should gracefully handle malformed early close data."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": True,
                    "holiday_overrides": [],
                    "early_closes": {
                        "2025-11-26": 13,     # Valid
                        "bad-format": 13,     # Invalid date format
                        "2025-11-27": "13pm", # Invalid hour type
                    },
                }
            }
            
            holidays, early = load_market_hours_overrides()
            
            # Should only include the valid entry
            assert len(early) == 1
            assert (2025, 11, 26) in early
    
    def test_handles_missing_config_loader(self):
        """Should return empty when config loader import fails."""
        with patch('pearlalgo.config.config_loader.load_service_config', side_effect=ImportError):
            holidays, early = load_market_hours_overrides()
            
            assert len(holidays) == 0
            assert len(early) == 0


class TestGetMarketHoursWithConfig:
    """Tests for get_market_hours() with config loading."""
    
    def setup_method(self):
        """Reset global instance before each test."""
        reset_market_hours()
    
    def teardown_method(self):
        """Reset global instance after each test."""
        reset_market_hours()
    
    def test_uses_config_overrides_when_enabled(self):
        """get_market_hours should use config overrides when enabled."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": True,
                    "holiday_overrides": [[2025, 6, 15]],  # Random Sunday
                    "early_closes": {},
                }
            }
            
            holidays, early_closes = load_market_hours_overrides()
            configure_market_hours(holiday_overrides=holidays, early_closes=early_closes)
            mh = get_market_hours()
            
            # June 15, 2025 is a Sunday - normally market opens at 6 PM
            # But with holiday override, it should be closed all day
            # Note: After 6 PM on a non-holiday Sunday, market would be open
            dt_after_6pm = _to_utc(2025, 6, 15, 19, 0)
            
            # Should be closed due to holiday override
            assert mh.is_market_open(dt_after_6pm) is False
    
    def test_early_close_applied(self):
        """get_market_hours should apply early close from config."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": True,
                    "holiday_overrides": [],
                    "early_closes": {
                        "2025-06-16": 13,  # Monday with 1 PM close
                    },
                }
            }
            
            holidays, early_closes = load_market_hours_overrides()
            configure_market_hours(holiday_overrides=holidays, early_closes=early_closes)
            mh = get_market_hours()
            
            # June 16, 2025 is Monday
            # At 12:30 ET - should be open
            assert mh.is_market_open(_to_utc(2025, 6, 16, 12, 30)) is True
            
            # At 13:30 ET - should be closed due to early close
            assert mh.is_market_open(_to_utc(2025, 6, 16, 13, 30)) is False
    
    def test_returns_same_instance(self):
        """get_market_hours should return the same cached instance."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": False,
                    "holiday_overrides": [],
                    "early_closes": {},
                }
            }
            
            holidays, early_closes = load_market_hours_overrides()
            configure_market_hours(holiday_overrides=holidays, early_closes=early_closes)
            mh1 = get_market_hours()
            mh2 = get_market_hours()
            
            assert mh1 is mh2
    
    def test_reset_clears_instance(self):
        """reset_market_hours should clear the cached instance."""
        with patch('pearlalgo.config.config_loader.load_service_config') as mock_config:
            mock_config.return_value = {
                "market_hours": {
                    "enable_config_overrides": False,
                    "holiday_overrides": [],
                    "early_closes": {},
                }
            }
            
            holidays, early_closes = load_market_hours_overrides()
            configure_market_hours(holiday_overrides=holidays, early_closes=early_closes)
            mh1 = get_market_hours()
            reset_market_hours()
            mh2 = get_market_hours()
            
            assert mh1 is not mh2

