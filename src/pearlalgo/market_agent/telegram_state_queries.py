"""
Telegram State Query Utilities for Market Agent.

This module provides mixin methods for reading and querying system state.
These are extracted from TelegramCommandHandler to improve modularity.

Architecture Note:
------------------
This is a mixin class designed to be composed with TelegramCommandHandler.
It provides state reading and metrics computation while keeping the main
handler class focused on routing and orchestration.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Any

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_state_file, get_signals_file, parse_utc_timestamp

if TYPE_CHECKING:
    pass


class TelegramStateQueriesMixin:
    """
    Mixin providing state query utilities for Telegram bot.

    This mixin is designed to be used with TelegramCommandHandler and provides:
    - State file reading
    - Signal history reading
    - Metrics computation
    - Performance data loading

    Usage:
        class TelegramCommandHandler(TelegramStateQueriesMixin, ...):
            ...

    Required attributes on the composing class:
        - state_dir: Path to the state directory
        - exports_dir: Path to the exports directory
    """

    # These will be set by the composing class
    state_dir: Path
    exports_dir: Path

    def _read_state(self) -> Optional[dict]:
        """Read current state from state.json."""
        state_file = get_state_file(self.state_dir)
        if not state_file.exists():
            return None
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to read state file: {e}")
            return None

    def _read_recent_signals(self, limit: int = 10) -> list:
        """Read recent signals from signals.jsonl."""
        signals_file = get_signals_file(self.state_dir)
        if not signals_file.exists():
            return []
        try:
            signals = []
            with open(signals_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rec = json.loads(line)
                            # Normalize for UI: many handlers expect direction/type/etc at top-level,
                            # but the JSONL stores these under rec["signal"].
                            if isinstance(rec, dict):
                                sig = rec.get("signal", {})
                                if isinstance(sig, dict):
                                    for k in (
                                        "direction",
                                        "type",
                                        "symbol",
                                        "timeframe",
                                        "entry_price",
                                        "stop_loss",
                                        "take_profit",
                                        "confidence",
                                        "risk_reward",
                                        "reason",
                                    ):
                                        if rec.get(k) is None and sig.get(k) is not None:
                                            rec[k] = sig.get(k)
                            signals.append(rec)
                        except json.JSONDecodeError:
                            continue
            # Return most recent signals first
            return signals[-limit:] if len(signals) > limit else signals
        except Exception as e:
            logger.warning(f"Failed to read signals file: {e}")
            return []

    def _read_latest_metrics(self) -> Optional[dict]:
        """Read latest performance metrics from exports directory."""
        if not self.exports_dir.exists():
            return None
        metrics_files = sorted(
            self.exports_dir.glob("performance_*_metrics.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not metrics_files:
            return None
        try:
            return json.loads(metrics_files[0].read_text(encoding="utf-8"))
        except Exception:
            return None

    def _read_strategy_selection(self) -> Optional[dict]:
        """Read latest strategy selection from exports directory."""
        if not self.exports_dir.exists():
            return None
        candidates = list(self.exports_dir.glob("strategy_selection_*.json"))
        if not candidates:
            latest = self.exports_dir / "strategy_selection_latest.json"
            candidates = [latest] if latest.exists() else []
        if not candidates:
            return None
        candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        try:
            return json.loads(candidates[0].read_text(encoding="utf-8"))
        except Exception:
            return None

    def _load_latest_incident_report(self) -> Optional[dict]:
        """Load the latest incident report from exports directory."""
        try:
            exports_dir = self.state_dir / "exports"
            if not exports_dir.exists():
                return None
            files = sorted(
                exports_dir.glob("incident_report_*.json"),
                key=lambda p: p.stat().st_mtime,
            )
            if not files:
                return None
            return json.loads(files[-1].read_text(encoding="utf-8"))
        except Exception:
            return None

    def _find_signal_by_prefix(self, signal_id_prefix: str) -> Optional[dict]:
        """Find a signal by its ID prefix in recent signals."""
        signals = self._read_recent_signals(limit=100)
        if not signals:
            return None

        # Search for matching signal
        for signal in reversed(signals):  # Most recent first
            sig_id = str(signal.get("signal_id", ""))
            if sig_id.startswith(signal_id_prefix):
                return signal

        return None

    def _extract_latest_price(self, state: dict) -> Optional[float]:
        """Extract latest price from state, trying multiple sources."""
        try:
            # Try direct latest_price first
            price = state.get("latest_price")
            if price is not None:
                return float(price)

            # Try latest_bar.close
            latest_bar = state.get("latest_bar")
            if isinstance(latest_bar, dict):
                close = latest_bar.get("close")
                if close is not None:
                    return float(close)

            return None
        except (ValueError, TypeError):
            return None

    def _extract_data_age_minutes(self, state: dict) -> Optional[float]:
        """
        Extract data age in minutes from state.

        Returns the age of the latest bar in minutes, or None if unavailable.
        """
        try:
            latest_bar = state.get("latest_bar")
            if not isinstance(latest_bar, dict):
                return None

            ts = latest_bar.get("timestamp") or state.get("latest_bar_timestamp")
            if not ts:
                return None

            dt = parse_utc_timestamp(str(ts))
            if dt and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt:
                return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0

            return None
        except Exception:
            return None

    def _compute_state_stale_threshold(self, state: dict) -> float:
        """Get the data stale threshold in minutes from state."""
        try:
            return float(state.get("data_stale_threshold_minutes", 10.0) or 10.0)
        except (ValueError, TypeError):
            return 10.0

    def _is_agent_process_running(self) -> bool:
        """
        Check if the agent process is actually running.

        This performs a live process check rather than relying on state file.
        """
        try:
            sc = getattr(self, "service_controller", None)
            if sc is None:
                return False
            # Use active_market if available, otherwise default to "NQ"
            market = getattr(self, "active_market", "NQ")
            status = sc.get_agent_status(market=market) or {}
            return bool(status.get("running"))
        except Exception:
            return False

    def _get_current_time_str(self) -> str:
        """Get current time as formatted string."""
        now = datetime.now(timezone.utc)
        try:
            import pytz
            et_tz = pytz.timezone('US/Eastern')
            et_time = now.astimezone(et_tz)
            return et_time.strftime("%I:%M %p ET").lstrip('0')
        except Exception:
            return now.strftime("%H:%M UTC")

    def _count_open_positions(self, state: Optional[dict] = None) -> int:
        """
        Count total open positions from state.

        Counts both execution positions and active virtual trades.
        """
        if state is None:
            state = self._read_state()
        if not state:
            return 0

        positions = (state.get("execution", {}).get("positions", 0) or 0)
        active_trades = state.get("active_trades_count", 0) or 0
        return positions + active_trades

    def _get_daily_performance(self, state: Optional[dict] = None) -> dict:
        """
        Get daily performance metrics from state.

        Returns:
            Dict with keys: daily_pnl, daily_trades, daily_wins, daily_losses, win_rate
        """
        if state is None:
            state = self._read_state()
        if not state:
            return {
                "daily_pnl": 0.0,
                "daily_trades": 0,
                "daily_wins": 0,
                "daily_losses": 0,
                "win_rate": 0.0,
            }

        daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
        daily_trades = state.get("daily_trades", 0) or 0
        daily_wins = state.get("daily_wins", 0) or 0
        daily_losses = state.get("daily_losses", 0) or 0
        win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0.0

        return {
            "daily_pnl": daily_pnl,
            "daily_trades": daily_trades,
            "daily_wins": daily_wins,
            "daily_losses": daily_losses,
            "win_rate": win_rate,
        }

    def _get_gateway_status(self) -> dict:
        """
        Get gateway status from service controller.

        Returns:
            Dict with keys: process_running, port_listening, is_healthy
        """
        try:
            sc = getattr(self, "service_controller", None)
            if sc is None:
                return {"process_running": False, "port_listening": False, "is_healthy": False}

            gw_status = sc.get_gateway_status() or {}
            process_running = bool(gw_status.get("process_running", False))
            port_listening = bool(gw_status.get("port_listening", False))

            return {
                "process_running": process_running,
                "port_listening": port_listening,
                "is_healthy": process_running and port_listening,
            }
        except Exception:
            return {"process_running": False, "port_listening": False, "is_healthy": False}

    def _get_agent_health(self, state: Optional[dict] = None) -> dict:
        """
        Get agent health status.

        Returns:
            Dict with keys: running, paused, healthy, cycle_age_seconds
        """
        if state is None:
            state = self._read_state()
        if not state:
            return {
                "running": False,
                "paused": False,
                "healthy": None,
                "cycle_age_seconds": None,
            }

        running = self._is_agent_process_running()
        paused = bool(state.get("paused", False))

        # Check cycle health
        cycle_age_sec = None
        healthy = None

        try:
            ts = state.get("last_successful_cycle")
            if ts:
                dt = parse_utc_timestamp(str(ts))
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt:
                    cycle_age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
        except Exception:
            cycle_age_sec = None

        # Determine cycle threshold
        cycle_thr = 120.0
        try:
            cm = state.get("cadence_metrics") or {}
            interval = cm.get("current_interval_seconds")
            if interval:
                cycle_thr = max(120.0, float(interval) * 4.0)
        except Exception:
            cycle_thr = 120.0

        if running and cycle_age_sec is not None:
            healthy = float(cycle_age_sec) <= float(cycle_thr)

        return {
            "running": running,
            "paused": paused,
            "healthy": healthy,
            "cycle_age_seconds": cycle_age_sec,
        }

    def _get_connection_status(self, state: Optional[dict] = None) -> dict:
        """
        Get connection status from state.

        Returns:
            Dict with keys: status, is_connected, is_stale
        """
        if state is None:
            state = self._read_state()
        if not state:
            return {"status": "unknown", "is_connected": None, "is_stale": None}

        # Check explicit connection status first
        if "connection_status" in state:
            cs = state.get("connection_status")
            if cs == "connected":
                return {"status": "connected", "is_connected": True, "is_stale": False}
            elif cs == "disconnected":
                return {"status": "disconnected", "is_connected": False, "is_stale": None}
            else:
                return {"status": str(cs), "is_connected": None, "is_stale": None}

        # Fall back to data freshness
        data_fresh = state.get("data_fresh")
        if data_fresh is not None:
            return {
                "status": "connected" if data_fresh else "stale",
                "is_connected": bool(data_fresh),
                "is_stale": not bool(data_fresh),
            }

        return {"status": "unknown", "is_connected": None, "is_stale": None}

    def _load_performance_trades(self) -> list:
        """
        Load all trades from performance.json.

        Returns:
            List of trade records, deduplicated by signal_id
        """
        try:
            perf_file = self.state_dir / "performance.json"
            if not perf_file.exists():
                return []

            with open(perf_file, 'r', encoding='utf-8') as f:
                all_trades = json.load(f)

            if not isinstance(all_trades, list):
                return []

            # De-dupe by signal_id
            by_id: dict[str, dict] = {}
            no_id: list[dict] = []

            for t in all_trades:
                if not isinstance(t, dict):
                    continue
                sid = str(t.get("signal_id") or "").strip()
                if not sid:
                    no_id.append(t)
                    continue
                by_id[sid] = t  # Keep most recent occurrence

            return list(by_id.values()) + no_id

        except Exception as e:
            logger.debug(f"Could not load performance trades: {e}")
            return []

    def _get_trading_day_start(self) -> datetime:
        """
        Get the start of the current trading day (6pm ET).

        Futures trading day runs from 6pm ET to 6pm ET next day.
        Returns datetime in UTC for comparison with trade timestamps.
        """
        from datetime import timedelta
        from zoneinfo import ZoneInfo

        et_tz = ZoneInfo("America/New_York")
        now_et = datetime.now(et_tz)

        if now_et.hour < 18:
            # Before 6pm ET - trading day started yesterday at 6pm
            trading_day_start = now_et.replace(
                hour=18, minute=0, second=0, microsecond=0
            ) - timedelta(days=1)
        else:
            # After 6pm ET - trading day started today at 6pm
            trading_day_start = now_et.replace(
                hour=18, minute=0, second=0, microsecond=0
            )

        return trading_day_start.astimezone(timezone.utc)

    def _get_today_trades(self) -> list:
        """
        Get trades from the current trading day (since 6pm ET).

        Returns:
            List of trade records from today's trading session
        """
        all_trades = self._load_performance_trades()
        if not all_trades:
            return []

        trading_day_start = self._get_trading_day_start()
        today_trades = []

        for t in all_trades:
            exit_time_str = t.get('exit_time', '')
            if exit_time_str:
                try:
                    exit_time = datetime.fromisoformat(
                        str(exit_time_str).replace("Z", "+00:00")
                    )
                    if exit_time >= trading_day_start:
                        today_trades.append(t)
                except (ValueError, TypeError):
                    pass

        return today_trades
