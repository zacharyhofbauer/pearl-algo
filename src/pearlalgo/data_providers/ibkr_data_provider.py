from __future__ import annotations

import calendar
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd
from ib_insync import IB, ContFuture, Future

from pearlalgo.brokers.contracts import build_contract
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.data_providers.base import DataProvider


@dataclass
class IBKRConnection:
    host: str
    port: int
    client_id: int


logger = logging.getLogger(__name__)


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
        data_client_id = (
            int(self.settings.ib_data_client_id)
            if self.settings.ib_data_client_id is not None
            else int(self.settings.ib_client_id) + 1
        )
        self.connection = connection or IBKRConnection(
            host=self.settings.ib_host,
            port=int(self.settings.ib_port),
            client_id=data_client_id,
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

    @staticmethod
    def _parse_ib_expiry(expiry: str) -> datetime | None:
        clean = expiry.replace("-", "")
        if len(clean) == 6:
            try:
                year, month = int(clean[:4]), int(clean[4:6])
                last_day = calendar.monthrange(year, month)[1]
                return datetime(year, month, last_day, tzinfo=timezone.utc)
            except ValueError:
                return None
        for fmt in ("%Y%m%d",):
            try:
                return datetime.strptime(clean, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def _resolve_front_future(self, ib: IB, symbol: str, exchange: str | None = None) -> Future:
        """
        Resolve the nearest-dated future for a symbol. Falls back to simple Future if lookup fails.
        """
        exch = exchange or "GLOBEX"
        candidates: list[tuple[datetime, Future]] = []
        now = datetime.now(timezone.utc)

        try:
            details = ib.reqContractDetails(ContFuture(symbol=symbol, exchange=exch))
            if not details:
                details = ib.reqContractDetails(Future(symbol=symbol, exchange=exch, currency="USD"))
        except Exception as exc:
            logger.warning("IBKR contract lookup failed for %s on %s: %s", symbol, exch, exc)
            details = []

        for det in details or []:
            expiry = det.contract.lastTradeDateOrContractMonth or ""
            expiry_dt = self._parse_ib_expiry(expiry)
            if not expiry_dt or expiry_dt <= now:
                continue
            candidates.append((expiry_dt, det.contract))

        if not candidates:
            logger.warning("No valid front-month contract for %s on %s; falling back to simple Future", symbol, exch)
            return Future(symbol=symbol, exchange=exch, currency="USD")

        candidates.sort(key=lambda item: item[0])
        front_contract = candidates[0][1]

        try:
            qualified = ib.qualifyContracts(front_contract)
            if qualified:
                front_contract = qualified[0]
        except Exception as exc:
            logger.warning("Qualification failed for %s on %s: %s", symbol, exch, exc)
        return front_contract

    def fetch_historical(  # type: ignore[override]
        self,
        symbol: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        timeframe: str | None = None,
        *,
        sec_type: str = "FUT",
        exchange: str | None = None,
        expiry: str | None = None,
        local_symbol: str | None = None,
        trading_class: str | None = None,
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
            if sec_type.upper().startswith("FUT") and (expiry or local_symbol):
                contract = build_contract(
                    symbol,
                    sec_type="FUT",
                    exchange=exchange,
                    expiry=expiry,
                    local_symbol=local_symbol,
                    trading_class=trading_class or symbol,
                )
            else:
                contract = build_contract(symbol, sec_type=sec_type, exchange=exchange)
            if sec_type.upper().startswith("FUT_CONT") and not (expiry or local_symbol):
                contract = self._resolve_front_future(ib, symbol, exchange)
            # Qualify to ensure conId is resolved (important for futures/continuous).
            if not getattr(contract, "conId", 0):
                qualified = ib.qualifyContracts(contract)
                if qualified:
                    contract = qualified[0]
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
