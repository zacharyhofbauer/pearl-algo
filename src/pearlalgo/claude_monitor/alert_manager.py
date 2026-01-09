"""
Alert Manager - Intelligent alert routing and deduplication for Claude monitor.

Handles alert generation, prioritization, deduplication, and delivery
with support for quiet hours and escalation logic.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from pearlalgo.utils.logger import logger
from pearlalgo.utils.paths import get_utc_timestamp

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore


class AlertLevel(Enum):
    """Alert severity levels."""
    CRITICAL = "critical"  # Immediate action required
    WARNING = "warning"    # Degradation detected
    INFO = "info"          # Opportunity identified
    SUCCESS = "success"    # Improvement confirmed
    
    @property
    def emoji(self) -> str:
        """Get emoji for alert level."""
        return {
            AlertLevel.CRITICAL: "🔴",
            AlertLevel.WARNING: "🟡",
            AlertLevel.INFO: "🔵",
            AlertLevel.SUCCESS: "🟢",
        }[self]
    
    @property
    def priority(self) -> int:
        """Get priority (higher = more urgent)."""
        return {
            AlertLevel.CRITICAL: 4,
            AlertLevel.WARNING: 3,
            AlertLevel.INFO: 2,
            AlertLevel.SUCCESS: 1,
        }[self]


@dataclass
class Alert:
    """Represents an alert to be sent."""
    level: AlertLevel
    title: str
    message: str
    category: str  # signals, system, market, code
    source: str    # analyzer that generated it
    timestamp: str = field(default_factory=get_utc_timestamp)
    data: Optional[Dict[str, Any]] = None
    suggestion_id: Optional[str] = None  # Link to suggestion if applicable
    escalated: bool = False
    
    @property
    def fingerprint(self) -> str:
        """Generate a fingerprint for deduplication."""
        # Intentionally exclude alert level so WARNING->CRITICAL upgrades don't bypass dedup.
        # Category+title is stable and prevents spam when severity fluctuates.
        content = f"{self.category}:{self.title}"
        return hashlib.md5(content.encode()).hexdigest()[:12]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "category": self.category,
            "source": self.source,
            "timestamp": self.timestamp,
            "data": self.data,
            "suggestion_id": self.suggestion_id,
            "escalated": self.escalated,
            "fingerprint": self.fingerprint,
        }
    
    def format_telegram(self, include_metadata: bool = True) -> str:
        """Format alert for Telegram message."""
        header = f"{self.level.emoji} *{self.title}*"
        
        lines = [header, ""]
        
        if self.message:
            lines.append(self.message)
            lines.append("")
        
        if self.escalated:
            lines.append("⚠️ _Escalated from previous warning_")
            lines.append("")
        
        if include_metadata:
        lines.append(f"📁 Category: {self.category}")
        lines.append(f"🔍 Source: {self.source}")
        
        if self.suggestion_id:
            lines.append("")
            lines.append(f"💡 Suggestion available: `{self.suggestion_id}`")
        
        return "\n".join(lines)


class AlertManager:
    """
    Manages alert generation, deduplication, and delivery.
    
    Features:
    - Smart deduplication (similar alerts within time window)
    - Quiet hours support
    - Escalation logic (warning -> critical)
    - Alert correlation (group related issues)
    - Rate limiting
    """
    
    def __init__(
        self,
        dedup_window_seconds: int = 900,  # 15 minutes
        quiet_start: Optional[str] = None,  # "22:00"
        quiet_end: Optional[str] = None,    # "07:00"
        timezone_name: Optional[str] = None,
        suppress_info_during_quiet: bool = True,
        max_alerts_per_hour: int = 20,
        escalation_threshold: int = 3,  # Warnings before escalation
        allowed_levels: Optional[List[str]] = None,
        allowed_categories: Optional[List[str]] = None,
    ):
        """
        Initialize alert manager.
        
        Args:
            dedup_window_seconds: Time window for deduplication
            quiet_start: Quiet hours start time (HH:MM)
            quiet_end: Quiet hours end time (HH:MM)
            suppress_info_during_quiet: Suppress INFO alerts during quiet hours
            max_alerts_per_hour: Maximum alerts per hour (rate limit)
            escalation_threshold: Number of warnings before escalation
        """
        self.dedup_window = timedelta(seconds=dedup_window_seconds)
        self.quiet_start = quiet_start
        self.quiet_end = quiet_end
        self.timezone_name = str(timezone_name or "UTC")
        self._tzinfo = timezone.utc
        if ZoneInfo is not None:
            try:
                self._tzinfo = ZoneInfo(self.timezone_name)
            except Exception:
                logger.warning(f"Invalid timezone for AlertManager: {self.timezone_name}; falling back to UTC")
                self.timezone_name = "UTC"
                self._tzinfo = timezone.utc
        self.suppress_info_during_quiet = suppress_info_during_quiet
        self.max_alerts_per_hour = max_alerts_per_hour
        self.escalation_threshold = escalation_threshold
        self.allowed_levels: Optional[Set[str]] = None
        self.allowed_categories: Optional[Set[str]] = None
        try:
            if isinstance(allowed_levels, list) and allowed_levels:
                self.allowed_levels = {str(x).lower() for x in allowed_levels if x is not None}
        except Exception:
            self.allowed_levels = None
        try:
            if isinstance(allowed_categories, list) and allowed_categories:
                self.allowed_categories = {str(x).lower() for x in allowed_categories if x is not None}
        except Exception:
            self.allowed_categories = None
        
        # State tracking
        self._recent_alerts: Dict[str, datetime] = {}  # fingerprint -> last sent
        self._recent_levels: Dict[str, str] = {}        # fingerprint -> last sent level
        self._warning_counts: Dict[str, int] = {}       # deprecated (kept for backward compat)
        self._hourly_count = 0
        self._hourly_reset: Optional[datetime] = None
        
        # Suppressed fingerprints (manually suppressed)
        self._suppressed: Set[str] = set()
    
    def process_analysis(
        self,
        analysis: Dict[str, Any],
    ) -> List[Alert]:
        """
        Process analysis results and generate alerts.
        
        Args:
            analysis: Analysis results from all dimensions
            
        Returns:
            List of alerts to send
        """
        raw_alerts = []
        
        # Extract alerts from each analysis dimension
        for dimension, result in analysis.items():
            if not isinstance(result, dict):
                continue
            
            # Check for alerts in result
            if "alerts" in result:
                for alert_data in result["alerts"]:
                    alert = self._create_alert(alert_data, dimension)
                    if alert:
                        raw_alerts.append(alert)
            
            # Check for findings that should generate alerts
            if "findings" in result:
                for finding in result.get("findings", []):
                    alert = self._finding_to_alert(finding, dimension)
                    if alert:
                        raw_alerts.append(alert)
        
        # Filter and deduplicate
        filtered_alerts = self._filter_alerts(raw_alerts)
        
        return filtered_alerts
    
    def _create_alert(
        self,
        alert_data: Dict[str, Any],
        source: str,
    ) -> Optional[Alert]:
        """Create an Alert from raw data."""
        try:
            level = AlertLevel(alert_data.get("level", "info"))
            return Alert(
                level=level,
                title=alert_data.get("title", "Alert"),
                message=alert_data.get("message", ""),
                category=alert_data.get("category", source),
                source=source,
                data=alert_data.get("data"),
                suggestion_id=alert_data.get("suggestion_id"),
            )
        except Exception as e:
            logger.warning(f"Could not create alert: {e}")
            return None
    
    def _finding_to_alert(
        self,
        finding: Dict[str, Any],
        source: str,
    ) -> Optional[Alert]:
        """Convert a finding to an alert if it meets threshold."""
        severity = finding.get("severity", "info")
        
        # Map severity to alert level
        level_map = {
            "critical": AlertLevel.CRITICAL,
            "high": AlertLevel.WARNING,
            "medium": AlertLevel.INFO,
            "low": AlertLevel.INFO,
            "info": AlertLevel.INFO,
        }
        
        level = level_map.get(severity, AlertLevel.INFO)
        
        # Only create alerts for medium+ severity
        if severity in ("low",):
            return None
        
        return Alert(
            level=level,
            title=finding.get("title", finding.get("type", "Finding")),
            message=finding.get("description", finding.get("message", "")),
            category=finding.get("category", source),
            source=source,
            data=finding.get("data"),
            suggestion_id=finding.get("suggestion_id"),
        )
    
    def _filter_alerts(self, alerts: List[Alert]) -> List[Alert]:
        """Filter alerts based on deduplication, quiet hours, and rate limits."""
        now = datetime.now(timezone.utc)
        filtered = []
        
        # Reset hourly counter if needed
        if self._hourly_reset is None or (now - self._hourly_reset) > timedelta(hours=1):
            self._hourly_count = 0
            self._hourly_reset = now
        
        # Clean up old dedup entries
        cutoff = now - self.dedup_window
        self._recent_alerts = {
            fp: ts for fp, ts in self._recent_alerts.items()
            if ts > cutoff
        }
        # Keep recent level map in sync with dedup map.
        self._recent_levels = {fp: lvl for fp, lvl in self._recent_levels.items() if fp in self._recent_alerts}
        
        for alert in alerts:
            # Category/level allowlists (if configured)
            if self.allowed_categories is not None:
                if str(alert.category or "").lower() not in self.allowed_categories:
                    continue
            if self.allowed_levels is not None:
                if str(alert.level.value).lower() not in self.allowed_levels:
                    continue

            # Check suppression
            if alert.fingerprint in self._suppressed:
                logger.debug(f"Alert suppressed: {alert.title}")
                continue
            
            # Check quiet hours
            if self._is_quiet_hours(now) and self.suppress_info_during_quiet:
                if alert.level == AlertLevel.INFO:
                    logger.debug(f"Alert suppressed during quiet hours: {alert.title}")
                    continue
            
            # Check deduplication
            if alert.fingerprint in self._recent_alerts:
                # Allow a one-time severity upgrade within the dedup window (e.g. WARNING -> CRITICAL),
                # but otherwise suppress repeats to avoid spam.
                last_level_val = self._recent_levels.get(alert.fingerprint)
                if last_level_val:
                    try:
                        last_level = AlertLevel(last_level_val)
                    except Exception:
                        last_level = None
                    if last_level and alert.level.priority > last_level.priority:
                        alert.escalated = True
                    else:
                        logger.debug(f"Alert deduplicated: {alert.title}")
                        continue
                else:
                    logger.debug(f"Alert deduplicated: {alert.title}")
                    continue
            
            # Check rate limit
            if self._hourly_count >= self.max_alerts_per_hour:
                # Always allow critical alerts
                if alert.level != AlertLevel.CRITICAL:
                    logger.warning(f"Alert rate limited: {alert.title}")
                    continue
            
            # Alert passes all filters
            filtered.append(alert)
            self._recent_alerts[alert.fingerprint] = now
            self._recent_levels[alert.fingerprint] = alert.level.value
            self._hourly_count += 1
        
        # Sort by priority (most urgent first)
        filtered.sort(key=lambda a: a.level.priority, reverse=True)
        
        return filtered
    
    def _is_quiet_hours(self, now: datetime) -> bool:
        """Check if current time is within quiet hours."""
        if not self.quiet_start or not self.quiet_end:
            return False
        
        try:
            # Parse times
            start_h, start_m = map(int, self.quiet_start.split(":"))
            end_h, end_m = map(int, self.quiet_end.split(":"))
            
            try:
                local_now = now.astimezone(self._tzinfo)
            except Exception:
                local_now = now
            current = local_now.hour * 60 + local_now.minute
            start = start_h * 60 + start_m
            end = end_h * 60 + end_m
            
            if start <= end:
                # Same day (e.g., 09:00 - 17:00)
                return start <= current < end
            else:
                # Overnight (e.g., 22:00 - 07:00)
                return current >= start or current < end
                
        except Exception:
            return False
    
    def suppress_fingerprint(self, fingerprint: str) -> None:
        """Manually suppress alerts with given fingerprint."""
        self._suppressed.add(fingerprint)
        logger.info(f"Suppressed alert fingerprint: {fingerprint}")
    
    def unsuppress_fingerprint(self, fingerprint: str) -> None:
        """Remove suppression for fingerprint."""
        self._suppressed.discard(fingerprint)
        logger.info(f"Unsuppressed alert fingerprint: {fingerprint}")
    
    def clear_suppressions(self) -> None:
        """Clear all manual suppressions."""
        self._suppressed.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get alert manager statistics."""
        return {
            "hourly_count": self._hourly_count,
            "max_per_hour": self.max_alerts_per_hour,
            "active_dedup_entries": len(self._recent_alerts),
            "suppressed_count": len(self._suppressed),
            "warning_counts": dict(self._warning_counts),  # deprecated
            "allowed_levels": sorted(self.allowed_levels) if self.allowed_levels else None,
            "allowed_categories": sorted(self.allowed_categories) if self.allowed_categories else None,
            "timezone": self.timezone_name,
        }
    
    def create_alert(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        category: str,
        source: str,
        data: Optional[Dict[str, Any]] = None,
        suggestion_id: Optional[str] = None,
    ) -> Alert:
        """
        Create a new alert directly.
        
        Args:
            level: Alert severity level
            title: Alert title
            message: Alert message/description
            category: Category (signals, system, market, code)
            source: Source analyzer
            data: Optional additional data
            suggestion_id: Optional linked suggestion
            
        Returns:
            New Alert instance
        """
        return Alert(
            level=level,
            title=title,
            message=message,
            category=category,
            source=source,
            data=data,
            suggestion_id=suggestion_id,
        )
    
    def should_send(self, alert: Alert) -> bool:
        """
        Check if an alert should be sent (without recording it).
        
        Useful for preview checks.
        """
        now = datetime.now(timezone.utc)
        
        # Check suppression
        if alert.fingerprint in self._suppressed:
            return False
        
        # Check quiet hours
        if self._is_quiet_hours(now) and self.suppress_info_during_quiet:
            if alert.level == AlertLevel.INFO:
                return False
        
        # Check deduplication
        if alert.fingerprint in self._recent_alerts:
            if alert.level != AlertLevel.CRITICAL:
                return False
        
        return True




