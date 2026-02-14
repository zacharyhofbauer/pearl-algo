"""
State Builder - Builds the state dictionary for the Market Agent Service.

Extracted from MarketAgentService._save_state() to reduce service.py size.
The StateBuilder reads service attributes and assembles the state dict that
gets persisted to state.json each cycle.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

import pandas as pd

from pearlalgo.utils.logger import logger
from pearlalgo.utils.market_hours import get_market_hours
from pearlalgo.utils.state_io import atomic_write_json
from pearlalgo.utils.volume_pressure import (
    compute_volume_pressure_summary,
    format_volume_pressure,
    timeframe_to_minutes,
)

if TYPE_CHECKING:
    from pearlalgo.market_agent.service import MarketAgentService


class StateBuilder:
    """Builds the state dictionary from MarketAgentService attributes.

    Receives the service instance in its constructor and reads its attributes
    to assemble the state dict that is persisted to state.json.
    """

    def __init__(self, service: "MarketAgentService") -> None:
        self.service = service

    def _get_connection_status(self) -> str:
        """Determine gateway connection status."""
        try:
            dp = self.service.data_fetcher.data_provider
            if hasattr(dp, '_executor') and hasattr(dp._executor, 'is_connected'):
                if dp._executor.is_connected():
                    return "connected"
                # Executor says disconnected, but if we have fresh data it's a stale check
                if self.service.data_fetcher.get_buffer_size() > 0 and self.service.connection_failures == 0:
                    return "connected"
                return "disconnected"
        except Exception:
            pass
        # Fallback: infer from data flow
        if self.service.data_fetcher.get_buffer_size() > 0 and self.service.connection_failures == 0:
            return "connected"
        return "unknown"

    def build_state(self) -> Dict[str, Any]:
        """Build and return the complete state dictionary.

        This contains the logic formerly in MarketAgentService._save_state(),
        minus the final self.state_manager.save_state(state) call.
        """
        # Include lightweight data freshness metadata for Telegram UI / operators.
        latest_bar_timestamp = None
        latest_bar_age_minutes = None
        data_fresh = None
        latest_bar = None
        
        # Get market status for market-aware freshness check
        futures_market_open: Optional[bool] = None
        try:
            futures_market_open = bool(get_market_hours().is_market_open())
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
        
        try:
            last_market_data = getattr(self.service.data_fetcher, "_last_market_data", None) or {}
            # Use market-aware freshness check to avoid false "stale" warnings when market is closed
            freshness = self.service.data_quality_checker.check_data_freshness(
                last_market_data.get("latest_bar"),
                last_market_data.get("df"),
                market_open=futures_market_open,
            )
            ts = freshness.get("timestamp")
            if ts:
                latest_bar_timestamp = ts.isoformat()
                latest_bar_age_minutes = float(freshness.get("age_minutes", 0.0))
                data_fresh = bool(freshness.get("is_fresh", False))
            # Persist latest_bar for Telegram command UI (order book transparency)
            raw_bar = last_market_data.get("latest_bar")
            if raw_bar and isinstance(raw_bar, dict):
                # Ensure JSON-serializable (timestamps as ISO strings)
                latest_bar = {}
                for k, v in raw_bar.items():
                    if hasattr(v, "isoformat"):
                        latest_bar[k] = v.isoformat()
                    elif hasattr(v, "item"):  # numpy scalar
                        latest_bar[k] = v.item()
                    else:
                        latest_bar[k] = v
        except Exception as e:
            # Never let status persistence fail due to optional metadata.
            logger.warning(f"Failed to merge optional metadata into state: {e}")

        # Get run_id for log correlation (if set by logging_config)
        run_id = None
        try:
            from pearlalgo.utils.logging_config import get_run_id
            run_id = get_run_id()
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

        # Get version for operational visibility
        version = None
        try:
            from importlib.metadata import version as get_version
            version = get_version("pearlalgo")
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            version = "0.2.3"  # Fallback to known version

        # Market + trading bot identity for multi-market observability (Telegram/UI/ops)
        market_label = None
        try:
            market_label = str(os.getenv("PEARLALGO_MARKET") or "NQ").strip().upper()
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
            market_label = "NQ"

        state = {
            # Core service state
            "market": market_label,
            "running": self.service.running,
            "paused": self.service.paused,
            "pause_reason": self.service.pause_reason,
            "start_time": self.service.start_time.isoformat() if self.service.start_time else None,
            # Counters (lifetime)
            "cycle_count": self.service.cycle_count,
            "signal_count": self.service.signal_count,
            "signals_sent": self.service.signals_sent,
            "signals_send_failures": self.service.signals_send_failures,
            "last_signal_send_error": self.service.last_signal_send_error,
            "last_signal_generated_at": self.service.last_signal_generated_at,
            "last_signal_sent_at": self.service.last_signal_sent_at,
            "last_signal_id_prefix": self.service.last_signal_id_prefix,
            # Counters (session - since start)
            "cycle_count_session": (
                (self.service.cycle_count - self.service._cycle_count_at_start)
                if self.service._cycle_count_at_start is not None
                else None
            ),
            "signal_count_session": (
                (self.service.signal_count - self.service._signal_count_at_start)
                if self.service._signal_count_at_start is not None
                else None
            ),
            "signals_sent_session": (
                (self.service.signals_sent - self.service._signals_sent_at_start)
                if self.service._signals_sent_at_start is not None
                else None
            ),
            "signals_send_failures_session": (
                (self.service.signals_send_failures - self.service._signals_fail_at_start)
                if self.service._signals_fail_at_start is not None
                else None
            ),
            # Error/health counters (for watchdog + Telegram UI)
            "error_count": self.service.error_count,
            "consecutive_errors": self.service.consecutive_errors,
            "connection_failures": self.service.connection_failures,
            "connection_status": self._get_connection_status(),
            "data_fetch_errors": self.service.data_fetch_errors,
            # Data quality
            "buffer_size": self.service.data_fetcher.get_buffer_size(),
            "buffer_size_target": self.service.buffer_size_target,
            "data_fresh": data_fresh,
            "latest_bar_timestamp": latest_bar_timestamp,
            "latest_bar_age_minutes": latest_bar_age_minutes,
            "latest_bar": latest_bar,
            "last_successful_cycle": (
                self.service.last_successful_cycle.isoformat() if self.service.last_successful_cycle else None
            ),
            # Market/session status used by Telegram UI and operators.
            # - futures_market_open: CME ETH + maintenance break semantics
            # - strategy_session_open: configurable strategy window (default 18:00–16:10 ET)
            "futures_market_open": None,
            "strategy_session_open": None,
            # Config thresholds (for external tools to compare against)
            "data_stale_threshold_minutes": self.service.stale_data_threshold_minutes,
            "connection_timeout_minutes": self.service.connection_timeout_minutes,
            "config": {
                "symbol": self.service.config.symbol,
                "timeframe": self.service.config.timeframe,
                "scan_interval": self.service.config.scan_interval,
                # Session window (for Telegram UI observability)
                "session_start_time": getattr(self.service.config, "start_time", "18:00"),
                "session_end_time": getattr(self.service.config, "end_time", "16:10"),
                # Adaptive cadence config
                "adaptive_cadence_enabled": self.service._adaptive_cadence_enabled,
                "scan_interval_active": self.service._scan_interval_active,
                "scan_interval_idle": self.service._scan_interval_idle,
                "scan_interval_market_closed": self.service._scan_interval_market_closed,
                "scan_interval_paused": self.service._scan_interval_paused,
                "scan_interval_effective": self.service._effective_interval,
            },
            "config_warnings": self.service._config_warnings,
            "telegram_ui": {
                "compact_metrics_enabled": getattr(self.service, "_telegram_ui_compact_metrics_enabled", True),
                "show_progress_bars": getattr(self.service, "_telegram_ui_show_progress_bars", False),
                "show_volume_metrics": getattr(self.service, "_telegram_ui_show_volume_metrics", True),
                "compact_metric_width": getattr(self.service, "_telegram_ui_compact_metric_width", 10),
            },
            # Cadence metrics for observability
            "cadence_mode": "adaptive" if self.service._adaptive_cadence_enabled else self.service.cadence_mode,
            "cadence_metrics": (
                self.service.cadence_scheduler.get_metrics().to_dict()
                if self.service.cadence_scheduler
                else None
            ),
            # Buy/Sell pressure (volume-based proxy) for /status parity with push dashboard
            "buy_sell_pressure": None,
            "buy_sell_pressure_raw": None,
            # Market regime snapshot (computed each scan by scanner.regime_detector)
            # Used by operator UI to detect "market changed" events.
            "regime": None,
            "regime_timestamp": None,
            # Quiet reason / signal diagnostics observability (why no signals?)
            # These are set each cycle and surfaced in /status and dashboards.
            "quiet_reason": self.service._last_quiet_reason,
            "signal_diagnostics": self.service._last_signal_diagnostics,
            "signal_diagnostics_raw": self.service._last_signal_diagnostics_raw,
            # Quiet period duration: how long since last signal was generated
            # Useful for monitoring signal generation health
            "quiet_period_minutes": self.service._compute_quiet_period_minutes(),
            # Operational metadata
            "run_id": run_id,
            "version": version,
            "close_all_last_executed": self.service._last_close_all_at,
            "close_all_last_reason": self.service._last_close_all_reason,
            "close_all_last_count": self.service._last_close_all_count,
            "close_all_last_pnl": self.service._last_close_all_pnl,
            "close_all_last_price_source": self.service._last_close_all_price_source,
        }
        # Reuse futures_market_open from earlier check (avoid duplicate API call)
        state["futures_market_open"] = futures_market_open
        try:
            from pearlalgo.trading_bots.pearl_bot_auto import check_trading_session
            state["strategy_session_open"] = check_trading_session(datetime.now(timezone.utc), self.service.config)
        except Exception as e:
            logger.warning(f"Failed to determine strategy session state: {e}")
            state["strategy_session_open"] = None

        # Compute market regime from buffer data (best-effort)
        # This populates the regime field used by the web dashboard header badges
        try:
            last_market_data = getattr(self.service.data_fetcher, "_last_market_data", None) or {}
            df_for_regime = last_market_data.get("df")
            if isinstance(df_for_regime, pd.DataFrame) and not df_for_regime.empty and len(df_for_regime) >= 50:
                from pearlalgo.trading_bots.pearl_bot_auto import detect_market_regime
                regime_result = detect_market_regime(df_for_regime, lookback=50)
                state["regime"] = regime_result.regime
                state["regime_confidence"] = regime_result.confidence
                state["regime_trend_strength"] = regime_result.trend_strength
                state["regime_volatility_ratio"] = regime_result.volatility_ratio
                state["regime_recommendation"] = regime_result.recommendation
                state["regime_timestamp"] = datetime.now(timezone.utc).isoformat()
            else:
                state["regime"] = None
                state["regime_timestamp"] = None
        except Exception as e:
            logger.warning(f"Failed to parse regime state for persistence: {e}")
            state["regime"] = None
            state["regime_timestamp"] = None

        # Compute and persist buy/sell pressure from last market data (best-effort)
        try:
            last_market_data = getattr(self.service.data_fetcher, "_last_market_data", None) or {}
            df_for_pressure = last_market_data.get("df")
            if isinstance(df_for_pressure, pd.DataFrame) and not df_for_pressure.empty:
                summary = compute_volume_pressure_summary(
                    df_for_pressure,
                    lookback_bars=self.service.pressure_lookback_bars,
                    baseline_bars=self.service.pressure_baseline_bars,
                    open_col="open",
                    close_col="close",
                    volume_col="volume",
                )
                if summary is not None:
                    tf_min = timeframe_to_minutes(getattr(self.service.config, "timeframe", "") or "")
                    state["buy_sell_pressure_raw"] = summary.to_dict()
                    state["buy_sell_pressure"] = format_volume_pressure(
                        summary,
                        timeframe_minutes=tf_min,
                        data_fresh=data_fresh,
                    )
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

        # ==========================================================================
        # ATS (Automated Trading System) status - for Telegram commands
        # ==========================================================================
        # Persist execution and learning status so /arm, /positions, /policy commands
        # can read accurate state even when service is running.
        state["execution"] = (
            self.service.execution_adapter.get_status()
            if self.service.execution_adapter is not None
            else {"enabled": False, "armed": False, "mode": "disabled"}
        )
        # Tradovate live account data (balance, positions, P&L, fills)
        if self.service._tradovate_account:
            # Separate fills from the summary to keep state.json cleaner
            new_fills = self.service._tradovate_account.pop("fills", [])
            state["tradovate_account"] = self.service._tradovate_account
            # Put fills back on the cached dict so next poll overwrites cleanly
            self.service._tradovate_account["fills"] = new_fills

            # Persist fills to a dedicated file (accumulates across sessions,
            # because Tradovate's /fill/list clears at end of day).
            fills_file = self.service.state_manager.state_dir / "tradovate_fills.json"
            try:
                existing_fills: list = []
                if fills_file.exists():
                    existing_fills = json.loads(fills_file.read_text()) or []
                # Merge: add new fills not already in the file (by fill id)
                existing_ids = {f.get("id") for f in existing_fills}
                for nf in new_fills:
                    if nf.get("id") and nf["id"] not in existing_ids:
                        existing_fills.append(nf)
                        existing_ids.add(nf["id"])
                # Atomic write: temp file + rename to prevent corruption on crash
                atomic_write_json(fills_file, existing_fills, indent=None)
                state["tradovate_fills"] = existing_fills
            except Exception as e:
                logger.warning(f"Failed to merge tradovate fills into state: {e}")
                state["tradovate_fills"] = new_fills

            # Override virtual trade counts with real broker data
            state["active_trades_count"] = self.service._tradovate_account.get("position_count", 0)
            state["active_trades_unrealized_pnl"] = self.service._tradovate_account.get("open_pnl", 0.0)
        state["learning"] = (
            self.service.bandit_policy.get_status()
            if self.service.bandit_policy is not None
            else {"enabled": False, "mode": "disabled"}
        )
        state["learning_contextual"] = (
            self.service.contextual_policy.get_status()
            if self.service.contextual_policy is not None
            else {"enabled": False, "mode": "disabled"}
        )
        state["ml_filter"] = {
            "enabled": bool(getattr(self.service, "_ml_filter_enabled", False)),
            "mode": getattr(self.service, "_ml_filter_mode", "shadow"),
            "trained": bool(getattr(getattr(self.service, "_ml_signal_filter", None), "is_ready", False)),
            "require_lift_to_block": bool(getattr(self.service, "_ml_require_lift_to_block", True)),
            "blocking_allowed": bool(getattr(self.service, "_ml_blocking_allowed", False)),
            "lift": getattr(self.service, "_ml_lift_metrics", {}) or {},
            "last_eval_at": (
                self.service._ml_lift_last_eval_at.isoformat()
                if getattr(self.service, "_ml_lift_last_eval_at", None) is not None
                else None
            ),
        }

        # ==========================================================================
        # Notification queue stats (async Telegram delivery observability)
        # ==========================================================================
        state["notification_queue"] = self.service.notification_queue.get_stats()

        # ==========================================================================
        # Pearl AI Insights (shadow tracking for web app)
        # ==========================================================================
        try:
            shadow_metrics = self.service.shadow_tracker.get_metrics()
            active_suggestion = self.service.shadow_tracker.get_active_suggestion()

            # Get AI chat status
            ai_enabled = False  # AI chat removed (restructure Phase 2D)

            state["pearl_insights"] = {
                "current_suggestion": active_suggestion,
                "shadow_metrics": shadow_metrics,
                "ai_enabled": ai_enabled,
                "last_insight_time": shadow_metrics.get("active_suggestion", {}).get("timestamp") if shadow_metrics.get("active_suggestion") else None,
                "suggestions_today": shadow_metrics.get("total_suggestions", 0),
                "accuracy_7d": shadow_metrics.get("accuracy_rate", 0),
            }
        except Exception as e:
            logger.debug(f"Could not build pearl_insights: {e}")
            state["pearl_insights"] = None

        # ==========================================================================
        # Trading circuit breaker status (risk management observability)
        # ==========================================================================
        state["trading_circuit_breaker"] = (
            self.service.trading_circuit_breaker.get_status()
            if self.service.trading_circuit_breaker is not None
            else {"enabled": False}
        )

        # ==========================================================================
        # Virtual positions (signals.jsonl status="entered") for Telegram command UI
        # ==========================================================================
        # The interactive Telegram command handler reads state.json. Persisting these
        # fields here keeps /start dashboards accurate (open positions + unrealized PnL).
        #
        # For Tradovate Paper, the real broker data is authoritative and was already
        # set above (lines ~6121-6122). Skip virtual override when Tradovate data exists.
        _tradovate_authoritative = bool(self.service._tradovate_account and self.service._tradovate_account.get("position_count") is not None)

        if not _tradovate_authoritative:
            state["active_trades_count"] = 0
        try:
            # Surface latest price source (Level 1 vs historical) for UI confidence cues.
            if isinstance(latest_bar, dict):
                state["latest_price_source"] = latest_bar.get("_data_level") or latest_bar.get("_data_source")
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

        try:
            recent_signals = self.service.state_manager.get_recent_signals(limit=300)
            active: list[dict] = []
            for rec in recent_signals:
                if isinstance(rec, dict) and rec.get("status") == "entered":
                    active.append(rec)

            if not _tradovate_authoritative:
                state["active_trades_count"] = int(len(active))

            # Total unrealized PnL (USD) across active trades using freshest available price.
            # Skip for Tradovate — real open_pnl is already set from broker data.
            if not _tradovate_authoritative:
                latest_price = None
                try:
                    if isinstance(latest_bar, dict):
                        latest_price = latest_bar.get("close")
                except Exception as e:
                    logger.warning(f"Failed to get latest bar for PnL computation: {e}")
                    latest_price = None

                if latest_price is not None and len(active) > 0:
                    try:
                        current_price = float(latest_price)
                    except Exception as e:
                        logger.warning(f"Failed to parse current price for PnL computation: {e}")
                        current_price = None

                    if current_price and current_price > 0:
                        total_upnl = 0.0
                        for rec in active:
                            sig = rec.get("signal", {}) or {}
                            # Direction & entry_price live at top-level on the record;
                            # fall back to the nested signal dict for older formats.
                            direction = str(
                                sig.get("direction") or rec.get("direction") or "long"
                            ).lower()
                            try:
                                entry_price = float(
                                    rec.get("entry_price") or sig.get("entry_price") or 0.0
                                )
                            except Exception as e:
                                logger.warning(f"Failed to parse entry price for PnL computation: {e}")
                                entry_price = 0.0
                            if entry_price <= 0:
                                continue
                            try:
                                tick_value = float(
                                    sig.get("tick_value") or rec.get("tick_value") or 2.0
                                )
                            except Exception as e:
                                logger.warning(f"Failed to parse tick value for PnL computation: {e}")
                                tick_value = 2.0
                            try:
                                position_size = float(
                                    sig.get("position_size") or rec.get("position_size") or 1.0
                                )
                            except Exception as e:
                                logger.warning(f"Failed to parse position size for PnL computation: {e}")
                                position_size = 1.0

                            pnl_pts = (current_price - entry_price) if direction == "long" else (entry_price - current_price)
                            total_upnl += float(pnl_pts) * float(tick_value) * float(position_size)

                        state["active_trades_unrealized_pnl"] = float(total_upnl)
        except Exception as e:
            # Never allow optional UI fields to break state persistence.
            logger.warning(f"Failed to compute unrealized PnL for state: {e}")

        return state
