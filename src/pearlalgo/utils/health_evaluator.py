"""Shared health evaluation logic for agent monitoring.

Provides :class:`HealthEvaluator` – a single, canonical implementation
of the agent-state health checks used by ``scripts/monitoring/monitor.py``
and ``scripts/monitoring/serve_agent_status.py``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class HealthStatus(Enum):
    """Severity level of a health-check result."""

    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"
    ERROR = "error"


@dataclass
class HealthResult:
    """Container for the outcome of :meth:`HealthEvaluator.evaluate`."""

    status: HealthStatus
    message: str
    details: Dict[str, Any] = field(default_factory=dict)


class HealthEvaluator:
    """Evaluate agent health from *state.json*.

    Checks performed by :meth:`evaluate` / :meth:`evaluate_state`:

    * Is the agent running?
    * Is it paused (circuit-breaker)?
    * Is state data fresh (``last_updated``)?
    * Is cycle data fresh (``last_successful_cycle``)?
    * Are there too many consecutive errors?

    All thresholds are constructor parameters with conservative defaults.
    """

    def __init__(
        self,
        state_file: Path,
        stale_threshold_minutes: float = 5.0,
        cycle_stale_threshold_minutes: float = 10.0,
        max_consecutive_errors: int = 5,
    ) -> None:
        self.state_file = state_file
        self.stale_threshold_minutes = stale_threshold_minutes
        self.cycle_stale_threshold_minutes = cycle_stale_threshold_minutes
        self.max_consecutive_errors = max_consecutive_errors

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_timestamp(ts_str: str | None) -> Optional[datetime]:
        """Parse an ISO-8601 timestamp string to an aware *datetime*.

        Returns ``None`` when *ts_str* is falsy or cannot be parsed.
        """
        if not ts_str:
            return None
        try:
            ts_str = str(ts_str)
            if ts_str.endswith("Z"):
                ts_str = ts_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception:
            return None

    @staticmethod
    def load_state(state_file: Path) -> Dict[str, Any]:
        """Read ``state.json`` from *state_file*.

        On failure the returned dict contains an ``_error`` key describing
        the problem (``state_file_missing``, ``state_file_corrupt``, or
        ``state_file_read_error``).
        """
        if not state_file.exists():
            return {"_error": "state_file_missing", "_path": str(state_file)}
        try:
            return json.loads(state_file.read_text())
        except json.JSONDecodeError as e:
            return {"_error": "state_file_corrupt", "_detail": str(e)}
        except Exception as e:
            return {"_error": "state_file_read_error", "_detail": str(e)}

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def evaluate(self) -> HealthResult:
        """Load the configured state file and evaluate agent health."""
        state = self.load_state(self.state_file)
        return self.evaluate_state(state)

    def evaluate_state(self, state: Dict[str, Any]) -> HealthResult:
        """Evaluate agent health from a pre-loaded state *dict*.

        ``HealthResult.details`` always contains ``"timestamp"`` and
        ``"running"``.  When issues are found it also includes:

        * ``"issues"`` – list of compact identifiers (e.g.
          ``"state_stale"``, ``"agent_paused"``).
        * ``"issue_messages"`` – human-readable descriptions.
        """
        now = datetime.now(timezone.utc)
        details: Dict[str, Any] = {"timestamp": now.isoformat()}

        # -- State-file errors ------------------------------------------
        if "_error" in state:
            error_type = str(state.get("_error", "unknown"))
            details.update(
                {
                    "status": f"state_error:{error_type}",
                    "error": error_type,
                    "detail": state.get("_detail", ""),
                    "path": state.get("_path", ""),
                }
            )
            return HealthResult(
                status=HealthStatus.ERROR,
                message=f"State error: {error_type}",
                details=details,
            )

        running = bool(state.get("running", False))
        paused = bool(state.get("paused", False))
        pause_reason = state.get("pause_reason")
        futures_market_open = state.get("futures_market_open")
        strategy_session_open = state.get("strategy_session_open")
        data_fresh = state.get("data_fresh")
        consecutive_errors = int(state.get("consecutive_errors", 0) or 0)

        last_updated = self.parse_timestamp(state.get("last_updated"))
        last_successful_cycle = self.parse_timestamp(
            state.get("last_successful_cycle"),
        )

        details.update(
            {
                "running": running,
                "paused": paused,
                "pause_reason": pause_reason,
                "futures_market_open": futures_market_open,
                "strategy_session_open": strategy_session_open,
                "data_fresh": data_fresh,
                "consecutive_errors": consecutive_errors,
            }
        )

        # Agent intentionally stopped -> OK.
        if not running:
            details["status"] = "agent_stopped"
            return HealthResult(
                status=HealthStatus.OK,
                message="Agent not running",
                details=details,
            )

        issues: List[str] = []
        issue_messages: List[str] = []

        # 1. Paused (circuit breaker)
        if paused:
            reason = pause_reason or "unknown reason"
            issues.append("agent_paused")
            issue_messages.append(f"Agent paused: {reason}")

        # 2. State freshness (last_updated)
        if last_updated is None:
            issues.append("missing_last_updated")
            issue_messages.append("Missing last_updated timestamp")
        else:
            age_s = (now - last_updated).total_seconds()
            details["state_age_seconds"] = age_s
            if age_s > self.stale_threshold_minutes * 60:
                issues.append("state_stale")
                issue_messages.append(
                    f"State stale: last updated {age_s / 60:.1f}m ago",
                )

        # 3. Cycle freshness (last_successful_cycle)
        if last_successful_cycle is None:
            issues.append("missing_last_successful_cycle")
            issue_messages.append("Missing last_successful_cycle timestamp")
        else:
            age_s = (now - last_successful_cycle).total_seconds()
            details["cycle_age_seconds"] = age_s
            if age_s > self.cycle_stale_threshold_minutes * 60:
                issues.append("cycle_stale")
                issue_messages.append(
                    f"Cycle stale: last successful cycle {age_s / 60:.1f}m ago",
                )

        # Market-aware suppression
        if futures_market_open is False or strategy_session_open is False:
            _suppress_ids = {"cycle_stale"}
            issues = [i for i in issues if i not in _suppress_ids]
            issue_messages = [
                m for m in issue_messages if "cycle stale" not in m.lower()
            ]
        if futures_market_open is False:
            _suppress_ids = {"state_stale"}
            issues = [i for i in issues if i not in _suppress_ids]
            issue_messages = [
                m for m in issue_messages if "state stale" not in m.lower()
            ]

        # 4. Data freshness while market open
        if futures_market_open is True and data_fresh is False:
            issues.append("data_stale")
            issue_messages.append("Data stale while market is open")

        # 5. Consecutive errors
        if consecutive_errors >= self.max_consecutive_errors:
            issues.append("consecutive_errors")
            issue_messages.append(
                f"High error count: {consecutive_errors} consecutive errors",
            )

        if not issues:
            details["status"] = "healthy"
            return HealthResult(
                status=HealthStatus.OK,
                message="All checks passed",
                details=details,
            )

        details["issues"] = issues
        details["issue_messages"] = issue_messages

        # Severity: anything stale / paused / data-stale -> critical.
        critical_ids = {"state_stale", "cycle_stale", "agent_paused", "data_stale"}
        is_critical = bool(critical_ids & set(issues))

        if is_critical:
            details["status"] = "critical"
            return HealthResult(
                status=HealthStatus.CRITICAL,
                message=f"Critical: {len(issues)} issue(s) detected",
                details=details,
            )

        details["status"] = "warning"
        return HealthResult(
            status=HealthStatus.WARNING,
            message=f"Warning: {len(issues)} issue(s) detected",
            details=details,
        )
