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

    def _connect(self) -> IB:
        """
        Connect to IBKR Gateway with proper event loop handling.
        
        Fixes event loop conflicts by running connection in a thread when called from async context.
        """
        import asyncio
        import threading
        from queue import Queue
        
        ib = IB()
        
        # Check if we're in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context - need to run connection in a separate thread
            result_queue = Queue()
            error_queue = Queue()
            
            def connect_in_thread():
                """Connect in a new thread with its own event loop."""
                try:
                    # Create new event loop for this thread
                    new_loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(new_loop)
                    
                    # Connect (ib.connect is synchronous but uses asyncio internally)
                    ib.connect(
                        self.connection.host,
                        self.connection.port,
                        clientId=self.connection.client_id,
                        timeout=5,  # Longer timeout for thread-based connection
                    )
                    result_queue.put(ib)
                except Exception as e:
                    error_queue.put(e)
                finally:
                    try:
                        new_loop.close()
                    except:
                        pass
            
            # Run in daemon thread
            thread = threading.Thread(target=connect_in_thread, daemon=True)
            thread.start()
            thread.join(timeout=10)  # Wait up to 10 seconds
            
            if not error_queue.empty():
                exc = error_queue.get()
                raise exc
            if not result_queue.empty():
                ib = result_queue.get()
                logger.info(f"IBKR connected successfully (clientId={self.connection.client_id})")
                return ib
            else:
                raise TimeoutError("IBKR connection timed out")
                
        except RuntimeError:
            # No running event loop - can connect directly
            try:
                ib.connect(
                    self.connection.host,
                    self.connection.port,
                    clientId=self.connection.client_id,
                    timeout=5,
                )
                logger.info(f"IBKR connected successfully (clientId={self.connection.client_id})")
            except (ConnectionRefusedError, OSError) as exc:
                logger.error(
                    f"IBKR connection refused at {self.connection.host}:{self.connection.port} "
                    f"(clientId={self.connection.client_id}). Is IB Gateway running?"
                )
                raise RuntimeError(
                    f"IBKR Gateway not available at {self.connection.host}:{self.connection.port}. "
                    f"Please start IB Gateway and ensure API is enabled. "
                    f"See IBKR_CONNECTION_FIXES.md for help. "
                    f"If testing without IBKR, set PEARLALGO_DUMMY_MODE=true in .env"
                ) from exc
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
                elif "event loop" in error_msg or "already running" in error_msg:
                    logger.error(f"IBKR event loop conflict: {exc}")
                    raise RuntimeError(
                        f"IBKR event loop conflict. This should not happen in sync context. Error: {exc}"
                    ) from exc
                else:
                    logger.error(f"IBKR connection error: {exc}")
                    raise RuntimeError(
                        f"Failed to connect to IB at {self.connection.host}:{self.connection.port} "
                        f"(clientId={self.connection.client_id}). Error: {exc}"
                    ) from exc
        
        return ib

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
