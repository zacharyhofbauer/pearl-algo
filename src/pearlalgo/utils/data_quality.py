"""
Data quality checking utilities.

Provides centralized data quality validation logic.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger


class DataQualityChecker:
    """
    Centralized data quality checking utilities.
    
    Provides methods to validate data freshness, completeness, and quality.
    """

    def __init__(self, stale_data_threshold_minutes: int = 10):
        """
        Initialize data quality checker.
        
        Args:
            stale_data_threshold_minutes: Threshold in minutes for considering data stale
        """
        self.stale_data_threshold_minutes = stale_data_threshold_minutes

    def check_data_freshness(
        self,
        latest_bar: Optional[Dict],
        df: Optional[pd.DataFrame] = None,
    ) -> Dict[str, Any]:
        """
        Check if data is fresh (not stale).
        
        Args:
            latest_bar: Latest bar dictionary with timestamp
            df: DataFrame with timestamp column (optional, used as fallback)
            
        Returns:
            Dictionary with:
            - is_fresh: bool - Whether data is fresh
            - age_minutes: float - Age of data in minutes
            - timestamp: Optional[datetime] - Timestamp of latest data
        """
        now = datetime.now(timezone.utc)
        timestamp: Optional[datetime] = None
        age_minutes = 0.0

        # Try to get timestamp from latest_bar
        if latest_bar and "timestamp" in latest_bar:
            timestamp = latest_bar["timestamp"]
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if isinstance(timestamp, datetime):
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age_minutes = (now - timestamp).total_seconds() / 60

        # Fallback to DataFrame if no latest_bar timestamp
        if timestamp is None and df is not None and not df.empty and "timestamp" in df.columns:
            latest_timestamp = df["timestamp"].max()
            if isinstance(latest_timestamp, pd.Timestamp):
                timestamp = latest_timestamp.to_pydatetime()
                if timestamp.tzinfo is None:
                    timestamp = timestamp.replace(tzinfo=timezone.utc)
                age_minutes = (now - timestamp).total_seconds() / 60

        is_fresh = age_minutes < self.stale_data_threshold_minutes

        return {
            "is_fresh": is_fresh,
            "age_minutes": age_minutes,
            "timestamp": timestamp,
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

