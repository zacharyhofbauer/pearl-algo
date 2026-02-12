"""
Service Notification Methods

Extracted from service.py to improve maintainability.
Contains dashboard, chart generation, and notification-related functionality.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.market_agent.live_chart_screenshot import capture_live_chart_screenshot
from pearlalgo.market_agent.notification_queue import Priority
from pearlalgo.utils.volume_pressure import (
    compute_volume_pressure_summary,
    format_volume_pressure,
    timeframe_to_minutes,
)

if TYPE_CHECKING:
    from pearlalgo.market_agent.service import MarketAgentService


class ServiceNotificationsMixin:
    """
    Mixin class containing notification-related methods for MarketAgentService.

    This mixin provides:
    - Dashboard sending and scheduling
    - Chart generation
    - Recent closes and MTF trend computation
    - Trade chart overlay data
    """

    async def _check_dashboard(
        self: "MarketAgentService",
        market_data: Optional[Dict] = None,
        quiet_reason: Optional[str] = None,
        signal_diagnostics=None,
    ) -> None:
        """
        Send periodic dashboard message (replaces status + heartbeat).

        Args:
            market_data: Current market data (may be empty)
            quiet_reason: Why the agent is quiet (e.g., "StrategySessionClosed")
            signal_diagnostics: SignalDiagnostics from the signal generator
        """
        # Check if interval notifications are enabled (user preference)
        try:
            from pearlalgo.utils.telegram_alerts import TelegramPrefs
            prefs = TelegramPrefs(state_dir=self.state_manager.state_dir)
            if not prefs.get("interval_notifications", True):
                return  # Notifications disabled
        except Exception as e:
            # If we can't load prefs, default to enabled
            logger.debug(f"Non-critical: {e}", exc_info=True)

        now = datetime.now(timezone.utc)

        # Check if it's time for a dashboard chart (every 60m by default)
        # Respect dashboard_chart_enabled config (can be disabled to reduce noise)
        chart_due = self.dashboard_chart_enabled and (
            self.last_dashboard_chart_sent is None
            or (now - self.last_dashboard_chart_sent).total_seconds() >= self.dashboard_chart_interval
        )

        # Check if it's time for a text dashboard update (every 15m by default)
        text_due = (
            self.last_status_update is None
            or (now - self.last_status_update).total_seconds() >= self.status_update_interval
        )

        # Canonical dashboard: one message (visual when chart is available).
        if chart_due:
            chart_path = None
            try:
                # Bound chart generation time so the service loop cannot stall indefinitely.
                chart_path = await asyncio.wait_for(self.observability_orchestrator.generate_dashboard_chart(), timeout=30.0)
            except Exception as e:
                logger.debug(f"Could not generate dashboard chart: {e}", exc_info=True)
                chart_path = None
            self.last_dashboard_chart_sent = now
            await self._send_dashboard(
                market_data,
                quiet_reason=quiet_reason,
                signal_diagnostics=signal_diagnostics,
                chart_path=chart_path,
            )
            # Clean up any temp chart file returned on export failure.
            try:
                if (
                    chart_path
                    and getattr(chart_path, "name", "") not in {"dashboard_latest.png", "dashboard_telegram_latest.png"}
                    and chart_path.exists()
                ):
                    chart_path.unlink()
            except Exception as e:
                logger.debug(f"Non-critical: {e}", exc_info=True)
            self.last_status_update = now
        elif text_due:
            # Text-only update (no chart refresh); keep layout identical.
            await self._send_dashboard(
                market_data,
                quiet_reason=quiet_reason,
                signal_diagnostics=signal_diagnostics,
                chart_path=None,
            )
            self.last_status_update = now

    async def _generate_dashboard_chart(self: "MarketAgentService") -> Optional[Path]:
        """Capture the Live Main Chart and export it for Telegram/UI use.

        Delegated to ObservabilityOrchestrator.generate_dashboard_chart().
        """
        return await self.observability_orchestrator.generate_dashboard_chart()

    async def _send_dashboard(
        self: "MarketAgentService",
        market_data: Optional[Dict] = None,
        quiet_reason: Optional[str] = None,
        signal_diagnostics=None,
        chart_path: Optional[Path] = None,
    ) -> None:
        """
        Send consolidated dashboard to Telegram.

        Args:
            market_data: Current market data (may be empty)
            quiet_reason: Why the agent is quiet (for observability)
            signal_diagnostics: SignalDiagnostics from the signal generator
            chart_path: Optional path to chart PNG for a visual dashboard message
        """
        try:
            # Get base status
            status = self.get_status()

            # Add current time
            status["current_time"] = datetime.now(timezone.utc)
            status["symbol"] = self.config.symbol

            # Add quiet reason for observability (why no signals)
            if quiet_reason:
                status["quiet_reason"] = quiet_reason

            # Add signal diagnostics when no signals (for observability)
            if signal_diagnostics is not None:
                # Handle both SignalDiagnostics object and pre-formatted string
                if hasattr(signal_diagnostics, 'format_compact'):
                    status["signal_diagnostics"] = signal_diagnostics.format_compact()
                    status["signal_diagnostics_raw"] = signal_diagnostics.to_dict() if hasattr(signal_diagnostics, 'to_dict') else {}
                else:
                    # Already a formatted string
                    status["signal_diagnostics"] = str(signal_diagnostics)
                    status["signal_diagnostics_raw"] = {}

            # Try to get latest price
            try:
                if market_data and market_data.get("latest_bar"):
                    latest_bar = market_data["latest_bar"]
                    if isinstance(latest_bar, dict) and "close" in latest_bar:
                        status["latest_price"] = latest_bar["close"]
            except Exception as e:
                logger.debug(f"Non-critical: {e}", exc_info=True)

            # Track price source for UI confidence cues (e.g., Level 1 vs historical fallback).
            try:
                if market_data and isinstance(market_data.get("latest_bar"), dict):
                    status["latest_price_source"] = market_data["latest_bar"].get("_data_level")
            except Exception as e:
                logger.debug(f"Non-critical: {e}", exc_info=True)

            # Active trades + unrealized PnL (virtual lifecycle: status="entered").
            self._add_active_trades_to_status(status, market_data)

            # Get recent closes for sparkline
            recent_closes = self._get_recent_closes(market_data)
            status["recent_closes"] = recent_closes

            # Get MTF trend arrows
            mtf_trends = self._compute_mtf_trends(market_data)
            status["mtf_trends"] = mtf_trends

            # Buy/Sell pressure (volume-based proxy) for 15m dashboard notifications
            self._add_volume_pressure_to_status(status, market_data)

            await self.notification_queue.enqueue_dashboard(status, chart_path=chart_path, priority=Priority.LOW)
        except Exception as e:
            logger.error(f"Error queuing dashboard: {e}", exc_info=True)

    def _add_active_trades_to_status(
        self: "MarketAgentService",
        status: Dict[str, Any],
        market_data: Optional[Dict],
    ) -> None:
        """Add active trades and unrealized PnL to status dict."""
        try:
            active = []
            try:
                recent_signals = self.state_manager.get_recent_signals(limit=300)
            except Exception:
                recent_signals = []
            for rec in recent_signals:
                if isinstance(rec, dict) and rec.get("status") == "entered":
                    active.append(rec)

            status["active_trades_count"] = len(active)

            # Total unrealized PnL across active trades (USD), computed using the freshest available price.
            latest_price = status.get("latest_price")
            if latest_price is not None and len(active) > 0:
                try:
                    current_price = float(latest_price)
                except Exception:
                    current_price = None
                if current_price and current_price > 0:
                    total_upnl = 0.0
                    for rec in active:
                        sig = rec.get("signal", {}) or {}
                        direction = str(sig.get("direction") or "long").lower()
                        try:
                            entry_price = float(sig.get("entry_price") or 0.0)
                        except Exception:
                            entry_price = 0.0
                        if entry_price <= 0:
                            continue
                        try:
                            tick_value = float(sig.get("tick_value") or 2.0)
                        except Exception:
                            tick_value = 2.0
                        try:
                            position_size = float(sig.get("position_size") or 1.0)
                        except Exception:
                            position_size = 1.0

                        pnl_pts = (current_price - entry_price) if direction == "long" else (entry_price - current_price)
                        total_upnl += float(pnl_pts) * float(tick_value) * float(position_size)

                    status["active_trades_unrealized_pnl"] = float(total_upnl)

            # Recent exits (compact transparency list for dashboards).
            try:
                exited = []
                for rec in recent_signals:
                    if not isinstance(rec, dict) or rec.get("status") != "exited":
                        continue
                    pnl = rec.get("pnl")
                    if pnl is None:
                        continue
                    sig = rec.get("signal", {}) or {}
                    exited.append(
                        {
                            "signal_id": str(rec.get("signal_id") or ""),
                            "type": str(sig.get("type") or "unknown"),
                            "direction": str(sig.get("direction") or "long"),
                            "pnl": pnl,
                            "exit_reason": str(rec.get("exit_reason") or ""),
                            "exit_time": rec.get("exit_time") or rec.get("timestamp") or sig.get("timestamp"),
                        }
                    )
                # Keep only the most recent few (signals.jsonl is append-only, so reverse is safe)
                exited = list(reversed(exited))[:3]
                if exited:
                    status["recent_exits"] = exited
            except Exception as e:
                logger.debug(f"Non-critical: {e}", exc_info=True)
        except Exception as e:
            # Never let optional PnL UI break dashboard delivery.
            logger.debug(f"Non-critical: {e}", exc_info=True)

    def _add_volume_pressure_to_status(
        self: "MarketAgentService",
        status: Dict[str, Any],
        market_data: Optional[Dict],
    ) -> None:
        """Add buy/sell pressure metrics to status dict."""
        try:
            df_for_pressure = None
            if market_data and "df" in market_data and market_data["df"] is not None:
                df_for_pressure = market_data["df"]
            elif getattr(self.data_fetcher, "_data_buffer", None) is not None:
                df_for_pressure = getattr(self.data_fetcher, "_data_buffer")

            if isinstance(df_for_pressure, pd.DataFrame) and not df_for_pressure.empty:
                summary = compute_volume_pressure_summary(
                    df_for_pressure,
                    lookback_bars=self.pressure_lookback_bars,
                    baseline_bars=self.pressure_baseline_bars,
                    open_col="open",
                    close_col="close",
                    volume_col="volume",
                )
                if summary is not None:
                    tf_min = timeframe_to_minutes(getattr(self.config, "timeframe", "") or "")
                    status["buy_sell_pressure_raw"] = summary.to_dict()
                    status["buy_sell_pressure"] = format_volume_pressure(
                        summary,
                        timeframe_minutes=tf_min,
                        data_fresh=status.get("data_fresh"),
                    )
        except Exception as e:
            # Never let optional observability break the dashboard.
            logger.debug(f"Non-critical: {e}", exc_info=True)

    def _get_recent_closes(self: "MarketAgentService", market_data: Optional[Dict] = None) -> list:
        """Extract recent close prices for sparkline."""
        try:
            if market_data and "df" in market_data and not market_data["df"].empty:
                df = market_data["df"]
                if "close" in df.columns:
                    # Get last 50 closes (about 4 hours of 5m data)
                    closes = df["close"].tail(50).tolist()
                    return [float(c) for c in closes if c is not None]

            # Fallback to buffer
            if self.data_fetcher._data_buffer is not None and not self.data_fetcher._data_buffer.empty:
                df = self.data_fetcher._data_buffer
                if "close" in df.columns:
                    closes = df["close"].tail(50).tolist()
                    return [float(c) for c in closes if c is not None]
        except Exception as e:
            logger.debug(f"Could not get recent closes for sparkline: {e}", exc_info=True)

        return []

    def _get_trades_for_chart(
        self: "MarketAgentService",
        chart_data: Optional[pd.DataFrame],
    ) -> list[dict]:
        """
        Build a compact list of recent **completed** trades within the chart window.

        Used to overlay trade history markers on the periodic dashboard chart.
        """
        try:
            if chart_data is None or not isinstance(chart_data, pd.DataFrame) or chart_data.empty:
                return []

            # Determine chart time window (normalize to naive UTC for stable comparisons)
            tmin = None
            tmax = None
            if "timestamp" in chart_data.columns:
                ts = pd.to_datetime(chart_data["timestamp"], errors="coerce")
                ts = ts.dropna()
                if ts.empty:
                    return []
                tmin = pd.Timestamp(ts.min())
                tmax = pd.Timestamp(ts.max())
            elif isinstance(chart_data.index, pd.DatetimeIndex) and len(chart_data.index) > 0:
                tmin = pd.Timestamp(chart_data.index.min())
                tmax = pd.Timestamp(chart_data.index.max())
            if tmin is None or tmax is None:
                return []

            def _to_utc_naive(x):
                if not x:
                    return None
                try:
                    tsx = pd.Timestamp(x)
                except Exception:
                    return None
                try:
                    if tsx.tzinfo is not None:
                        tsx = tsx.tz_convert("UTC").tz_localize(None)
                except Exception:
                    # If tz_convert fails, fall back to stripping tz
                    try:
                        tsx = tsx.tz_localize(None)
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}", exc_info=True)
                return tsx

            tmin_u = _to_utc_naive(tmin)
            tmax_u = _to_utc_naive(tmax)
            if tmin_u is None or tmax_u is None:
                return []

            # Pull recent signals (append-only), filter to entered/exited within the window.
            try:
                recent = self.state_manager.get_recent_signals(limit=500)
            except Exception:
                recent = []

            symbol_norm = str(getattr(self.config, "symbol", "MNQ") or "MNQ").upper()
            trades: list[dict] = []
            for rec in recent:
                if not isinstance(rec, dict):
                    continue
                status = str(rec.get("status") or "").lower()
                if status not in ("exited",):
                    continue
                sig = rec.get("signal", {}) or {}
                sym = str(sig.get("symbol") or symbol_norm).upper()
                if sym != symbol_norm:
                    continue

                entry_time_raw = rec.get("entry_time") or sig.get("timestamp") or rec.get("timestamp")
                entry_time = _to_utc_naive(entry_time_raw)
                if entry_time is None:
                    continue

                exit_time_raw = rec.get("exit_time") if status == "exited" else None
                exit_time = _to_utc_naive(exit_time_raw) if exit_time_raw else None

                # Include if entry or exit is inside window, or trade spans across it.
                in_window = (tmin_u <= entry_time <= tmax_u)
                if exit_time is not None:
                    in_window = in_window or (tmin_u <= exit_time <= tmax_u) or (entry_time <= tmax_u and exit_time >= tmin_u)
                if not in_window:
                    continue

                # Prices
                entry_price = rec.get("entry_price") or sig.get("entry_price")
                exit_price = rec.get("exit_price") if status == "exited" else None
                pnl = rec.get("pnl") if status == "exited" else None

                trades.append(
                    {
                        "signal_id": str(rec.get("signal_id") or ""),
                        "direction": str(sig.get("direction") or "long"),
                        "entry_time": entry_time_raw,
                        "entry_price": entry_price,
                        "exit_time": exit_time_raw,
                        "exit_price": exit_price,
                        "exit_reason": rec.get("exit_reason"),
                        "pnl": pnl,
                        "status": status,
                    }
                )

            # Keep only the most recent N to avoid chart clutter.
            trades = trades[-20:]
            return trades
        except Exception:
            return []

    def _compute_mtf_trends(self: "MarketAgentService", market_data: Optional[Dict] = None) -> dict:
        """
        Compute compact trend arrows for multiple timeframes.

        Uses df_5m and df_15m from market_data for accurate MTF trends,
        regardless of the base decision timeframe (1m/5m).

        Returns dict mapping timeframe -> slope value for trend_arrow() conversion.
        """
        trends = {}

        try:
            # 5m trend from df_5m (explicit MTF data, not base buffer)
            if market_data and "df_5m" in market_data:
                df_5m = market_data["df_5m"]
                if df_5m is not None and not df_5m.empty and "close" in df_5m.columns and len(df_5m) >= 10:
                    closes = df_5m["close"].tail(10)
                    if len(closes) >= 2:
                        slope = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        trends["5m"] = float(slope)

            # 15m trend from df_15m
            if market_data and "df_15m" in market_data:
                df_15m = market_data["df_15m"]
                if df_15m is not None and not df_15m.empty and "close" in df_15m.columns and len(df_15m) >= 5:
                    closes = df_15m["close"].tail(5)
                    if len(closes) >= 2:
                        slope = (closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0] * 100
                        trends["15m"] = float(slope)

            # Compute longer timeframes from 15m data (higher TF = fewer bars needed)
            if market_data and "df_15m" in market_data:
                df_15m = market_data["df_15m"]
                if df_15m is not None and not df_15m.empty and "close" in df_15m.columns:
                    # 1h: look at 4 bars of 15m data
                    if len(df_15m) >= 4:
                        closes_1h = df_15m["close"].tail(4)
                        if len(closes_1h) >= 2:
                            slope = (closes_1h.iloc[-1] - closes_1h.iloc[0]) / closes_1h.iloc[0] * 100
                            trends["1h"] = float(slope)

                    # 4h: look at 16 bars of 15m data
                    if len(df_15m) >= 16:
                        closes_4h = df_15m["close"].tail(16)
                        if len(closes_4h) >= 2:
                            slope = (closes_4h.iloc[-1] - closes_4h.iloc[0]) / closes_4h.iloc[0] * 100
                            trends["4h"] = float(slope)

                    # 1D: look at all available 15m data (up to 96 bars = 24h)
                    if len(df_15m) >= 20:
                        closes_1d = df_15m["close"].tail(min(96, len(df_15m)))
                        if len(closes_1d) >= 2:
                            slope = (closes_1d.iloc[-1] - closes_1d.iloc[0]) / closes_1d.iloc[0] * 100
                            trends["1D"] = float(slope)
        except Exception as e:
            logger.debug(f"Could not compute MTF trends: {e}", exc_info=True)

        return trends
