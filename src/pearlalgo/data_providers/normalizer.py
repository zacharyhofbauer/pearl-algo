"""
Data Normalization Layer for consistent data format across providers.

Normalizes data from different providers into a standard internal format.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class DataNormalizer:
    """
    Normalizes market data from various providers into consistent format.

    Standard format:
    - OHLCV: timestamp (index), open, high, low, close, volume
    - Quotes: bid, ask, last, volume, timestamp
    - Options: symbol, strike, expiration, type, bid, ask, volume, greeks
    """

    @staticmethod
    def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize OHLCV DataFrame to standard format.

        Args:
            df: DataFrame with OHLCV data (may have various column names)

        Returns:
            Normalized DataFrame with columns: open, high, low, close, volume
            indexed by timestamp
        """
        if df.empty:
            return df

        df_normalized = df.copy()

        # Ensure timestamp index
        if "timestamp" in df_normalized.columns:
            df_normalized.set_index("timestamp", inplace=True)
        elif not isinstance(df_normalized.index, pd.DatetimeIndex):
            logger.warning(
                "DataFrame does not have DatetimeIndex, attempting conversion..."
            )
            try:
                df_normalized.index = pd.to_datetime(df_normalized.index)
            except Exception as e:
                logger.error(f"Could not convert index to DatetimeIndex: {e}")
                return pd.DataFrame()

        # Standardize column names (case-insensitive)
        column_mapping = {}
        for col in df_normalized.columns:
            col_lower = str(col).lower()
            if col_lower in ["open", "o"]:
                column_mapping[col] = "open"
            elif col_lower in ["high", "h"]:
                column_mapping[col] = "high"
            elif col_lower in ["low", "l"]:
                column_mapping[col] = "low"
            elif col_lower in ["close", "c", "last"]:
                column_mapping[col] = "close"
            elif col_lower in ["volume", "v", "vol"]:
                column_mapping[col] = "volume"

        df_normalized.rename(columns=column_mapping, inplace=True)

        # Ensure required columns exist
        required_cols = ["open", "high", "low", "close"]
        missing_cols = [col for col in required_cols if col not in df_normalized.columns]

        if missing_cols:
            logger.error(
                f"Missing required columns after normalization: {missing_cols}"
            )
            return pd.DataFrame()

        # Add volume if missing (default to 0)
        if "volume" not in df_normalized.columns:
            df_normalized["volume"] = 0
            logger.warning("Volume column missing, defaulting to 0")

        # Ensure numeric types
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df_normalized.columns:
                df_normalized[col] = pd.to_numeric(
                    df_normalized[col], errors="coerce"
                )

        # Sort by timestamp
        df_normalized.sort_index(inplace=True)

        # Remove any rows with NaN in critical columns
        df_normalized = df_normalized.dropna(subset=["open", "high", "low", "close"])

        return df_normalized[["open", "high", "low", "close", "volume"]]

    @staticmethod
    def normalize_quote(quote: Dict) -> Dict:
        """
        Normalize quote data to standard format.

        Args:
            quote: Dict with quote data (may have various keys)

        Returns:
            Normalized dict with: bid, ask, last, volume, timestamp
        """
        if not quote:
            return {}

        normalized = {}

        # Map various key names to standard names
        key_mappings = {
            "bid": ["bid", "b", "bid_price"],
            "ask": ["ask", "a", "ask_price", "offer"],
            "last": ["last", "last_price", "close", "c", "price"],
            "volume": ["volume", "v", "vol"],
            "timestamp": ["timestamp", "time", "date", "datetime"],
        }

        quote_lower = {str(k).lower(): v for k, v in quote.items()}

        for standard_key, possible_keys in key_mappings.items():
            for key in possible_keys:
                if key in quote_lower:
                    normalized[standard_key] = quote_lower[key]
                    break

        # Convert timestamp to datetime if needed
        if "timestamp" in normalized:
            if not isinstance(normalized["timestamp"], datetime):
                try:
                    normalized["timestamp"] = pd.to_datetime(
                        normalized["timestamp"]
                    )
                except Exception as e:
                    logger.warning(f"Could not parse timestamp: {e}")
                    normalized["timestamp"] = datetime.now()

        # Ensure numeric types
        for key in ["bid", "ask", "last", "volume"]:
            if key in normalized:
                try:
                    normalized[key] = float(normalized[key])
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert {key} to float")
                    normalized.pop(key, None)

        return normalized

    @staticmethod
    def normalize_options_chain(options: List[Dict]) -> List[Dict]:
        """
        Normalize options chain data to standard format.

        Args:
            options: List of option contract dicts

        Returns:
            List of normalized option dicts with standard keys
        """
        if not options:
            return []

        normalized = []

        for opt in options:
            normalized_opt = {}

            # Map various key names
            key_mappings = {
                "symbol": ["symbol", "ticker", "contract_symbol"],
                "strike": ["strike", "strike_price", "strikePrice"],
                "expiration": [
                    "expiration",
                    "expiration_date",
                    "exp_date",
                    "expiry",
                ],
                "option_type": [
                    "option_type",
                    "type",
                    "contract_type",
                    "call_put",
                ],
                "bid": ["bid", "bid_price", "b"],
                "ask": ["ask", "ask_price", "a", "offer"],
                "last": ["last", "last_price", "price"],
                "volume": ["volume", "v"],
                "open_interest": ["open_interest", "oi", "openInterest"],
                "greeks": ["greeks", "greek"],
            }

            opt_lower = {str(k).lower(): v for k, v in opt.items()}

            for standard_key, possible_keys in key_mappings.items():
                for key in possible_keys:
                    if key in opt_lower:
                        normalized_opt[standard_key] = opt_lower[key]
                        break

            # Normalize option type
            if "option_type" in normalized_opt:
                opt_type = str(normalized_opt["option_type"]).lower()
                if opt_type in ["call", "c"]:
                    normalized_opt["option_type"] = "call"
                elif opt_type in ["put", "p"]:
                    normalized_opt["option_type"] = "put"

            # Normalize Greeks if present
            if "greeks" in normalized_opt:
                greeks = normalized_opt["greeks"]
                if isinstance(greeks, dict):
                    normalized_greeks = {}
                    for greek_name in ["delta", "gamma", "theta", "vega", "rho"]:
                        if greek_name in greeks:
                            try:
                                normalized_greeks[greek_name] = float(
                                    greeks[greek_name]
                                )
                            except (ValueError, TypeError):
                                pass
                    normalized_opt["greeks"] = normalized_greeks

            # Ensure numeric types
            numeric_keys = [
                "strike",
                "bid",
                "ask",
                "last",
                "volume",
                "open_interest",
            ]
            for key in numeric_keys:
                if key in normalized_opt:
                    try:
                        normalized_opt[key] = float(normalized_opt[key])
                    except (ValueError, TypeError):
                        normalized_opt.pop(key, None)

            normalized.append(normalized_opt)

        return normalized

    @staticmethod
    def validate_ohlcv(df: pd.DataFrame) -> bool:
        """
        Validate OHLCV DataFrame has correct structure.

        Args:
            df: DataFrame to validate

        Returns:
            True if valid, False otherwise
        """
        if df.empty:
            return False

        if not isinstance(df.index, pd.DatetimeIndex):
            logger.error("DataFrame must have DatetimeIndex")
            return False

        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in df.columns]

        if missing_cols:
            logger.error(f"Missing required columns: {missing_cols}")
            return False

        # Check for invalid values
        if df[["open", "high", "low", "close"]].isnull().any().any():
            logger.warning("DataFrame contains NaN values in OHLC columns")
            return False

        # Check OHLC logic (high >= low, high >= open/close, low <= open/close)
        invalid = (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
        )

        if invalid.any():
            logger.warning(
                f"Found {invalid.sum()} rows with invalid OHLC relationships"
            )
            # Don't return False for this, just log warning

        return True


