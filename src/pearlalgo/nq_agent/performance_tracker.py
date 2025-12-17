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
        self.state_dir = ensure_state_dir(state_dir)

        # State manager for signal persistence (delegation)
        self.state_manager = state_manager
        self.signals_file = get_signals_file(self.state_dir)
        self.performance_file = get_performance_file(self.state_dir)

        # Load performance configuration
        service_config = load_service_config()
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
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Signal ID for tracking
        """
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
                "signal": signal,
            }
            try:
                with open(self.signals_file, "a") as f:
                    f.write(json.dumps(signal_record) + "\n")
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

        signal = signal_record.get("signal", {})
        entry_price = signal.get("entry_price", 0)
        direction = signal.get("direction", "long").lower()

        # Calculate P&L (simplified - assumes 1 contract)
        if direction == "long":
            pnl = (exit_price - entry_price) * 20  # NQ tick value
        else:
            pnl = (entry_price - exit_price) * 20

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

        # Update signal status
        self._update_signal_status(
            signal_id,
            "exited",
            {
                "exit_price": exit_price,
                "exit_time": exit_time.isoformat(),
                "exit_reason": exit_reason,
                "pnl": pnl,
                "is_win": is_win,
            },
        )

        # Save performance record
        self._save_performance(performance)

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

        # Filter to exited signals only
        exited_signals = [s for s in signals if s.get("status") == "exited"]

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

