"""
NQ Agent State Manager

Manages state persistence for the NQ agent service.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pearlalgo.utils.logger import logger


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
        if state_dir is None:
            state_dir = Path("data/nq_agent_state")

        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.signals_file = self.state_dir / "signals.jsonl"
        self.state_file = self.state_dir / "state.json"

        logger.info(f"NQAgentStateManager initialized: state_dir={self.state_dir}")

    def save_signal(self, signal: Dict) -> None:
        """
        Save a signal to persistent storage.
        
        Args:
            signal: Signal dictionary
        """
        try:
            with open(self.signals_file, "a") as f:
                f.write(json.dumps(signal) + "\n")
        except Exception as e:
            logger.error(f"Error saving signal: {e}")

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
            state["last_updated"] = datetime.now(timezone.utc).isoformat()
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
