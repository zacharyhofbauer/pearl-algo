"""
Monitor State - Persistent state management for Claude monitor observations.

Tracks Claude's analysis history, suggestions, and applied changes for
learning and audit purposes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import ensure_state_dir, get_utc_timestamp


class MonitorState:
    """
    Manages persistent state for Claude monitor.
    
    Tracks:
    - Analysis history (observations over time)
    - Active suggestions
    - Applied changes (audit log)
    - Learning data (what worked, what didn't)
    """
    
    def __init__(self, state_dir: Optional[Path] = None):
        """
        Initialize monitor state.
        
        Args:
            state_dir: Directory for state files (defaults to data/nq_agent_state/)
        """
        self.state_dir = ensure_state_dir(state_dir)
        
        # State files
        self.observations_file = self.state_dir / "claude_observations.jsonl"
        self.suggestions_file = self.state_dir / "claude_suggestions.json"
        self.changes_file = self.state_dir / "claude_applied_changes.jsonl"
        self.monitor_state_file = self.state_dir / "claude_monitor_state.json"
        
        # In-memory state
        self._active_suggestions: Dict[str, Dict[str, Any]] = {}
        self._last_analysis: Optional[Dict[str, Any]] = None
        self._analysis_count = 0
        self._alert_count = 0
        self._suggestion_count = 0
        self._applied_count = 0
        self._last_daily_report_sent_at: Optional[str] = None
        self._last_weekly_report_sent_at: Optional[str] = None

        # Regime tracking (used for "strategy update on market change" prompts)
        self._last_regime_seen: Optional[Dict[str, Any]] = None
        self._last_regime_seen_at: Optional[str] = None
        self._last_regime_prompt_signature: Optional[str] = None
        self._last_regime_prompt_at: Optional[str] = None
        
        # Load existing state
        self._load_state()
    
    def _load_state(self) -> None:
        """Load existing state from disk."""
        try:
            if self.monitor_state_file.exists():
                with open(self.monitor_state_file, "r") as f:
                    state = json.load(f)
                    self._analysis_count = state.get("analysis_count", 0)
                    self._alert_count = state.get("alert_count", 0)
                    self._suggestion_count = state.get("suggestion_count", 0)
                    self._applied_count = state.get("applied_count", 0)
                    self._last_daily_report_sent_at = state.get("last_daily_report_sent_at")
                    self._last_weekly_report_sent_at = state.get("last_weekly_report_sent_at")
                    self._last_regime_seen = state.get("last_regime_seen")
                    self._last_regime_seen_at = state.get("last_regime_seen_at")
                    self._last_regime_prompt_signature = state.get("last_regime_prompt_signature")
                    self._last_regime_prompt_at = state.get("last_regime_prompt_at")
                    logger.debug(f"Loaded monitor state: {self._analysis_count} analyses, {self._applied_count} applied")
            
            if self.suggestions_file.exists():
                with open(self.suggestions_file, "r") as f:
                    self._active_suggestions = json.load(f)
                    logger.debug(f"Loaded {len(self._active_suggestions)} active suggestions")
                    
        except Exception as e:
            logger.warning(f"Could not load monitor state: {e}")
    
    def _save_state(self) -> None:
        """Save current state to disk."""
        try:
            state = {
                "analysis_count": self._analysis_count,
                "alert_count": self._alert_count,
                "suggestion_count": self._suggestion_count,
                "applied_count": self._applied_count,
                "last_daily_report_sent_at": self._last_daily_report_sent_at,
                "last_weekly_report_sent_at": self._last_weekly_report_sent_at,
                "last_regime_seen": self._last_regime_seen,
                "last_regime_seen_at": self._last_regime_seen_at,
                "last_regime_prompt_signature": self._last_regime_prompt_signature,
                "last_regime_prompt_at": self._last_regime_prompt_at,
                "last_updated": get_utc_timestamp(),
            }
            with open(self.monitor_state_file, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save monitor state: {e}")

    def get_last_daily_report_sent_at(self) -> Optional[str]:
        """Return the last daily report sent timestamp (UTC ISO) if known."""
        return self._last_daily_report_sent_at

    def set_last_daily_report_sent_at(self, timestamp: str) -> None:
        """Persist the last daily report sent timestamp (UTC ISO)."""
        self._last_daily_report_sent_at = timestamp
        self._save_state()

    def get_last_weekly_report_sent_at(self) -> Optional[str]:
        """Return the last weekly report sent timestamp (UTC ISO) if known."""
        return self._last_weekly_report_sent_at

    def set_last_weekly_report_sent_at(self, timestamp: str) -> None:
        """Persist the last weekly report sent timestamp (UTC ISO)."""
        self._last_weekly_report_sent_at = timestamp
        self._save_state()

    # =========================================================================
    # Regime prompt state (market change → strategy update proposals)
    # =========================================================================

    def get_last_regime_seen(self) -> Optional[Dict[str, Any]]:
        """Return the last regime snapshot seen by the monitor (if any)."""
        return self._last_regime_seen

    def set_last_regime_seen(self, regime: Optional[Dict[str, Any]], timestamp: Optional[str] = None) -> None:
        """Persist the last regime snapshot seen by the monitor."""
        self._last_regime_seen = regime
        self._last_regime_seen_at = timestamp
        self._save_state()

    def get_last_regime_prompt(self) -> Dict[str, Any]:
        """Return last regime prompt metadata (signature + timestamp)."""
        return {
            "signature": self._last_regime_prompt_signature,
            "timestamp": self._last_regime_prompt_at,
        }

    def set_last_regime_prompt(self, signature: str, timestamp: Optional[str] = None) -> None:
        """Persist that we prompted for a specific regime transition signature."""
        self._last_regime_prompt_signature = signature
        self._last_regime_prompt_at = timestamp or get_utc_timestamp()
        self._save_state()
    
    def record_analysis(
        self,
        analysis: Dict[str, Any],
        suggestions: Optional[List[Dict[str, Any]]] = None,
    ) -> List[str]:
        """
        Record an analysis result.
        
        Args:
            analysis: Analysis results from all analyzers
            suggestions: Optional list of generated suggestions

        Returns:
            List of created suggestion IDs (useful for linking Telegram buttons to new suggestions)
        """
        self._analysis_count += 1
        self._last_analysis = analysis
        created_suggestion_ids: List[str] = []
        
        # Write to observations file (append)
        observation = {
            "timestamp": get_utc_timestamp(),
            "analysis_id": self._analysis_count,
            "summary": self._summarize_analysis(analysis),
            "findings_count": self._count_findings(analysis),
            "suggestions_count": len(suggestions) if suggestions else 0,
        }
        
        try:
            with open(self.observations_file, "a") as f:
                f.write(json.dumps(observation) + "\n")
        except Exception as e:
            logger.error(f"Could not write observation: {e}")
        
        # Process suggestions
        if suggestions:
            for suggestion in suggestions:
                try:
                    sid = self.add_suggestion(suggestion)
                    created_suggestion_ids.append(sid)
                    # Mutate input dict so callers (monitor service / Telegram UI) can reference IDs
                    # without re-loading from disk. This is safe because suggestion dicts are ephemeral.
                    try:
                        suggestion["id"] = sid
                    except Exception:
                        pass
                except Exception:
                    continue
        
        self._save_state()
        return created_suggestion_ids
    
    def _summarize_analysis(self, analysis: Dict[str, Any]) -> Dict[str, str]:
        """Create a brief summary of analysis results."""
        summary = {}
        for dimension, result in analysis.items():
            if isinstance(result, dict):
                if "status" in result:
                    summary[dimension] = result["status"]
                elif "severity" in result:
                    summary[dimension] = result["severity"]
                else:
                    summary[dimension] = "analyzed"
            else:
                summary[dimension] = "completed"
        return summary
    
    def _count_findings(self, analysis: Dict[str, Any]) -> int:
        """Count total findings across all dimensions."""
        count = 0
        for dimension, result in analysis.items():
            if isinstance(result, dict) and "findings" in result:
                findings = result["findings"]
                if isinstance(findings, list):
                    count += len(findings)
                elif isinstance(findings, dict):
                    count += len(findings)
        return count
    
    def add_suggestion(self, suggestion: Dict[str, Any]) -> str:
        """
        Add a new suggestion.
        
        Args:
            suggestion: Suggestion data
            
        Returns:
            Suggestion ID
        """
        self._suggestion_count += 1
        suggestion_id = f"sug_{self._suggestion_count:06d}"
        
        suggestion_record = {
            "id": suggestion_id,
            "created_at": get_utc_timestamp(),
            "status": "pending",
            **suggestion,
        }
        
        self._active_suggestions[suggestion_id] = suggestion_record
        self._save_suggestions()
        
        logger.info(f"Added suggestion {suggestion_id}: {suggestion.get('title', 'untitled')}")
        return suggestion_id
    
    def _save_suggestions(self) -> None:
        """Save active suggestions to disk."""
        try:
            with open(self.suggestions_file, "w") as f:
                json.dump(self._active_suggestions, f, indent=2)
        except Exception as e:
            logger.error(f"Could not save suggestions: {e}")
    
    def get_suggestion(self, suggestion_id: str) -> Optional[Dict[str, Any]]:
        """Get a suggestion by ID."""
        return self._active_suggestions.get(suggestion_id)
    
    def get_active_suggestions(self) -> List[Dict[str, Any]]:
        """Get all pending suggestions."""
        return [
            s for s in self._active_suggestions.values()
            if s.get("status") == "pending"
        ]
    
    def update_suggestion_status(
        self,
        suggestion_id: str,
        status: str,
        result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update a suggestion's status.
        
        Args:
            suggestion_id: Suggestion ID
            status: New status (pending, applied, dismissed, failed)
            result: Optional result data
            
        Returns:
            True if updated successfully
        """
        if suggestion_id not in self._active_suggestions:
            return False
        
        suggestion = self._active_suggestions[suggestion_id]
        suggestion["status"] = status
        suggestion["updated_at"] = get_utc_timestamp()
        
        if result:
            suggestion["result"] = result
        
        if status == "applied":
            self._applied_count += 1
            self._record_applied_change(suggestion)
            # Remove from active suggestions
            del self._active_suggestions[suggestion_id]
        elif status in ("dismissed", "failed"):
            # Keep for history but mark as inactive
            pass
        
        self._save_suggestions()
        self._save_state()
        
        return True
    
    def _record_applied_change(self, suggestion: Dict[str, Any]) -> None:
        """Record an applied change to the audit log."""
        change_record = {
            "timestamp": get_utc_timestamp(),
            "suggestion_id": suggestion.get("id"),
            "type": suggestion.get("type"),
            "title": suggestion.get("title"),
            "description": suggestion.get("description"),
            "changes": suggestion.get("changes"),
            "result": suggestion.get("result"),
        }
        
        try:
            with open(self.changes_file, "a") as f:
                f.write(json.dumps(change_record) + "\n")
        except Exception as e:
            logger.error(f"Could not record applied change: {e}")
    
    def record_alert(self, alert: Dict[str, Any]) -> None:
        """Record that an alert was sent."""
        self._alert_count += 1
        self._save_state()
    
    def get_recent_observations(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get recent observations.
        
        Args:
            limit: Maximum number to return
            
        Returns:
            List of recent observations (newest first)
        """
        observations = []
        try:
            if self.observations_file.exists():
                with open(self.observations_file, "r") as f:
                    for line in f:
                        if line.strip():
                            observations.append(json.loads(line))
                # Return newest first
                return observations[-limit:][::-1]
        except Exception as e:
            logger.error(f"Could not read observations: {e}")
        return []
    
    def get_applied_changes(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get recent applied changes.
        
        Args:
            limit: Maximum number to return
            
        Returns:
            List of applied changes (newest first)
        """
        changes = []
        try:
            if self.changes_file.exists():
                with open(self.changes_file, "r") as f:
                    for line in f:
                        if line.strip():
                            changes.append(json.loads(line))
                return changes[-limit:][::-1]
        except Exception as e:
            logger.error(f"Could not read applied changes: {e}")
        return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get monitor statistics."""
        return {
            "analysis_count": self._analysis_count,
            "alert_count": self._alert_count,
            "suggestion_count": self._suggestion_count,
            "applied_count": self._applied_count,
            "active_suggestions": len([
                s for s in self._active_suggestions.values()
                if s.get("status") == "pending"
            ]),
            "last_analysis": self._last_analysis is not None,
        }
    
    def get_last_analysis(self) -> Optional[Dict[str, Any]]:
        """Get the most recent analysis results."""
        return self._last_analysis
    
    def clear_old_observations(self, days: int = 30) -> int:
        """
        Clear observations older than specified days.
        
        Args:
            days: Keep observations from last N days
            
        Returns:
            Number of observations removed
        """
        cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
        
        try:
            if not self.observations_file.exists():
                return 0
            
            kept = []
            removed = 0
            
            with open(self.observations_file, "r") as f:
                for line in f:
                    if line.strip():
                        obs = json.loads(line)
                        ts = obs.get("timestamp", "")
                        try:
                            obs_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                            if obs_time.timestamp() >= cutoff:
                                kept.append(line)
                            else:
                                removed += 1
                        except (ValueError, AttributeError):
                            kept.append(line)  # Keep if we can't parse
            
            if removed > 0:
                with open(self.observations_file, "w") as f:
                    f.writelines(kept)
                logger.info(f"Cleared {removed} old observations")
            
            return removed
            
        except Exception as e:
            logger.error(f"Could not clear old observations: {e}")
            return 0




