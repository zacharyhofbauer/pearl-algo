"""
Data adapters for Mini App.

Reads from existing state files (signals.jsonl, state.json, performance.json, etc.)
to provide data for the Decision Room terminal.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_signals_file,
    get_state_file,
)
from pearlalgo.utils.logger import logger


class MiniAppDataProvider:
    """
    Provides data for the Mini App from existing state files.
    
    This is a read-only adapter that doesn't modify any state.
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize data provider.
        
        Args:
            state_dir: Path to state directory (defaults to standard location)
        """
        self.state_dir = ensure_state_dir(state_dir)
        self._notes_file = self.state_dir / "signal_notes.json"
        self._notes_cache: Dict[str, List[str]] = {}
        self._load_notes()
    
    def _load_notes(self):
        """Load notes from file."""
        if self._notes_file.exists():
            try:
                with open(self._notes_file, "r") as f:
                    self._notes_cache = json.load(f)
            except Exception as e:
                logger.warning(f"Could not load notes: {e}")
                self._notes_cache = {}
    
    def _save_notes(self):
        """Save notes to file."""
        try:
            with open(self._notes_file, "w") as f:
                json.dump(self._notes_cache, f, indent=2)
        except Exception as e:
            logger.warning(f"Could not save notes: {e}")
    
    def get_state(self) -> Dict[str, Any]:
        """
        Get current agent state.
        
        Returns:
            State dictionary or empty dict if not available
        """
        state_file = get_state_file(self.state_dir)
        if not state_file.exists():
            return {}
        
        try:
            with open(state_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read state: {e}")
            return {}
    
    def get_performance(self) -> Dict[str, Any]:
        """
        Get performance metrics.
        
        Returns:
            Performance dictionary or empty dict if not available
        """
        perf_file = self.state_dir / "performance.json"
        if not perf_file.exists():
            return {}
        
        try:
            with open(perf_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read performance: {e}")
            return {}
    
    def get_signals(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get recent signals.
        
        Args:
            limit: Maximum number of signals to return
            
        Returns:
            List of signal dictionaries (newest first)
        """
        signals_file = get_signals_file(self.state_dir)
        if not signals_file.exists():
            return []
        
        signals = []
        try:
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            signals.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.warning(f"Could not read signals: {e}")
            return []
        
        # Return newest first
        signals.reverse()
        return signals[:limit]
    
    def get_signal_by_id(self, signal_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific signal by ID.
        
        Args:
            signal_id: Signal ID (can be partial prefix)
            
        Returns:
            Signal dictionary or None if not found
        """
        signals_file = get_signals_file(self.state_dir)
        if not signals_file.exists():
            return None
        
        try:
            with open(signals_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            signal = json.loads(line)
                            sid = signal.get("signal_id", "")
                            # Match full ID or prefix
                            if sid == signal_id or sid.startswith(signal_id):
                                return signal
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.warning(f"Could not read signals: {e}")
        
        return None
    
    def get_active_trades(self) -> List[Dict[str, Any]]:
        """
        Get currently active trades.
        
        Returns:
            List of active trade dictionaries
        """
        state = self.get_state()
        return state.get("active_trades", [])
    
    def get_policy_state(self) -> Dict[str, Any]:
        """
        Get bandit policy state (for ATS constraints).
        
        Returns:
            Policy state dictionary or empty dict
        """
        policy_file = self.state_dir / "policy_state.json"
        if not policy_file.exists():
            return {}
        
        try:
            with open(policy_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not read policy state: {e}")
            return {}
    
    def get_notes(self, signal_id: str) -> List[str]:
        """
        Get notes for a signal.
        
        Args:
            signal_id: Signal ID
            
        Returns:
            List of note strings
        """
        return self._notes_cache.get(signal_id, [])
    
    def add_note(self, signal_id: str, note: str) -> bool:
        """
        Add a note for a signal.
        
        Args:
            signal_id: Signal ID
            note: Note text
            
        Returns:
            True if saved successfully
        """
        if signal_id not in self._notes_cache:
            self._notes_cache[signal_id] = []
        
        # Add timestamp to note
        timestamp = datetime.now(timezone.utc).isoformat()
        timestamped_note = f"[{timestamp}] {note}"
        self._notes_cache[signal_id].append(timestamped_note)
        
        self._save_notes()
        return True
    
    def get_data_quality(self) -> Tuple[str, Optional[float], bool, Optional[str]]:
        """
        Get data quality information.
        
        Returns:
            Tuple of (level, age_minutes, is_stale, explanation)
        """
        state = self.get_state()
        
        # Get data level
        data_level = state.get("data_level", "unknown")
        
        # Get data age
        age_minutes = None
        is_stale = False
        last_bar_time = state.get("last_bar_time")
        if last_bar_time:
            try:
                if isinstance(last_bar_time, str):
                    last_bar_dt = datetime.fromisoformat(last_bar_time.replace("Z", "+00:00"))
                else:
                    last_bar_dt = last_bar_time
                if last_bar_dt.tzinfo is None:
                    last_bar_dt = last_bar_dt.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - last_bar_dt
                age_minutes = age.total_seconds() / 60
                is_stale = age_minutes > 10  # 10 minute threshold
            except Exception:
                pass
        
        # Build explanation
        explanation = None
        if data_level in ("historical", "historical_fallback"):
            explanation = "Using historical data (Level 1 quotes unavailable)"
            if is_stale:
                explanation += f". Data is {age_minutes:.1f} minutes old."
        elif data_level == "error":
            explanation = "Data fetch error - check Gateway connection"
        elif data_level == "unknown":
            explanation = "Data source unknown"
        elif is_stale and age_minutes is not None:
            explanation = f"Data is stale ({age_minutes:.1f} minutes old)"
        
        return data_level, age_minutes, is_stale, explanation
    
    def get_ohlcv(
        self,
        lookback_hours: float = 12.0,
    ) -> List[Dict[str, Any]]:
        """
        Get OHLCV data for charting.
        
        This reads from the cached historical data or buffer in state.
        
        Args:
            lookback_hours: Hours of data to return
            
        Returns:
            List of OHLCV bar dictionaries
        """
        # Try to read from parquet cache first
        historical_dir = self.state_dir.parent / "historical"
        parquet_file = historical_dir / "MNQ_1m_2w.parquet"
        
        if parquet_file.exists():
            try:
                import pandas as pd
                df = pd.read_parquet(parquet_file)
                
                # Filter to lookback window
                end_time = datetime.now(timezone.utc)
                start_time = end_time - timedelta(hours=lookback_hours)
                
                # Handle timestamp column or index
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                    mask = df["timestamp"] >= start_time
                    df = df[mask]
                elif isinstance(df.index, pd.DatetimeIndex):
                    df = df.loc[start_time:]
                
                # Convert to list of dicts
                bars = []
                for _, row in df.iterrows():
                    bar = {
                        "timestamp": row.get("timestamp", row.name).isoformat() if hasattr(row.get("timestamp", row.name), "isoformat") else str(row.get("timestamp", row.name)),
                        "open": float(row.get("open", 0)),
                        "high": float(row.get("high", 0)),
                        "low": float(row.get("low", 0)),
                        "close": float(row.get("close", 0)),
                        "volume": int(row.get("volume", 0)),
                    }
                    bars.append(bar)
                
                return bars
            except Exception as e:
                logger.warning(f"Could not read parquet data: {e}")
        
        # Fallback: try buffer from state
        state = self.get_state()
        buffer = state.get("buffer", [])
        
        if buffer:
            # Filter to lookback window
            end_time = datetime.now(timezone.utc)
            start_time = end_time - timedelta(hours=lookback_hours)
            
            bars = []
            for bar in buffer:
                try:
                    ts = bar.get("timestamp")
                    if isinstance(ts, str):
                        bar_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    else:
                        bar_time = ts
                    
                    if bar_time.tzinfo is None:
                        bar_time = bar_time.replace(tzinfo=timezone.utc)
                    
                    if bar_time >= start_time:
                        bars.append({
                            "timestamp": bar_time.isoformat(),
                            "open": float(bar.get("open", 0)),
                            "high": float(bar.get("high", 0)),
                            "low": float(bar.get("low", 0)),
                            "close": float(bar.get("close", 0)),
                            "volume": int(bar.get("volume", 0)),
                        })
                except Exception:
                    continue
            
            return bars
        
        return []
    
    def build_evidence(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build evidence structure from signal context.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Evidence dictionary
        """
        context = signal.get("context", {})
        
        return {
            "mtf_alignment": context.get("mtf_alignment"),
            "regime": context.get("regime"),
            "vwap_location": context.get("vwap_position"),
            "pressure": context.get("pressure"),
            "additional": {
                k: v for k, v in context.items()
                if k not in ("mtf_alignment", "regime", "vwap_position", "pressure")
            },
        }
    
    def build_risks(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build risks structure from signal.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            Risks dictionary
        """
        # Extract invalidation and key levels
        context = signal.get("context", {})
        
        # Build invalidation description
        invalidation = None
        direction = signal.get("direction", "").upper()
        stop_loss = signal.get("stop_loss")
        entry_price = signal.get("entry_price")
        
        if stop_loss and entry_price:
            if direction == "LONG":
                invalidation = f"Price below ${stop_loss:.2f} invalidates setup"
            else:
                invalidation = f"Price above ${stop_loss:.2f} invalidates setup"
        
        # Key levels from context
        key_levels = []
        if stop_loss:
            key_levels.append(stop_loss)
        take_profit = signal.get("take_profit")
        if take_profit:
            key_levels.append(take_profit)
        
        # Warnings
        warnings = []
        confidence = signal.get("confidence", 0)
        if confidence < 0.5:
            warnings.append("Low confidence signal")
        
        data_level, age_minutes, is_stale, _ = self.get_data_quality()
        if is_stale:
            warnings.append(f"Data is stale ({age_minutes:.1f}m old)")
        if data_level in ("historical", "historical_fallback"):
            warnings.append("Using historical fallback (no live quotes)")
        
        return {
            "invalidation": invalidation,
            "key_levels": key_levels,
            "warnings": warnings,
        }
    
    def build_ats_constraints(self) -> Dict[str, Any]:
        """
        Build ATS constraints from policy state.
        
        Returns:
            ATS constraints dictionary
        """
        policy = self.get_policy_state()
        state = self.get_state()
        
        # Check if armed (from state)
        armed = state.get("execution_armed", False)
        
        # Get daily PnL (simplified)
        perf = self.get_performance()
        current_daily_pnl = perf.get("daily_pnl", 0.0)
        
        # Max daily loss from config (would need to read config, use default)
        max_daily_loss = 500.0  # Default
        
        # Session allowed (from state)
        session_open = state.get("strategy_session_open", True)
        
        return {
            "armed": armed,
            "max_daily_loss": max_daily_loss,
            "current_daily_pnl": current_daily_pnl,
            "session_allowed": session_open,
            "position_size": None,  # Would come from signal
            "risk_per_trade": None,  # Would come from signal
        }
    
    def build_ml_view(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build ML view from signal.
        
        Args:
            signal: Signal dictionary
            
        Returns:
            ML view dictionary
        """
        confidence = signal.get("confidence", 0)
        
        # Determine tier
        if confidence >= 0.75:
            tier = "High"
        elif confidence >= 0.5:
            tier = "Moderate"
        else:
            tier = "Low"
        
        # Extract features from context
        context = signal.get("context", {})
        features = {
            "confidence": confidence,
            "signal_type": signal.get("type"),
            "direction": signal.get("direction"),
        }
        
        # Add any feature_ prefixed keys from context
        for key, value in context.items():
            if key.startswith("feature_") or key in ("score", "strength"):
                features[key] = value
        
        # Diagnostics from reason
        diagnostics = signal.get("reason")
        
        return {
            "confidence": confidence,
            "confidence_tier": tier,
            "features": features,
            "diagnostics": diagnostics,
        }


def get_data_provider() -> MiniAppDataProvider:
    """Get a configured MiniAppDataProvider instance."""
    return MiniAppDataProvider()


