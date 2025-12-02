from __future__ import annotations

from datetime import datetime
from typing import Iterable, Optional

import pandas as pd
from ib_insync import IB, Stock, Future

from pearlalgo.data_providers.base import DataProvider
from pearlalgo.config.settings import Settings


class IBDataProvider(DataProvider):
    """
    Thin ib_insync wrapper for pulling historical bars from IBKR Gateway/TWS.

    This is read-only for research/backtesting. It does NOT place orders.
    """

    def __init__(
        self,
        settings: Settings,
        host: Optional[str] = None,
        port: Optional[int] = None,
        client_id: Optional[int] = None,
    ):
        self.settings = settings
        self.host = host or settings.ib_host
        self.port = port or settings.ib_port
        self.client_id = client_id or settings.ib_client_id

    def _contract(
        self, symbol: str, sec_type: str = "FUT", exchange: str | None = None
    ):
        exch = exchange or ("GLOBEX" if sec_type == "FUT" else "SMART")
        if sec_type.upper() == "FUT":
            return Future(symbol=symbol, exchange=exch, currency="USD")
        return Stock(symbol=symbol, exchange=exch, currency="USD")

    def fetch_historical(
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: str | None = None,
        *,
        duration: str = "2 D",
        bar_size: str = "15 mins",
        what_to_show: str = "TRADES",
        sec_type: str = "FUT",
        exchange: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Pull historical bars from IBKR. Duration and bar_size follow IB formats.
        """
        ib = IB()
        try:
            ib.connect(self.host, int(self.port), clientId=int(self.client_id))
        except Exception as exc:  # pragma: no cover - network/IB specific
            raise RuntimeError(
                f"IB connection failed to {self.host}:{self.port} (clientId={self.client_id}). "
                f"Ensure IB Gateway/TWS is running with API enabled. Error: {exc}"
            ) from exc
        contract = self._contract(symbol, sec_type=sec_type, exchange=exchange)
        bars = ib.reqHistoricalData(
            contract,
            endDateTime=end or "",
            durationStr=duration,
            barSizeSetting=bar_size,
            whatToShow=what_to_show,
            useRTH=False,
            formatDate=1,
        )
        ib.disconnect()
        if not bars:
            raise RuntimeError(f"No data returned from IB for {symbol}")
        df = pd.DataFrame(bars)
        df = df.rename(columns=str.title)
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
        if timeframe:
            from pearlalgo.data.pipelines import resample_ohlcv

            df = resample_ohlcv(df, timeframe)
        return df

    def stream_live(self, symbols: list[str]) -> Iterable[pd.DataFrame]:
        raise NotImplementedError("Live streaming is not implemented in this provider")
