from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
from ib_insync import IB, Future

from pearlalgo.brokers.contracts import build_contract, resolve_future_contract
from pearlalgo.config.settings import Settings, get_settings
from pearlalgo.data_providers.base import DataProvider
from pearlalgo.data_providers.ibkr_connection_manager import (
    IBKRConnection,
    IBKRConnectionManager,
)

logger = logging.getLogger(__name__)


class IBKRDataProvider(DataProvider):
    """
    Thin ib_insync wrapper for historical data.
    
    **DEPRECATED**: IBKR is now optional and deprecated.
    Use Polygon/Tradier/local providers instead.
    See IBKR_DEPRECATION_NOTICE.md for migration guide.

    This provider is read-only and intended for research/backtesting.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        connection: IBKRConnection | None = None,
    ):
        self.settings = settings or get_settings()
        
        # Use settings values (which now read IBKR_* env vars)
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
        logger.info(f"IBKRDataProvider initialized: host={self.connection.host}, port={self.connection.port}, client_id={self.connection.client_id}")
        
        # Use connection manager to get singleton connection
        self._connection_manager = IBKRConnectionManager.get_instance(self.connection)

    def _connect(self) -> IB:
        """
        Get IBKR connection using connection manager.
        
        Uses singleton pattern to ensure only one connection per client ID,
        avoiding "client id already in use" errors.
        """
        try:
            ib = self._connection_manager.get_connection()
            if not ib.isConnected():
                # Connection lost, reconnect
                self._connection_manager.disconnect()
                ib = self._connection_manager.get_connection()
            return ib
        except Exception as exc:
            error_msg = str(exc).lower()
            
            if "client id" in error_msg or "already in use" in error_msg:
                logger.error(
                    f"IBKR client ID {self.connection.client_id} already in use. "
                    f"Try using a different client ID or close existing connections."
                )
                raise RuntimeError(
                    f"IBKR client ID {self.connection.client_id} already in use. "
                    f"Please use a different client ID or close existing connections. "
                    f"See IBKR_CONNECTION_FIXES.md for help."
                ) from exc
            else:
                logger.error(f"IBKR connection error: {exc}")
                raise RuntimeError(
                    f"Failed to connect to IB at {self.connection.host}:{self.connection.port} "
                    f"(clientId={self.connection.client_id}). Error: {exc}"
                ) from exc

    def _resolve_front_future(
        self, ib: IB, symbol: str, exchange: str | None = None
    ) -> Future:
        """
        Resolve the nearest-dated future for a symbol. Falls back to simple Future if lookup fails.
        Uses symbol-specific exchange mapping for micro contracts.
        """
        from pearlalgo.brokers.contracts import _default_exchange_for_symbol

        exch = exchange or _default_exchange_for_symbol(symbol)
        contract = resolve_future_contract(ib, symbol, exchange=exch)
        if contract:
            return contract
        logger.warning(
            "No valid front-month contract for %s on %s; falling back to simple Future",
            symbol,
            exch,
        )
        return Future(symbol=symbol, exchange=exch, currency="USD")

    def _resolve_specific_future(
        self,
        ib: IB,
        symbol: str,
        *,
        exchange: str | None = None,
        expiry: str | None = None,
        local_symbol: str | None = None,
        trading_class: str | None = None,
    ) -> Future | None:
        """
        Use contract details to pick a dated future matching expiry/local symbol/trading class.
        Tries explicit futures (CME/GLOBEX) then continuous; warns and returns None if no match.
        """
        contract = resolve_future_contract(
            ib,
            symbol,
            exchange=exchange,
            target_expiry=expiry,
            local_symbol=local_symbol,
            trading_class=trading_class,
        )
        if not contract:
            logger.warning(
                "No matching contract for %s expiry=%s local=%s tc=%s on %s",
                symbol,
                expiry,
                local_symbol,
                trading_class,
                exchange or "GLOBEX/CME",
            )
        return contract

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
            stype = sec_type.upper()
            if stype.startswith("FUT") and (expiry or local_symbol):
                contract = self._resolve_specific_future(
                    ib,
                    symbol,
                    exchange=exchange,
                    expiry=expiry,
                    local_symbol=local_symbol,
                    trading_class=trading_class or symbol,
                )
                if contract is None:
                    raise RuntimeError(
                        f"Could not resolve future for {symbol} (expiry={expiry}, local={local_symbol}, tc={trading_class})"
                    )
            elif stype.startswith("FUT"):
                # Use discovered front-month contract to avoid sec-def errors.
                contract = self._resolve_front_future(ib, symbol, exchange)
            else:
                contract = build_contract(symbol, sec_type=sec_type, exchange=exchange)
            # Qualify to ensure conId is resolved (important for futures/continuous).
            if not getattr(contract, "conId", 0):
                qualified = ib.qualifyContracts(contract)
                if qualified:
                    contract = qualified[0]
            
            # reqHistoricalData - handle async context by running in thread
            # The connection is already in a thread with its own event loop
            # When called from async context, we need to run in a thread to avoid event loop conflicts
            import asyncio
            import threading
            from queue import Queue
            
            try:
                # Check if we're in async context
                asyncio.get_running_loop()
                # In async context - run in thread to avoid event loop conflicts
                result_queue = Queue()
                error_queue = Queue()
                
                def fetch_in_thread():
                    try:
                        bars = ib.reqHistoricalData(
                            contract,
                            endDateTime=end or "",
                            durationStr=duration,
                            barSizeSetting=bar_size,
                            whatToShow=what_to_show,
                            useRTH=use_rth,
                            formatDate=1,
                        )
                        result_queue.put(bars)
                    except Exception as e:
                        error_queue.put(e)
                
                thread = threading.Thread(target=fetch_in_thread, daemon=True)
                thread.start()
                thread.join(timeout=30)  # Wait up to 30 seconds
                
                if not error_queue.empty():
                    raise error_queue.get()
                if not result_queue.empty():
                    bars = result_queue.get()
                else:
                    raise TimeoutError("Historical data request timed out")
            except RuntimeError:
                # No running loop - use sync method directly
                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime=end or "",
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow=what_to_show,
                    useRTH=use_rth,
                    formatDate=1,
                )
        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            raise
        # Don't disconnect - keep connection alive for reuse
        # The connection manager will handle cleanup when needed

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
