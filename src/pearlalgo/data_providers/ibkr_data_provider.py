from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from ib_insync import IB, Contract, Future, Stock

from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.data_providers.base import DataProvider


@dataclass
class IBKRConnection:
    host: str
    port: int
    client_id: int


def _build_contract(symbol: str, sec_type: str, exchange: str | None = None, currency: str = "USD") -> Contract:
    """
    Construct a simple stock/future contract. Futures use symbol-only (front) by default.
    """
    if sec_type.upper() == "STK":
        return Stock(symbol=symbol, exchange=exchange or "SMART", currency=currency)
    return Future(symbol=symbol, exchange=exchange or "CME", currency=currency)


class IBKRDataProvider(DataProvider):
    """
    Thin ib_insync wrapper for historical data.

    This provider is read-only and intended for research/backtesting.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        connection: IBKRConnection | None = None,
    ):
        self.settings = settings or get_settings()
        self.connection = connection or IBKRConnection(
            host=self.settings.ib_host,
            port=int(self.settings.ib_port),
            client_id=int(self.settings.ib_client_id),
        )

    def _connect(self) -> IB:
        ib = IB()
        try:
            ib.connect(self.connection.host, self.connection.port, clientId=self.connection.client_id)
        except Exception as exc:  # pragma: no cover - requires live IB
            raise RuntimeError(
                f"Failed to connect to IB at {self.connection.host}:{self.connection.port} "
                f"(clientId={self.connection.client_id}). Ensure IB Gateway is running and API is enabled. "
                f"Original error: {exc}"
            ) from exc
        return ib

    def fetch_historical(  # type: ignore[override]
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: str | None = None,
        *,
        sec_type: str = "FUT",
        exchange: str | None = None,
        duration: str = "2 D",
        bar_size: str = "5 mins",
        what_to_show: str = "TRADES",
        use_rth: bool = False,
    ) -> pd.DataFrame:
        """
        Pull historical bars and return as a DataFrame indexed by datetime.
        """
        ib = self._connect()
        try:
            contract = _build_contract(symbol, sec_type=sec_type, exchange=exchange)
            bars = ib.reqHistoricalData(
                contract,
                endDateTime=end or "",
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow=what_to_show,
                useRTH=use_rth,
                formatDate=1,
            )
        finally:
            ib.disconnect()

        if not bars:
            raise RuntimeError(f"No data returned for {symbol} ({sec_type}) from IBKR")

        df = pd.DataFrame(bars).rename(columns=str.title)
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")

        if timeframe:
            from pearlalgo.data.pipelines import resample_ohlcv

            df = resample_ohlcv(df, timeframe)
        return df

    def save_historical(
        self,
        symbol: str,
        output_path: Path,
        *,
        sec_type: str = "FUT",
        exchange: str | None = None,
        duration: str = "2 D",
        bar_size: str = "5 mins",
        what_to_show: str = "TRADES",
        use_rth: bool = False,
    ) -> Path:
        """Convenience: fetch and persist to CSV."""
        df = self.fetch_historical(
            symbol,
            sec_type=sec_type,
            exchange=exchange,
            duration=duration,
            bar_size=bar_size,
            what_to_show=what_to_show,
            use_rth=use_rth,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(output_path)
        return output_path
