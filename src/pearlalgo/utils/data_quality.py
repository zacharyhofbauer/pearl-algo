"""
Data quality checking utilities.

Provides centralized data quality validation logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd



class DataQualityChecker:
    """
    Centralized data quality checking utilities.
    
    Provides methods to validate data freshness, completeness, and quality.
    """

    # Market-closed staleness threshold (60 minutes) - expected when markets are closed
    MARKET_CLOSED_STALE_THRESHOLD_MINUTES = 60

    def __init__(self, stale_data_threshold_minutes: int = 10):
        """
        Initialize data quality checker.
        
        Args:
            stale_data_threshold_minutes: Threshold in minutes for considering data stale
                                          (used when market is open)
        """
        self.stale_data_threshold_minutes = stale_data_threshold_minutes

    def check_data_freshness(
        self,
        latest_bar: Optional[Dict],
        df: Optional[pd.DataFrame] = None,
        market_open: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Check if data is fresh (not stale).
        
        Uses market-aware thresholds:
        - When market is open (market_open=True): strict threshold (default 10 min)
        - When market is closed (market_open=False): relaxed threshold (60 min)
        - When market_open=None: uses strict threshold (default behavior)
        
        Args:
            latest_bar: Latest bar dictionary with timestamp
            df: DataFrame with timestamp column or DatetimeIndex (optional, used as fallback)
            market_open: Whether the futures market is currently open (None = use strict threshold)
            
        Returns:
            Dictionary with:
            - is_fresh: bool - Whether data is fresh
            - age_minutes: float - Age of data in minutes
            - timestamp: Optional[datetime] - Timestamp of latest data
            - threshold_minutes: float - The threshold used for freshness check
            - market_aware: bool - Whether market-aware threshold was applied
        """
        now = datetime.now(timezone.utc)
        timestamp: Optional[datetime] = None
        age_minutes = 0.0

        # Try to get timestamp from latest_bar
        if latest_bar and "timestamp" in latest_bar:
            timestamp = latest_bar["timestamp"]
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            # Handle pd.Timestamp from latest_bar
            if isinstance(timestamp, pd.Timestamp):
                timestamp = timestamp.to_pydatetime()
            if isinstance(timestamp, datetime):
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age_minutes = (now - timestamp).total_seconds() / 60

        # Fallback to DataFrame if no latest_bar timestamp
        if timestamp is None and df is not None and not df.empty:
            latest_timestamp = None
            
            # First, try timestamp column (bars-only contract preference)
            if "timestamp" in df.columns:
                latest_timestamp = df["timestamp"].max()
            # Fallback: check for DatetimeIndex (some providers use index-based timestamps)
            elif isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 0:
                latest_timestamp = df.index.max()
            
            # Convert to datetime and compute age
            if latest_timestamp is not None:
                if isinstance(latest_timestamp, pd.Timestamp):
                    timestamp = latest_timestamp.to_pydatetime()
                elif isinstance(latest_timestamp, datetime):
                    timestamp = latest_timestamp
                    
                if timestamp is not None:
                    if timestamp.tzinfo is None:
                        timestamp = timestamp.replace(tzinfo=timezone.utc)
                    age_minutes = (now - timestamp).total_seconds() / 60

        # Market-aware threshold selection
        # When market is closed, stale data is expected - use relaxed threshold
        # When market is open (or unknown), use strict threshold
        if market_open is False:
            threshold = self.MARKET_CLOSED_STALE_THRESHOLD_MINUTES
            market_aware = True
        else:
            threshold = self.stale_data_threshold_minutes
            market_aware = market_open is not None

        is_fresh = age_minutes < threshold

        return {
            "is_fresh": is_fresh,
            "age_minutes": age_minutes,
            "timestamp": timestamp,
            "threshold_minutes": threshold,
            "market_aware": market_aware,
        }

    def check_data_completeness(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Check if data is complete (no missing values).
        
        Args:
            df: DataFrame to check
            
        Returns:
            Dictionary with:
            - is_complete: bool - Whether data is complete
            - missing_counts: Dict - Count of missing values per column
        """
        if df is None or df.empty:
            return {
                "is_complete": False,
                "missing_counts": {},
            }

        missing = df.isnull().sum()
        missing_dict = {col: int(missing[col]) for col in missing.index if missing[col] > 0}

        return {
            "is_complete": len(missing_dict) == 0,
            "missing_counts": missing_dict,
        }

    def check_buffer_size(self, buffer_size: int, min_size: int = 10) -> Dict[str, Any]:
        """
        Check if buffer size is adequate.
        
        Args:
            buffer_size: Current buffer size
            min_size: Minimum acceptable buffer size
            
        Returns:
            Dictionary with:
            - is_adequate: bool - Whether buffer size is adequate
            - buffer_size: int - Current buffer size
        """
        return {
            "is_adequate": buffer_size >= min_size,
            "buffer_size": buffer_size,
        }

    def validate_market_data(self, market_data: Dict) -> Dict[str, Any]:
        """
        Comprehensive market data validation.
        
        Args:
            market_data: Market data dictionary with 'df' and optionally 'latest_bar'
            
        Returns:
            Dictionary with validation results:
            - is_valid: bool - Overall validity
            - freshness: Dict - Freshness check results
            - completeness: Dict - Completeness check results
            - buffer_size: Dict - Buffer size check results
            - issues: List[str] - List of issues found
        """
        df = market_data.get("df")
        latest_bar = market_data.get("latest_bar")

        issues: list[str] = []

        # Check freshness
        freshness = self.check_data_freshness(latest_bar, df)
        if not freshness["is_fresh"]:
            issues.append(f"Data is stale: {freshness['age_minutes']:.1f} minutes old")

        # Check completeness
        if df is not None:
            completeness = self.check_data_completeness(df)
            if not completeness["is_complete"]:
                issues.append(f"Data has missing values: {completeness['missing_counts']}")
        else:
            completeness = {"is_complete": False, "missing_counts": {}}
            issues.append("No DataFrame available")

        # Check buffer size
        buffer_size = len(df) if df is not None else 0
        buffer_check = self.check_buffer_size(buffer_size)
        if not buffer_check["is_adequate"]:
            issues.append(f"Buffer size is low: {buffer_size} bars")

        return {
            "is_valid": len(issues) == 0,
            "freshness": freshness,
            "completeness": completeness,
            "buffer_size": buffer_check,
            "issues": issues,
        }






