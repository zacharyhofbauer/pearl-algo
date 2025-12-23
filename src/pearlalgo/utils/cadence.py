"""
Fixed-cadence scheduler helper.

Provides a deterministic, testable cadence scheduler that ensures cycles run
at fixed intervals (start-to-start) rather than sleep-after-work semantics.

Key features:
- Uses monotonic time to avoid wall-clock drift (NTP adjustments, DST)
- Handles missed cycles by skip-ahead (no catch-up storms)
- Tracks cadence metrics for observability
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Optional


@dataclass
class CadenceMetrics:
    """Cadence metrics for observability."""
    
    # Current cycle info
    cycle_started_at_utc: Optional[str] = None
    cycle_duration_ms: float = 0.0
    sleep_scheduled_ms: float = 0.0
    cadence_lag_ms: float = 0.0  # scheduled vs actual start
    
    # Rolling stats (last N cycles)
    duration_p50_ms: float = 0.0
    duration_p95_ms: float = 0.0
    missed_cycles: int = 0  # cycles skipped due to running behind
    
    def to_dict(self) -> dict:
        """Convert to dictionary for state persistence."""
        return {
            "cycle_started_at_utc": self.cycle_started_at_utc,
            "cycle_duration_ms": round(self.cycle_duration_ms, 1),
            "sleep_scheduled_ms": round(self.sleep_scheduled_ms, 1),
            "cadence_lag_ms": round(self.cadence_lag_ms, 1),
            "duration_p50_ms": round(self.duration_p50_ms, 1),
            "duration_p95_ms": round(self.duration_p95_ms, 1),
            "missed_cycles": self.missed_cycles,
        }
    
    def format_compact(self) -> str:
        """Format as compact string for Telegram dashboard."""
        lag_indicator = ""
        if self.cadence_lag_ms > 1000:
            lag_indicator = " ⚠️"
        elif self.cadence_lag_ms > 500:
            lag_indicator = " 🟡"
        
        missed_str = ""
        if self.missed_cycles > 0:
            missed_str = f" | {self.missed_cycles} skipped"
        
        return (
            f"{self.cycle_duration_ms:.0f}ms "
            f"(p50: {self.duration_p50_ms:.0f}ms, p95: {self.duration_p95_ms:.0f}ms)"
            f"{lag_indicator}{missed_str}"
        )


@dataclass
class CadenceScheduler:
    """
    Fixed-cadence scheduler for service loops.
    
    Ensures cycles start at fixed intervals (start-to-start) regardless of
    how long each cycle takes to execute.
    
    Example usage:
        scheduler = CadenceScheduler(interval_seconds=30.0)
        scheduler.mark_cycle_start()
        # ... do work ...
        sleep_time = scheduler.mark_cycle_end()
        await asyncio.sleep(sleep_time)
    """
    
    interval_seconds: float
    max_history: int = 100
    
    # Internal state
    _next_scheduled: Optional[float] = field(default=None, repr=False)
    _cycle_start: Optional[float] = field(default=None, repr=False)
    _cycle_start_utc: Optional[datetime] = field(default=None, repr=False)
    _duration_history: Deque[float] = field(default_factory=lambda: deque(maxlen=100), repr=False)
    _total_missed_cycles: int = field(default=0, repr=False)
    _last_metrics: CadenceMetrics = field(default_factory=CadenceMetrics, repr=False)
    
    def __post_init__(self) -> None:
        """Initialize with empty deque if not already set."""
        if not isinstance(self._duration_history, deque):
            self._duration_history = deque(maxlen=self.max_history)
    
    def mark_cycle_start(self) -> float:
        """
        Mark the start of a cycle.
        
        Returns:
            Cadence lag in milliseconds (how late this cycle started vs scheduled).
        """
        now_mono = time.monotonic()
        now_utc = datetime.now(timezone.utc)
        
        self._cycle_start = now_mono
        self._cycle_start_utc = now_utc
        
        # Calculate lag from scheduled time
        lag_ms = 0.0
        if self._next_scheduled is not None:
            lag_ms = max(0.0, (now_mono - self._next_scheduled) * 1000)
        
        self._last_metrics.cycle_started_at_utc = now_utc.isoformat()
        self._last_metrics.cadence_lag_ms = lag_ms
        
        return lag_ms
    
    def mark_cycle_end(self) -> float:
        """
        Mark the end of a cycle and compute sleep time.
        
        Returns:
            Seconds to sleep before next cycle (may be 0 if running behind).
        """
        now_mono = time.monotonic()
        
        # Calculate cycle duration
        if self._cycle_start is not None:
            duration_s = now_mono - self._cycle_start
            duration_ms = duration_s * 1000
        else:
            duration_s = 0.0
            duration_ms = 0.0
        
        # Track duration history
        self._duration_history.append(duration_ms)
        self._last_metrics.cycle_duration_ms = duration_ms
        
        # Compute percentiles
        if self._duration_history:
            sorted_durations = sorted(self._duration_history)
            n = len(sorted_durations)
            self._last_metrics.duration_p50_ms = sorted_durations[n // 2]
            self._last_metrics.duration_p95_ms = sorted_durations[int(n * 0.95)] if n > 1 else sorted_durations[0]
        
        # Calculate next scheduled time
        if self._next_scheduled is None:
            # First cycle: schedule next from now
            self._next_scheduled = now_mono + self.interval_seconds
            sleep_time = self.interval_seconds
        else:
            # Fixed cadence: next scheduled time is interval from last scheduled
            self._next_scheduled += self.interval_seconds
            
            # If we're behind schedule, skip ahead to avoid catch-up storms
            missed = 0
            while self._next_scheduled < now_mono:
                self._next_scheduled += self.interval_seconds
                missed += 1
            
            if missed > 0:
                self._total_missed_cycles += missed
                self._last_metrics.missed_cycles = self._total_missed_cycles
            
            sleep_time = max(0.0, self._next_scheduled - now_mono)
        
        self._last_metrics.sleep_scheduled_ms = sleep_time * 1000
        
        return sleep_time
    
    def get_metrics(self) -> CadenceMetrics:
        """Get current cadence metrics for observability."""
        return self._last_metrics
    
    def reset(self) -> None:
        """Reset scheduler state (e.g., on pause/resume)."""
        self._next_scheduled = None
        self._cycle_start = None
        self._cycle_start_utc = None
        # Keep history and missed count for observability


def compute_sleep_time_fixed_cadence(
    cycle_start_mono: float,
    interval_seconds: float,
    next_scheduled: Optional[float] = None,
) -> tuple[float, float, int]:
    """
    Pure function version for testing without scheduler state.
    
    Args:
        cycle_start_mono: Monotonic time when cycle started
        interval_seconds: Target interval in seconds
        next_scheduled: Previous scheduled time (None for first cycle)
    
    Returns:
        Tuple of (sleep_time, new_next_scheduled, missed_cycles)
    """
    now_mono = time.monotonic()
    
    if next_scheduled is None:
        # First cycle
        new_next = now_mono + interval_seconds
        return (interval_seconds, new_next, 0)
    
    # Fixed cadence
    new_next = next_scheduled + interval_seconds
    missed = 0
    
    while new_next < now_mono:
        new_next += interval_seconds
        missed += 1
    
    sleep_time = max(0.0, new_next - now_mono)
    return (sleep_time, new_next, missed)

