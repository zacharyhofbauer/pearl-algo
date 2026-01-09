"""
NQ Agent Performance Tracker

Tracks signal performance and calculates metrics.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_performance_file,
    get_signals_file,
    get_utc_timestamp,
    parse_utc_timestamp,
)
from pearlalgo.nq_agent.state_manager import _to_json_safe

try:
    from pearlalgo.learning.trade_database import TradeDatabase
    SQLITE_AVAILABLE = True
except Exception:
    SQLITE_AVAILABLE = False
    TradeDatabase = None  # type: ignore

if TYPE_CHECKING:
    from pearlalgo.nq_agent.state_manager import NQAgentStateManager


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
        state_manager: Optional["NQAgentStateManager"] = None,
    ):
        """
        Initialize performance tracker.
        
        Args:
            state_dir: Directory for state files (default: ./data/nq_agent_state)
            state_manager: State manager instance for signal persistence (optional)
        """
        # Track whether caller explicitly provided a state_dir (tests do this).
        # If explicit, SQLite writes MUST stay inside that directory to avoid polluting
        # the live agent DB under data/nq_agent_state.
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
        self._async_sqlite_queue = None  # Injected from service.py if async writes enabled
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

        logger.info(f"PerformanceTracker initialized: state_dir={self.state_dir}")

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
                        minimal = {
                            "signal_id": signal_id,
                            "timestamp": get_utc_timestamp(),
                            "status": "generated",
                            "signal": {
                                "signal_id": signal_id,
                                "timestamp": str(signal.get("timestamp") or ""),
                                "symbol": str(signal.get("symbol") or ""),
                                "type": str(signal.get("type") or "unknown"),
                                "direction": str(signal.get("direction") or "unknown"),
                                "entry_price": float(signal.get("entry_price") or 0.0),
                                "stop_loss": float(signal.get("stop_loss") or 0.0),
                                "take_profit": float(signal.get("take_profit") or 0.0),
                                "confidence": float(signal.get("confidence") or 0.0),
                                "reason": str(signal.get("reason") or ""),
                            },
                        }
                        payload = json.dumps(minimal)
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
        """
        if stop_loss is None and take_profit is None:
            return
        if not self.signals_file.exists():
            return
        if updated_at is None:
            updated_at = datetime.now(timezone.utc)

        # Read all records (jsonl), update one, write back.
        records: List[Dict] = []
        try:
            with open(self.signals_file, "r") as f:
                for line in f:
                    try:
                        records.append(json.loads(line.strip()))
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception as e:
            logger.debug(f"Could not read signals file for price update: {e}")
            return

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
                except Exception:
                    pass
            if take_profit is not None:
                try:
                    sig["take_profit"] = float(take_profit)
                    record["take_profit_updated_at"] = updated_at.isoformat()
                except Exception:
                    pass
            record["price_update_source"] = str(source)
            record["signal"] = sig
            updated = True
            break

        if not updated:
            return

        try:
            with open(self.signals_file, "w") as f:
                for record in records:
                    f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.debug(f"Could not write signals file for price update: {e}")

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
        entry_price = float(signal.get("entry_price", 0) or 0.0)
        direction = str(signal.get("direction", "long") or "long").lower()

        # MNQ-native P&L:
        # pnl = points * $/point * contracts
        try:
            tick_value = float(signal.get("tick_value") or 2.0)  # $ per point (MNQ default)
        except Exception:
            tick_value = 2.0
        try:
            position_size = float(signal.get("position_size") or 1.0)
        except Exception:
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

        # Determine outcome string for consistent schema
        outcome = "win" if is_win else "loss"

        # Update signal status with all required fields for downstream consumers
        # (Claude Monitor, Telegram, quality scorer all rely on consistent schema)
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
                except Exception:
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
                            except Exception:
                                continue
                except Exception:
                    features = {}

                # Attach ML prediction fields (for shadow A/B lift measurement).
                # These are stored on the signal as `_ml_prediction` by NQSignalGenerator.
                try:
                    ml_pred = signal.get("_ml_prediction")
                    if isinstance(ml_pred, dict):
                        try:
                            features["ml_win_probability"] = float(ml_pred.get("win_probability", 0.0) or 0.0)
                        except Exception:
                            pass
                        try:
                            features["ml_pass_filter"] = 1.0 if bool(ml_pred.get("pass_filter", True)) else 0.0
                        except Exception:
                            pass
                        try:
                            features["ml_fallback_used"] = 1.0 if bool(ml_pred.get("fallback_used", False)) else 0.0
                        except Exception:
                            pass
                        # Confidence level bucket (low/medium/high) -> numeric (0/1/2) for easy aggregation.
                        try:
                            level = str(ml_pred.get("confidence_level", "") or "").lower()
                            level_map = {"low": 0.0, "medium": 1.0, "high": 2.0}
                            if level in level_map:
                                features["ml_confidence_level"] = float(level_map[level])
                        except Exception:
                            pass
                except Exception:
                    pass

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
            logger.debug(f"Could not write trade to SQLite: {e}")

        return performance

    def get_performance_metrics(self, days: Optional[int] = None) -> Dict:
        """
        Get performance metrics for the last N days.
        
        Args:
            days: Number of days to analyze (defaults to config value)
            
        Returns:
            Dictionary with performance metrics
        """
        if days is None:
            days = self._default_lookback_days
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
            return {
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
        by_type: Dict[str, Dict] = {}
        for signal in exited_signals:
            signal_type = signal.get("signal", {}).get("type", "unknown")
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

        return {
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

    def _get_signal_record(self, signal_id: str) -> Optional[Dict]:
        """Get signal record by ID."""
        if not self.signals_file.exists():
            return None

        try:
            with open(self.signals_file, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        if record.get("signal_id") == signal_id:
                            return record
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception as e:
            logger.error(f"Error loading signal record: {e}")

        return None

    def _update_signal_status(self, signal_id: str, status: str, data: Dict) -> None:
        """Update signal status (read all, update, write back)."""
        logger.debug(f"Signal {signal_id} status: {status}")

        if not self.signals_file.exists():
            return

        # Read all records
        records = []
        try:
            with open(self.signals_file, "r") as f:
                for line in f:
                    try:
                        record = json.loads(line.strip())
                        records.append(record)
                    except (json.JSONDecodeError, ValueError):
                        continue
        except Exception as e:
            logger.error(f"Error reading signals file: {e}")
            return

        # Update matching record
        updated = False
        for record in records:
            if record.get("signal_id") == signal_id:
                record["status"] = status
                record.update(data)
                updated = True
                break

        # If not found, create a new record (shouldn't happen, but handle gracefully)
        if not updated:
            logger.warning(f"Signal {signal_id} not found for status update")
            return

        # Write all records back
        try:
            with open(self.signals_file, "w") as f:
                for record in records:
                    f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error(f"Error writing signals file: {e}")

        # Dual-write signal event into SQLite (append-only event log)
        try:
            if self._sqlite_enabled and self._trade_db is not None:
                # Find the updated record (for payload snapshot)
                payload = None
                for record in records:
                    if record.get("signal_id") == signal_id:
                        payload = record
                        break
                self._trade_db.add_signal_event(
                    signal_id=str(signal_id),
                    status=str(status),
                    timestamp=str(payload.get("timestamp") if isinstance(payload, dict) else get_utc_timestamp()),
                    payload=payload if isinstance(payload, dict) else {"signal_id": signal_id, "status": status, **(data or {})},
                )
        except Exception as e:
            logger.debug(f"Could not write signal event to SQLite: {e}")

    def _save_performance(self, performance: Dict) -> None:
        """Save performance record."""
        # Load existing performance records
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

        try:
            with open(self.performance_file, "w") as f:
                json.dump(performances, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving performance record: {e}")

