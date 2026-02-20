"""
NQ Agent Performance Tracker

Tracks signal performance and calculates metrics.
"""

from __future__ import annotations

import asyncio
import fcntl
import math
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.utils.error_handler import ErrorHandler
from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_performance_file,
    get_signals_file,
    get_utc_timestamp,
    parse_utc_timestamp,
)
from pearlalgo.market_agent.state_manager import _to_json_safe
from pearlalgo.utils.state_io import (
    atomic_write_json,
    atomic_write_jsonl,
    create_minimal_signal_record,
    file_lock,
)

try:
    from pearlalgo.learning.trade_database import TradeDatabase
    SQLITE_AVAILABLE = True
except Exception:
    SQLITE_AVAILABLE = False
    TradeDatabase = None  # type: ignore

if TYPE_CHECKING:
    from pearlalgo.market_agent.state_manager import MarketAgentStateManager

# Dollars per point for Micro E-mini Nasdaq (MNQ).
DEFAULT_MNQ_TICK_VALUE: float = 2.0


def validate_trade_prices(
    entry_price: float,
    exit_price: float,
    *,
    label: str = "",
) -> tuple[bool, str]:
    """Check that trade prices are positive and finite.

    Returns:
        ``(True, "")`` when valid, or ``(False, reason)`` when invalid.
    """
    for name, value in [("entry_price", entry_price), ("exit_price", exit_price)]:
        if not math.isfinite(value):
            return False, f"{label}{name} is not finite ({value})"
        if value <= 0:
            return False, f"{label}{name} must be positive ({value})"
    return True, ""


class PerformanceTracker:
    """
    Tracks signal performance and calculates metrics.
    
    Tracks:
    - Signal generated → entry → exit (or expiry)
    - Win/loss tracking
    - Average hold time
    - Average profit/loss
    """

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        state_manager: Optional["MarketAgentStateManager"] = None,
    ):
        """
        Initialize performance tracker.
        
        Args:
            state_dir: Directory for state files (default: ./data/agent_state/<MARKET>)
            state_manager: State manager instance for signal persistence (optional)
        """
        # Track whether caller explicitly provided a state_dir (tests do this).
        # If explicit, SQLite writes MUST stay inside that directory to avoid polluting
        # the live agent DB under data/agent_state/<MARKET>.
        self._explicit_state_dir = state_dir is not None

        self.state_dir = ensure_state_dir(state_dir)

        # State manager for signal persistence (delegation)
        self.state_manager = state_manager
        self.signals_file = get_signals_file(self.state_dir)
        self.performance_file = get_performance_file(self.state_dir)

        # Load configuration early (needed for SQLite + performance settings)
        service_config = load_service_config(validate=False) or {}

        # Optional SQLite dual-write (platform memory). Keep performance.json for backward compatibility.
        self._sqlite_enabled = False
        self._trade_db = None
        self._async_sqlite_queue = None  # Set via set_sqlite_queue() if async writes enabled
        if SQLITE_AVAILABLE:
            try:
                storage_cfg = service_config.get("storage", {}) or {}
                self._sqlite_enabled = bool(storage_cfg.get("sqlite_enabled", False))
                if self._sqlite_enabled:
                    # IMPORTANT:
                    # - In production (no explicit state_dir), honor config.db_path if provided.
                    # - In tests (explicit state_dir), ALWAYS use state_dir/trades.db regardless of config.
                    if self._explicit_state_dir:
                        db_path = self.state_dir / "trades.db"
                    else:
                        db_path_raw = storage_cfg.get("db_path") or str(self.state_dir / "trades.db")
                        db_path = Path(str(db_path_raw))
                    self._trade_db = TradeDatabase(db_path)
            except Exception as e:
                logger.debug(f"SQLite storage not enabled/available: {e}")

        # Load performance configuration
        data_settings = service_config.get("data", {})
        performance_settings = service_config.get("performance", {})
        # Use data.performance_history_limit if available, fallback to performance.max_records for backward compatibility
        self._max_records = data_settings.get("performance_history_limit", performance_settings.get("max_records", 1000))
        self._default_lookback_days = performance_settings.get("default_lookback_days", 7)

        # TTL cache for get_performance_metrics() — avoids redundant full-file
        # reads when called multiple times per service cycle.
        self._METRICS_CACHE_TTL: float = 30.0  # seconds
        self._metrics_cache: Optional[Dict] = None
        self._metrics_cache_time: float = 0.0
        self._metrics_cache_days: Optional[int] = None

        # Running aggregates for all-time metrics — updated incrementally
        # on each trade exit to avoid O(n) file scans.  Initialized from a
        # one-time full scan on first get_performance_metrics() call.
        self._running_aggregates: Dict = {
            "total_pnl": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_win_pnl": 0.0,
            "total_loss_pnl": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "is_initialized": False,
        }

        logger.info(f"PerformanceTracker initialized: state_dir={self.state_dir}")

    def set_sqlite_queue(self, queue) -> None:
        """Set the async SQLite queue for non-blocking dual-write operations.

        This replaces direct private-attribute injection from the service layer,
        making the dependency explicit.

        Args:
            queue: An ``AsyncSQLiteQueue`` instance (or None to disable).
        """
        self._async_sqlite_queue = queue

    def track_signal_generated(self, signal: Dict) -> str:
        """
        Track a new signal generation.
        
        **Delegation Pattern**: This method delegates signal persistence to `StateManager.save_signal()`
        if a state_manager is provided. This ensures all signal persistence goes through a single
        interface for consistency and maintainability.
        
        **Fallback**: If no state_manager is provided, falls back to direct file write for backward
        compatibility. In normal operation, state_manager should always be provided.
        
        **Test Signals**: Signals marked with `_is_test=True` are NEVER persisted.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Signal ID for tracking (empty string for test signals)
        """
        # GUARD: Never track test signals
        if signal.get("_is_test", False):
            logger.debug(f"Skipping test signal tracking: {signal.get('type', 'unknown')}")
            return ""
        
        signal_id = f"{signal.get('type', 'unknown')}_{datetime.now(timezone.utc).timestamp()}"
        signal["signal_id"] = signal_id

        # Delegate to state_manager if available
        if self.state_manager:
            self.state_manager.save_signal(signal)
        else:
            # Fallback: direct file write (for backward compatibility)
            signal_record = {
                "signal_id": signal_id,
                "timestamp": get_utc_timestamp(),
                "status": "generated",
                "signal": _to_json_safe(signal),
            }
            try:
                with open(self.signals_file, "a") as f:
                    try:
                        payload = json.dumps(signal_record)
                    except TypeError as e:
                        logger.error(
                            f"Signal serialization failed (fallback write), writing minimal record: {e}",
                            extra={"signal_id": signal_id},
                        )
                        payload = json.dumps(create_minimal_signal_record(signal_id, signal))
                    f.write(payload + "\n")
            except Exception as e:
                logger.error(f"Error tracking signal: {e}")

        return signal_id

    def track_signal_expired(self, signal_id: str, reason: str = "expired") -> None:
        """
        Track that a signal expired without execution.
        
        Args:
            signal_id: Signal ID
            reason: Reason for expiry
        """
        self._update_signal_status(signal_id, "expired", {"reason": reason})

    def track_entry(self, signal_id: str, entry_price: float, entry_time: Optional[datetime] = None) -> None:
        """
        Track signal entry.
        
        Args:
            signal_id: Signal ID
            entry_price: Entry price
            entry_time: Entry time (default: now)
        """
        if entry_time is None:
            entry_time = datetime.now(timezone.utc)

        self._update_signal_status(
            signal_id,
            "entered",
            {
                "entry_price": entry_price,
                "entry_time": entry_time.isoformat(),
            },
        )

    def update_signal_prices(
        self,
        signal_id: str,
        *,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        updated_at: Optional[datetime] = None,
        source: str = "trade_manager",
    ) -> None:
        """
        Update stop-loss / take-profit for an existing signal record.

        This is used by in-trade management (e.g., trailing stops) so the virtual-exit
        engine (_update_virtual_trade_exits) grades exits using the *latest* stop.
        
        Safety: Uses atomic file write with locking.
        """
        if stop_loss is None and take_profit is None:
            return
        if not self.signals_file.exists():
            return
        if updated_at is None:
            updated_at = datetime.now(timezone.utc)

        # Acquire exclusive lock on the signals file during read-modify-write
        lock_path = Path(str(self.signals_file) + ".lock")
        try:
            with file_lock(lock_path):
                # Read all records
                records: List[Dict] = []
                with open(self.signals_file, "r") as f:
                    for line in f:
                        try:
                            records.append(json.loads(line.strip()))
                        except (json.JSONDecodeError, ValueError):
                            continue

                # Update matching record
                updated = False
                for record in records:
                    if record.get("signal_id") != signal_id:
                        continue
                    sig = record.get("signal", {}) or {}
                    if not isinstance(sig, dict):
                        sig = {}
                    if stop_loss is not None:
                        try:
                            sig["stop_loss"] = float(stop_loss)
                            record["stop_loss_updated_at"] = updated_at.isoformat()
                        except Exception as e:
                            ErrorHandler.log_and_continue(
                                "update_signal_prices stop_loss conversion", e,
                                level="warning", category="file_io",
                            )
                    if take_profit is not None:
                        try:
                            sig["take_profit"] = float(take_profit)
                            record["take_profit_updated_at"] = updated_at.isoformat()
                        except Exception as e:
                            ErrorHandler.log_and_continue(
                                "update_signal_prices take_profit conversion", e,
                                level="warning", category="file_io",
                            )
                    record["price_update_source"] = str(source)
                    record["signal"] = sig
                    updated = True
                    break

                if not updated:
                    return

                atomic_write_jsonl(self.signals_file, records)
        except Exception as e:
            ErrorHandler.log_and_continue(
                "update_signal_prices", e, level="warning", category="file_io",
            )

    def track_exit(
        self,
        signal_id: str,
        exit_price: float,
        exit_reason: str,
        exit_time: Optional[datetime] = None,
    ) -> Optional[Dict]:
        """
        Track signal exit and calculate P&L.
        
        Args:
            signal_id: Signal ID
            exit_price: Exit price
            exit_reason: Reason for exit (e.g., "stop_loss", "take_profit", "manual")
            exit_time: Exit time (default: now)
            
        Returns:
            Performance record dictionary
        """
        if exit_time is None:
            exit_time = datetime.now(timezone.utc)

        # Get original signal
        signal_record = self._get_signal_record(signal_id)
        if not signal_record:
            logger.warning(f"Signal {signal_id} not found for exit tracking")
            return None

        signal = signal_record.get("signal", {}) or {}
        entry_price = float(
            signal_record.get("entry_price")
            or signal.get("entry_price")
            or 0.0
        )
        direction = str(signal.get("direction", "long") or "long").lower()

        # Validate prices before computing P&L to prevent corrupt metrics.
        valid, reason = validate_trade_prices(
            entry_price, float(exit_price), label=f"signal {signal_id}: "
        )
        if not valid:
            logger.error(f"Rejecting trade exit — {reason}")
            return None

        # MNQ-native P&L:
        # pnl = points * $/point * contracts
        try:
            tick_value = float(signal.get("tick_value") or DEFAULT_MNQ_TICK_VALUE)
        except Exception as e:
            ErrorHandler.log_and_continue(
                "track_exit tick_value conversion", e, level="warning", category="serialization",
            )
            tick_value = DEFAULT_MNQ_TICK_VALUE
        try:
            position_size = float(signal.get("position_size") or 1.0)
        except Exception as e:
            ErrorHandler.log_and_continue(
                "track_exit position_size conversion", e, level="warning", category="serialization",
            )
            position_size = 1.0

        if direction == "long":
            pnl_points = float(exit_price) - float(entry_price)
        else:
            pnl_points = float(entry_price) - float(exit_price)

        pnl = pnl_points * tick_value * position_size

        is_win = pnl > 0

        # Calculate hold time
        entry_time_str = signal_record.get("entry_time")
        if entry_time_str:
            entry_time = parse_utc_timestamp(entry_time_str)
            hold_duration = (exit_time - entry_time).total_seconds() / 60  # minutes
        else:
            hold_duration = None

        performance = {
            "signal_id": signal_id,
            "signal_type": signal.get("type"),
            "direction": direction,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl": pnl,
            "is_win": is_win,
            "exit_reason": exit_reason,
            "hold_duration_minutes": hold_duration,
            "exit_time": exit_time.isoformat(),
        }

        # Update running aggregates incrementally (O(1) — no file scan).
        self._update_running_aggregates(pnl, is_win)

        # Incrementally patch the cached metrics dict (if present) instead of
        # invalidating it — avoids the O(n) full-file scan that was previously
        # triggered on every exit.  The exit just happened so it falls within
        # any active time-window.  avg_hold_minutes and total_signals refresh
        # on the next TTL-driven full scan.
        if self._metrics_cache is not None:
            c = self._metrics_cache
            c["exited_signals"] = c.get("exited_signals", 0) + 1
            c["total_pnl"] = c.get("total_pnl", 0.0) + pnl
            if is_win:
                c["wins"] = c.get("wins", 0) + 1
            else:
                c["losses"] = c.get("losses", 0) + 1
            n_exited = c.get("exited_signals", 1)
            c["win_rate"] = c["wins"] / n_exited if n_exited > 0 else 0.0
            c["avg_pnl"] = c["total_pnl"] / n_exited if n_exited > 0 else 0.0
            # Update by_signal_type breakdown
            if "by_signal_type" in c:
                sig_type = signal.get("type", "unknown")
                if sig_type not in c["by_signal_type"]:
                    c["by_signal_type"][sig_type] = {
                        "count": 0, "wins": 0, "losses": 0,
                        "total_pnl": 0.0, "win_rate": 0.0, "avg_pnl": 0.0,
                    }
                bt = c["by_signal_type"][sig_type]
                bt["count"] += 1
                bt["total_pnl"] += pnl
                if is_win:
                    bt["wins"] += 1
                else:
                    bt["losses"] += 1
                bt["win_rate"] = bt["wins"] / bt["count"] if bt["count"] > 0 else 0.0
                bt["avg_pnl"] = bt["total_pnl"] / bt["count"] if bt["count"] > 0 else 0.0
            # Prepend to recent_exits so callers see the latest trade
            if "recent_exits" in c:
                c["recent_exits"].insert(0, {
                    "signal_id": signal_id,
                    "type": signal.get("type", "unknown"),
                    "direction": direction,
                    "pnl": pnl,
                    "is_win": is_win,
                    "exit_reason": exit_reason,
                    "exit_time": exit_time.isoformat(),
                })
                c["recent_exits"] = c["recent_exits"][:10]

        # Determine outcome string for consistent schema
        outcome = "win" if is_win else "loss"

        # Update signal status with all required fields for downstream consumers
        # (AI monitor, Telegram, quality scorer all rely on consistent schema)
        self._update_signal_status(
            signal_id,
            "exited",
            {
                "exit_price": exit_price,
                "exit_time": exit_time.isoformat(),
                "exit_reason": exit_reason,
                "pnl": pnl,
                "is_win": is_win,
                "outcome": outcome,  # Required for quality scorer / win-rate tracking
                "hold_duration_minutes": hold_duration,
                # Promote signal_type to top level for easier querying
                "signal_type": signal.get("type"),
            },
        )

        # Save performance record
        self._save_performance(performance)

        # Dual-write completed trade into SQLite for queryable history + ML training datasets
        try:
            if self._sqlite_enabled and self._trade_db is not None:
                # Extract optional context
                regime_val = None
                try:
                    reg = signal.get("regime", {})
                    if isinstance(reg, dict):
                        regime_val = reg.get("regime")
                    elif isinstance(reg, str):
                        regime_val = reg
                except Exception as e:
                    ErrorHandler.log_and_continue(
                        "track_exit regime extraction", e, category="sqlite",
                    )
                    regime_val = None

                # Extract numeric features if present
                features = {}
                try:
                    raw_features = signal.get("features") or signal.get("ml_features") or signal.get("indicators") or {}
                    if isinstance(raw_features, dict):
                        for k, v in raw_features.items():
                            try:
                                fv = float(v)
                                if fv == fv:  # not NaN
                                    features[str(k)] = fv
                            except (TypeError, ValueError):
                                continue
                except Exception as e:
                    ErrorHandler.log_and_continue(
                        "track_exit feature extraction", e, level="warning", category="sqlite",
                    )
                    features = {}

                # Attach ML prediction fields (for shadow A/B lift measurement).
                # These are stored on the signal as `_ml_prediction` by the signal generator.
                try:
                    ml_pred = signal.get("_ml_prediction")
                    if isinstance(ml_pred, dict):
                        try:
                            features["ml_win_probability"] = float(ml_pred.get("win_probability", 0.0) or 0.0)
                        except Exception as e:
                            ErrorHandler.log_and_continue(
                                "track_exit ml_win_probability", e, category="sqlite",
                            )
                        # Use shadow lift flag when available (separate threshold for measurement only).
                        shadow_pf = signal.get("_ml_shadow_pass_filter", None)
                        shadow_thr = signal.get("_ml_shadow_threshold", None)
                        if shadow_pf is not None:
                            try:
                                features["ml_pass_filter"] = 1.0 if bool(shadow_pf) else 0.0
                            except Exception as e:
                                ErrorHandler.log_and_continue(
                                    "track_exit ml_pass_filter", e, category="sqlite",
                                )
                            try:
                                if shadow_thr is not None:
                                    features["ml_pass_threshold"] = float(shadow_thr)
                            except Exception as e:
                                ErrorHandler.log_and_continue(
                                    "track_exit ml_pass_threshold", e, category="sqlite",
                                )
                        else:
                            try:
                                features["ml_pass_filter"] = 1.0 if bool(ml_pred.get("pass_filter", True)) else 0.0
                            except Exception as e:
                                ErrorHandler.log_and_continue(
                                    "track_exit ml_pass_filter fallback", e, category="sqlite",
                                )
                        try:
                            features["ml_fallback_used"] = 1.0 if bool(ml_pred.get("fallback_used", False)) else 0.0
                        except Exception as e:
                            ErrorHandler.log_and_continue(
                                "track_exit ml_fallback_used", e, category="sqlite",
                            )
                        # Confidence level bucket (low/medium/high) -> numeric (0/1/2) for easy aggregation.
                        try:
                            level = str(ml_pred.get("confidence_level", "") or "").lower()
                            level_map = {"low": 0.0, "medium": 1.0, "high": 2.0}
                            if level in level_map:
                                features["ml_confidence_level"] = float(level_map[level])
                        except Exception as e:
                            ErrorHandler.log_and_continue(
                                "track_exit ml_confidence_level", e, category="sqlite",
                            )
                except Exception as e:
                    ErrorHandler.log_and_continue(
                        "track_exit ML prediction features", e, level="warning", category="sqlite",
                    )

                # Use async queue if available (injected from service.py), else blocking write
                if self._async_sqlite_queue is not None:
                    from pearlalgo.storage.async_sqlite_queue import WritePriority
                    
                    self._async_sqlite_queue.enqueue(
                        "add_trade",
                        priority=WritePriority.HIGH,  # Trade exits are HIGH priority (never drop)
                        trade_id=str(signal_id),
                        signal_id=str(signal_id),
                        signal_type=str(signal.get("type") or signal.get("signal_type") or "unknown"),
                        direction=str(direction),
                        entry_price=float(entry_price),
                        exit_price=float(exit_price),
                        pnl=float(pnl),
                        is_win=bool(is_win),
                        entry_time=str(signal_record.get("entry_time") or signal_record.get("timestamp") or ""),
                        exit_time=str(exit_time.isoformat()),
                        stop_loss=float(signal.get("stop_loss") or 0.0) if signal.get("stop_loss") is not None else None,
                        take_profit=float(signal.get("take_profit") or 0.0) if signal.get("take_profit") is not None else None,
                        exit_reason=str(exit_reason),
                        hold_duration_minutes=float(hold_duration) if hold_duration is not None else None,
                        regime=str(regime_val) if regime_val is not None else None,
                        context_key=str(signal.get("context_key") or "") or None,
                        volatility_percentile=None,
                        volume_percentile=None,
                        features=features or None,
                    )
                else:
                    # Blocking write (legacy/fallback)
                    self._trade_db.add_trade(
                        trade_id=str(signal_id),
                        signal_id=str(signal_id),
                        signal_type=str(signal.get("type") or signal.get("signal_type") or "unknown"),
                        direction=str(direction),
                        entry_price=float(entry_price),
                        exit_price=float(exit_price),
                        pnl=float(pnl),
                        is_win=bool(is_win),
                        entry_time=str(signal_record.get("entry_time") or signal_record.get("timestamp") or ""),
                        exit_time=str(exit_time.isoformat()),
                        stop_loss=float(signal.get("stop_loss") or 0.0) if signal.get("stop_loss") is not None else None,
                        take_profit=float(signal.get("take_profit") or 0.0) if signal.get("take_profit") is not None else None,
                        exit_reason=str(exit_reason),
                        hold_duration_minutes=float(hold_duration) if hold_duration is not None else None,
                        regime=str(regime_val) if regime_val is not None else None,
                        context_key=str(signal.get("context_key") or "") or None,
                        volatility_percentile=None,
                        volume_percentile=None,
                        features=features or None,
                    )
        except Exception as e:
            ErrorHandler.log_and_continue(
                "track_exit SQLite dual-write", e, level="warning", category="sqlite",
            )

        return performance

    def get_performance_metrics(self, days: Optional[int] = None) -> Dict:
        """
        Get performance metrics for the last N days.
        
        Args:
            days: Number of days to analyze (defaults to config value)
            
        Returns:
            Dictionary with performance metrics
        """
        import time as _time

        if days is None:
            days = self._default_lookback_days

        # Ensure running aggregates are initialized (one-time full scan on
        # startup).  Subsequent exits update them incrementally in track_exit().
        if not self._running_aggregates["is_initialized"]:
            self._initialize_running_aggregates()

        # Check TTL cache — return cached result when within TTL and same lookback
        now = _time.monotonic()
        if (
            self._metrics_cache is not None
            and (now - self._metrics_cache_time) < self._METRICS_CACHE_TTL
            and self._metrics_cache_days == days
        ):
            return self._metrics_cache

        cutoff_time = datetime.now(timezone.utc).timestamp() - (days * 24 * 60 * 60)

        # Load all signals
        signals = []
        if self.signals_file.exists():
            try:
                with open(self.signals_file, "r") as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            timestamp_str = record.get("timestamp", "")
                            if timestamp_str:
                                timestamp = parse_utc_timestamp(timestamp_str).timestamp()
                                if timestamp >= cutoff_time:
                                    signals.append(record)
                        except (json.JSONDecodeError, ValueError):
                            continue
            except Exception as e:
                logger.error(f"Error loading signals: {e}")

        # Filter to exited signals only, excluding test signals from P&L calculations
        exited_signals = [
            s for s in signals 
            if s.get("status") == "exited" 
            and not s.get("signal", {}).get("_is_test", False)
            and not s.get("_is_test", False)
        ]

        if not exited_signals:
            result = {
                "total_signals": len(signals),
                "exited_signals": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "avg_pnl": 0.0,
                "avg_hold_minutes": 0.0,
                "by_signal_type": {},
            }
            self._metrics_cache = result
            self._metrics_cache_time = now
            self._metrics_cache_days = days
            return result

        # Calculate metrics
        total_pnl = sum(s.get("pnl", 0) for s in exited_signals)
        wins = sum(1 for s in exited_signals if s.get("is_win", False))
        losses = len(exited_signals) - wins
        win_rate = wins / len(exited_signals) if exited_signals else 0.0

        hold_times = [
            s.get("hold_duration_minutes")
            for s in exited_signals
            if s.get("hold_duration_minutes") is not None
        ]
        avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0.0

        # Metrics by signal type
        # For append-only JSONL events, signal_type is promoted to the root level;
        # for legacy full-record format it's nested under signal.type.
        by_type: Dict[str, Dict] = {}
        for signal in exited_signals:
            signal_type = signal.get("signal_type") or signal.get("signal", {}).get("type", "unknown")
            if signal_type not in by_type:
                by_type[signal_type] = {
                    "count": 0,
                    "wins": 0,
                    "losses": 0,
                    "total_pnl": 0.0,
                }

            by_type[signal_type]["count"] += 1
            if signal.get("is_win", False):
                by_type[signal_type]["wins"] += 1
            else:
                by_type[signal_type]["losses"] += 1
            by_type[signal_type]["total_pnl"] += signal.get("pnl", 0)

        # Calculate win rates by type
        for signal_type, metrics in by_type.items():
            metrics["win_rate"] = (
                metrics["wins"] / metrics["count"] if metrics["count"] > 0 else 0.0
            )
            metrics["avg_pnl"] = (
                metrics["total_pnl"] / metrics["count"] if metrics["count"] > 0 else 0.0
            )

        # Build recent exits list (most recent first)
        # Sort by exit_time descending
        sorted_exits = sorted(
            exited_signals,
            key=lambda x: x.get("exit_time", x.get("timestamp", "")),
            reverse=True,
        )
        recent_exits = []
        for s in sorted_exits[:10]:  # Keep last 10 for display
            sig = s.get("signal", {}) or {}
            recent_exits.append({
                "signal_id": s.get("signal_id"),
                "type": sig.get("type", "unknown"),
                "direction": sig.get("direction", "unknown"),
                "pnl": s.get("pnl", 0),
                "is_win": s.get("is_win", False),
                "exit_reason": s.get("exit_reason", "unknown"),
                "exit_time": s.get("exit_time"),
            })

        result = {
            "total_signals": len(signals),
            "exited_signals": len(exited_signals),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
            "total_pnl": total_pnl,
            "avg_pnl": total_pnl / len(exited_signals) if exited_signals else 0.0,
            "avg_hold_minutes": avg_hold,
            "by_signal_type": by_type,
            "recent_exits": recent_exits,
        }
        self._metrics_cache = result
        self._metrics_cache_time = now
        self._metrics_cache_days = days
        return result

    def _get_signal_record(self, signal_id: str) -> Optional[Dict]:
        """Get signal record by ID.

        Strategy:
        - SQLite available: O(1) indexed lookup via ``signal_events`` table.
        - Fallback: O(n) linear scan of ``signals.jsonl`` (handles both legacy
          single-entry format and append-only ``status_change`` events).
        """
        # --- SQLite fast-path (O(1) indexed lookup) ---
        if self._sqlite_enabled and self._trade_db is not None:
            try:
                record = self._trade_db.get_signal_event_by_id(signal_id)
                if record is not None:
                    return record
            except Exception as e:
                logger.debug(f"SQLite lookup failed for {signal_id}, falling back to JSONL: {e}")

        # --- JSONL fallback (O(n) scan) ---
        if not self.signals_file.exists():
            return None

        try:
            base_record: Optional[Dict] = None
            with open(self.signals_file, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        if record.get("signal_id") != signal_id:
                            continue
                        if record.get("event") == "status_change":
                            # Merge append-only status_change into base record
                            if base_record is not None:
                                base_record.update(record)
                        else:
                            # Original record (or legacy full-rewrite record)
                            base_record = record
                    except (json.JSONDecodeError, ValueError):
                        continue
            # Remove merge artifact so callers don't see "event" key
            if base_record is not None:
                base_record.pop("event", None)
            return base_record
        except Exception as e:
            logger.error(f"Error loading signal record: {e}")

        return None

    def _update_signal_status(self, signal_id: str, status: str, data: Dict) -> None:
        """
        Update signal status.

        Strategy:
        - SQLite available: O(1) SQLite write (primary) + append-only JSONL event.
          No file locking or full-file rewrite needed.
        - SQLite unavailable: Legacy read-modify-rewrite of ``signals.jsonl``
          with file locking (safety net).
        """
        logger.debug(f"Signal {signal_id} status: {status}")

        # --- PRIMARY PATH: SQLite + append-only JSONL ---
        if self._sqlite_enabled and self._trade_db is not None:
            # 1. SQLite update (O(1) — read latest event, merge, write new event)
            try:
                # Fetch current record so the new event payload stays complete
                # (downstream consumers like _get_signal_record expect the full record).
                current_record: Optional[Dict] = None
                try:
                    current_record = self._trade_db.get_signal_event_by_id(signal_id)
                except Exception:
                    pass  # OK — proceed with partial payload

                event_payload = current_record if isinstance(current_record, dict) else {}
                event_payload["signal_id"] = signal_id
                event_payload["status"] = status
                event_payload.update(data or {})

                event_ts = get_utc_timestamp()

                self._trade_db.add_signal_event(
                    signal_id=str(signal_id),
                    status=str(status),
                    timestamp=event_ts,
                    payload=event_payload,
                )
            except Exception as e:
                ErrorHandler.log_and_continue(
                    "_update_signal_status SQLite write", e,
                    level="warning", category="sqlite",
                )

            # 2. Append status-change event to JSONL (append-only, no rewrite)
            if self.signals_file.exists():
                try:
                    event_line: Dict = {
                        "signal_id": signal_id,
                        "status": status,
                        "event": "status_change",
                        "timestamp": get_utc_timestamp(),
                    }
                    event_line.update(data or {})
                    with open(self.signals_file, "a") as f:
                        f.write(json.dumps(event_line) + "\n")
                except Exception as e:
                    ErrorHandler.log_and_continue(
                        "_update_signal_status JSONL append", e,
                        level="warning", category="file_io",
                    )
            return

        # --- FALLBACK: Legacy read-modify-rewrite (no SQLite available) ---
        if not self.signals_file.exists():
            return

        # Acquire exclusive lock on the signals file during read-modify-write
        lock_path = Path(str(self.signals_file) + ".lock")
        try:
            with file_lock(lock_path):
                # Read all records
                records = []
                with open(self.signals_file, "r") as f:
                    for line in f:
                        try:
                            record = json.loads(line.strip())
                            records.append(record)
                        except (json.JSONDecodeError, ValueError):
                            continue

                # Update matching record
                updated = False
                for record in records:
                    if record.get("signal_id") == signal_id:
                        record["status"] = status
                        record.update(data)
                        updated = True
                        break

                # If not found, log warning and exit
                if not updated:
                    logger.warning(f"Signal {signal_id} not found for status update")
                    return

                atomic_write_jsonl(self.signals_file, records)
        except Exception as e:
            ErrorHandler.log_and_continue(
                "_update_signal_status", e, level="error", category="file_io",
            )

    def load_performance_data(self) -> list:
        """Load all performance records from ``performance.json``.

        Returns:
            List of trade-performance dicts (empty list if file is
            missing or corrupt).
        """
        if not self.performance_file.exists():
            return []
        try:
            with open(self.performance_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            return []
        except Exception as e:
            logger.error(f"Error loading performance data: {e}")
            return []

    def _save_performance(self, performance: Dict) -> None:
        """Save performance record with file locking and atomic write.

        Uses the same ``file_lock`` + ``atomic_write_json`` pattern as
        ``_update_signal_status`` to prevent concurrent read-modify-write
        races from dropping records.
        """
        lock_path = self.performance_file.with_suffix(".lock")
        try:
            with file_lock(lock_path):
                performances = []
                if self.performance_file.exists():
                    try:
                        with open(self.performance_file, "r") as f:
                            performances = json.load(f)
                    except Exception as e:
                        logger.error(f"Error loading performance records: {e}")

                performances.append(performance)

                # Keep only last N records (from config)
                if len(performances) > self._max_records:
                    performances = performances[-self._max_records:]

                atomic_write_json(self.performance_file, performances)
        except Exception as e:
            logger.error(f"Error saving performance record: {e}")

    # ------------------------------------------------------------------
    # Running aggregates – incremental O(1) updates per trade exit
    # ------------------------------------------------------------------

    def _initialize_running_aggregates(self) -> None:
        """One-time full scan of signals.jsonl to seed running aggregates.

        Called lazily on the first ``get_performance_metrics()`` invocation.
        After this, ``_update_running_aggregates()`` keeps them current in
        O(1) on every ``track_exit()``.
        """
        agg = self._running_aggregates
        agg.update({
            "total_pnl": 0.0,
            "total_trades": 0,
            "wins": 0,
            "losses": 0,
            "total_win_pnl": 0.0,
            "total_loss_pnl": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
        })

        if not self.signals_file.exists():
            agg["is_initialized"] = True
            return

        try:
            with open(self.signals_file, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        if record.get("status") != "exited":
                            continue
                        # Skip test signals
                        if record.get("_is_test", False):
                            continue
                        sig = record.get("signal", {})
                        if isinstance(sig, dict) and sig.get("_is_test", False):
                            continue

                        pnl = float(record.get("pnl", 0))
                        is_win = bool(record.get("is_win", False))

                        agg["total_pnl"] += pnl
                        agg["total_trades"] += 1
                        if is_win:
                            agg["wins"] += 1
                            agg["total_win_pnl"] += pnl
                            agg["max_win"] = max(agg["max_win"], pnl)
                        else:
                            agg["losses"] += 1
                            agg["total_loss_pnl"] += pnl
                            agg["max_loss"] = min(agg["max_loss"], pnl)
                    except (json.JSONDecodeError, ValueError, TypeError):
                        continue
        except Exception as e:
            logger.error(f"Error initializing running aggregates: {e}")

        agg["is_initialized"] = True
        if agg["total_trades"] > 0:
            wr = agg["wins"] / agg["total_trades"] * 100
            logger.info(
                f"Running aggregates initialized: {agg['total_trades']} trades, "
                f"PnL={agg['total_pnl']:.2f}, win_rate={wr:.1f}%"
            )
        else:
            logger.info("Running aggregates initialized: 0 trades")

    def _update_running_aggregates(self, pnl: float, is_win: bool) -> None:
        """Incrementally update running aggregates with a new trade exit.

        O(1) — no file I/O required.  If aggregates are not yet
        initialized (first ``get_performance_metrics()`` hasn't run),
        this is a no-op; the full initialization scan will pick up
        the trade from the file.
        """
        agg = self._running_aggregates
        if not agg["is_initialized"]:
            return

        agg["total_pnl"] += pnl
        agg["total_trades"] += 1
        if is_win:
            agg["wins"] += 1
            agg["total_win_pnl"] += pnl
            agg["max_win"] = max(agg["max_win"], pnl)
        else:
            agg["losses"] += 1
            agg["total_loss_pnl"] += pnl
            agg["max_loss"] = min(agg["max_loss"], pnl)

    # ------------------------------------------------------------------
    # Async wrappers – run blocking file I/O in a thread to avoid
    # stalling the async event loop.
    # ------------------------------------------------------------------

    async def _update_signal_status_async(self, signal_id: str, status: str, data: Dict) -> None:
        """Async wrapper for _update_signal_status() – runs file I/O in a thread."""
        return await asyncio.to_thread(self._update_signal_status, signal_id, status, data)

    async def update_signal_prices_async(
        self,
        signal_id: str,
        *,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        updated_at: Optional[datetime] = None,
        source: str = "trade_manager",
    ) -> None:
        """Async wrapper for update_signal_prices() – runs file I/O in a thread."""
        return await asyncio.to_thread(
            self.update_signal_prices,
            signal_id,
            stop_loss=stop_loss,
            take_profit=take_profit,
            updated_at=updated_at,
            source=source,
        )

    async def get_performance_metrics_async(self, days: Optional[int] = None) -> Dict:
        """Async wrapper for get_performance_metrics() – runs file I/O in a thread."""
        return await asyncio.to_thread(self.get_performance_metrics, days)

    async def _save_performance_async(self, performance: Dict) -> None:
        """Async wrapper for _save_performance() – runs file I/O in a thread."""
        return await asyncio.to_thread(self._save_performance, performance)
