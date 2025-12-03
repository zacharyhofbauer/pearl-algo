"""
Tradier API Data Provider for options chains and market data.

Tradier provides free market data with a trading account and is excellent
for options chains and real-time quotes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

import pandas as pd
import requests

from pearlalgo.data_providers.base import DataProvider

logger = logging.getLogger(__name__)


class TradierDataProvider(DataProvider):
    """
    Tradier API data provider for options chains and market data.

    Supports:
    - Options chains
    - Real-time quotes
    - Historical OHLCV data
    - Account-based (free data with trading account)
    """

    def __init__(
        self,
        api_key: str,
        account_id: Optional[str] = None,
        sandbox: bool = True,
    ):
        """
        Initialize Tradier data provider.

        Args:
            api_key: Tradier API key
            account_id: Tradier account ID (optional, for account-specific endpoints)
            sandbox: Use sandbox endpoint (default: True)
        """
        self.api_key = api_key
        self.account_id = account_id
        self.sandbox = sandbox
        self.base_url = (
            "https://sandbox.tradier.com"
            if sandbox
            else "https://api.tradier.com"
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            }
        )

    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch historical OHLCV data.

        Args:
            symbol: Ticker symbol
            start: Start datetime
            end: End datetime
            timeframe: Not used by Tradier (uses daily by default)

        Returns:
            DataFrame with OHLCV data
        """
        if start is None:
            start = datetime.now(timezone.utc).replace(
                year=datetime.now(timezone.utc).year - 1
            )
        if end is None:
            end = datetime.now(timezone.utc)

        # Tradier uses YYYY-MM-DD format
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        url = f"{self.base_url}/v1/markets/history"
        params = {
            "symbol": symbol,
            "interval": "daily",
            "start": start_str,
            "end": end_str,
        }

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            history = data.get("history", {})

            if not history or "day" not in history:
                logger.warning(f"No historical data found for {symbol}")
                return pd.DataFrame()

            days = history["day"]
            if not isinstance(days, list):
                days = [days]

            rows = []
            for day in days:
                rows.append(
                    {
                        "timestamp": datetime.strptime(
                            day["date"], "%Y-%m-%d"
                        ).replace(tzinfo=timezone.utc),
                        "open": float(day["open"]),
                        "high": float(day["high"]),
                        "low": float(day["low"]),
                        "close": float(day["close"]),
                        "volume": int(day.get("volume", 0)),
                    }
                )

            if not rows:
                return pd.DataFrame()

            df = pd.DataFrame(rows)
            df.set_index("timestamp", inplace=True)
            return df

        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            return pd.DataFrame()

    def get_options_chain(
        self,
        underlying_symbol: str,
        expiration_date: Optional[str] = None,
    ) -> List[Dict]:
        """
        Get options chain for an underlying symbol.

        Args:
            underlying_symbol: Underlying ticker (e.g., 'AAPL', 'QQQ')
            expiration_date: Expiration date in YYYY-MM-DD format (optional)

        Returns:
            List of option contracts with strike, expiration, type, bid, ask, etc.
        """
        url = f"{self.base_url}/v1/markets/options/chains"
        params = {
            "symbol": underlying_symbol,
            "greeks": "true",  # Include Greeks
        }

        if expiration_date:
            params["expiration"] = expiration_date

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            options_data = data.get("options", {})

            if not options_data or "option" not in options_data:
                logger.warning(
                    f"No options chain found for {underlying_symbol}"
                )
                return []

            options_list = options_data["option"]
            if not isinstance(options_list, list):
                options_list = [options_list]

            options = []
            for opt in options_list:
                # Parse symbol to extract strike and type
                symbol = opt.get("symbol", "")
                description = opt.get("description", "")

                options.append(
                    {
                        "symbol": symbol,
                        "description": description,
                        "strike": float(opt.get("strike", 0)),
                        "expiration": opt.get("expiration_date"),
                        "option_type": opt.get("option_type"),  # 'call' or 'put'
                        "bid": float(opt.get("bid", 0)),
                        "ask": float(opt.get("ask", 0)),
                        "last": float(opt.get("last", 0)),
                        "volume": int(opt.get("volume", 0)),
                        "open_interest": int(opt.get("open_interest", 0)),
                        "greeks": {
                            "delta": float(opt.get("delta", 0)),
                            "gamma": float(opt.get("gamma", 0)),
                            "theta": float(opt.get("theta", 0)),
                            "vega": float(opt.get("vega", 0)),
                            "rho": float(opt.get("rho", 0)),
                        },
                    }
                )

            return options

        except Exception as e:
            logger.error(
                f"Error fetching options chain for {underlying_symbol}: {e}"
            )
            return []

    def get_quote(self, symbol: str) -> Optional[Dict]:
        """
        Get real-time quote for a symbol.

        Args:
            symbol: Ticker symbol

        Returns:
            Dict with bid, ask, last, volume, etc.
        """
        url = f"{self.base_url}/v1/markets/quotes"
        params = {"symbols": symbol, "greeks": "false"}

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            quotes = data.get("quotes", {})

            if not quotes or "quote" not in quotes:
                return None

            quote = quotes["quote"]
            if isinstance(quote, list):
                quote = quote[0]

            return {
                "symbol": quote.get("symbol"),
                "bid": float(quote.get("bid", 0)),
                "ask": float(quote.get("ask", 0)),
                "last": float(quote.get("last", 0)),
                "volume": int(quote.get("volume", 0)),
                "high": float(quote.get("high", 0)),
                "low": float(quote.get("low", 0)),
                "open": float(quote.get("open", 0)),
                "close": float(quote.get("close", 0)),
                "timestamp": datetime.now(timezone.utc),
            }

        except Exception as e:
            logger.error(f"Error fetching quote for {symbol}: {e}")
            return None

    def get_expirations(self, underlying_symbol: str) -> List[str]:
        """
        Get available expiration dates for an underlying symbol.

        Args:
            underlying_symbol: Underlying ticker

        Returns:
            List of expiration dates in YYYY-MM-DD format
        """
        url = f"{self.base_url}/v1/markets/options/expirations"
        params = {"symbol": underlying_symbol}

        try:
            response = self.session.get(url, params=params)
            response.raise_for_status()

            data = response.json()
            expirations = data.get("expirations", {})

            if not expirations or "date" not in expirations:
                return []

            dates = expirations["date"]
            if not isinstance(dates, list):
                dates = [dates]

            return dates

        except Exception as e:
            logger.error(
                f"Error fetching expirations for {underlying_symbol}: {e}"
            )
            return []


