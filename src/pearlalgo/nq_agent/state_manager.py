"""
NQ Agent State Manager

Manages state persistence for the NQ agent service.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import (
    ensure_state_dir,
    get_signals_file,
    get_state_file,
    get_utc_timestamp,
)

# Import get_utc_timestamp is already in the import above


class NQAgentStateManager:
    """
    Manages state persistence for NQ agent.
    
    Stores signals, positions, and service state.
    """

    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize state manager.
        
        Args:
            state_dir: Directory for state files (default: ./data/nq_agent_state)
        """
        self.state_dir = ensure_state_dir(state_dir)
        self.signals_file = get_signals_file(self.state_dir)
        self.state_file = get_state_file(self.state_dir)

        logger.info(f"NQAgentStateManager initialized: state_dir={self.state_dir}")

    def save_signal(self, signal: Dict) -> None:
        """
        Save a signal to persistent storage.
        
        Saves in the format expected by /signals command:
        {
            "signal_id": "...",
            "timestamp": "...",
            "status": "generated",
            "signal": {...}
        }
        
        Args:
            signal: Signal dictionary (should already have signal_id set)
        """
        try:
            # Extract signal_id from signal dict (set by performance_tracker)
            signal_id = signal.get("signal_id", "")
            if not signal_id:
                # Generate one if missing (shouldn't happen, but be safe)
                from datetime import datetime, timezone
                signal_id = f"{signal.get('type', 'unknown')}_{datetime.now(timezone.utc).timestamp()}"
                signal["signal_id"] = signal_id
            
            # Create wrapped record in format expected by /signals command
            signal_record = {
                "signal_id": signal_id,
                "timestamp": get_utc_timestamp(),
                "status": "generated",  # Default status for new signals
                "signal": signal,  # Store full signal dict
            }
            
            with open(self.signals_file, "a") as f:
                f.write(json.dumps(signal_record) + "\n")
            
            logger.debug(f"Saved signal {signal_id} to {self.signals_file}")
        except Exception as e:
            logger.error(f"Error saving signal: {e}", exc_info=True)

    def get_recent_signals(self, limit: int = 100) -> List[Dict]:
        """
        Get recent signals.
        
        Args:
            limit: Maximum number of signals to return
            
        Returns:
            List of signal dictionaries
        """
        signals = []

        if not self.signals_file.exists():
            return signals

        try:
            with open(self.signals_file, "r") as f:
                lines = f.readlines()
                for line in lines[-limit:]:
                    try:
                        signal = json.loads(line.strip())
                        signals.append(signal)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Error reading signals: {e}")

        return signals

    def save_state(self, state: Dict) -> None:
        """
        Save service state.
        
        Args:
            state: State dictionary
        """
        try:
            state["last_updated"] = get_utc_timestamp()
            with open(self.state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving state: {e}")

    def load_state(self) -> Dict:
        """
        Load service state.
        
        Returns:
            State dictionary (empty dict if no state exists)
        """
        if not self.state_file.exists():
            return {}

        try:
            with open(self.state_file, "r") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading state: {e}")
            return {}
