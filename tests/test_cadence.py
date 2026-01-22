"""
Tests for the fixed-cadence scheduler.

Validates:
- Fixed-cadence timing (start-to-start)
- Skip-ahead behavior when running behind
- Metrics tracking
- Integration with service loop
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch

import pytest

from pearlalgo.utils.cadence import (
    CadenceMetrics,
    CadenceScheduler,
    compute_sleep_time_fixed_cadence,
)


class TestCadenceMetrics:
    """Tests for CadenceMetrics dataclass."""

    def test_to_dict_returns_all_fields(self) -> None:
        metrics = CadenceMetrics(
            cycle_started_at_utc="2025-12-23T10:00:00+00:00",
            cycle_duration_ms=150.5,
            sleep_scheduled_ms=29849.5,
            cadence_lag_ms=50.0,
            duration_p50_ms=140.0,
            duration_p95_ms=200.0,
            missed_cycles=2,
        )
        d = metrics.to_dict()
        assert d["cycle_started_at_utc"] == "2025-12-23T10:00:00+00:00"
        assert d["cycle_duration_ms"] == 150.5
        assert d["sleep_scheduled_ms"] == 29849.5
        assert d["cadence_lag_ms"] == 50.0
        assert d["duration_p50_ms"] == 140.0
        assert d["duration_p95_ms"] == 200.0
        assert d["missed_cycles"] == 2

    def test_format_compact_normal(self) -> None:
        metrics = CadenceMetrics(
            cycle_duration_ms=150.0,
            duration_p50_ms=140.0,
            duration_p95_ms=200.0,
            cadence_lag_ms=100.0,
            missed_cycles=0,
        )
        s = metrics.format_compact()
        assert "150ms" in s
        assert "p50: 140ms" in s
        assert "p95: 200ms" in s
        assert "⚠️" not in s  # No warning for <500ms lag

    def test_format_compact_lag_warning(self) -> None:
        metrics = CadenceMetrics(
            cycle_duration_ms=150.0,
            duration_p50_ms=140.0,
            duration_p95_ms=200.0,
            cadence_lag_ms=600.0,  # >500ms triggers yellow
            missed_cycles=0,
        )
        s = metrics.format_compact()
        assert "🟡" in s

    def test_format_compact_lag_critical(self) -> None:
        metrics = CadenceMetrics(
            cycle_duration_ms=150.0,
            duration_p50_ms=140.0,
            duration_p95_ms=200.0,
            cadence_lag_ms=1500.0,  # >1000ms triggers warning
            missed_cycles=0,
        )
        s = metrics.format_compact()
        assert "⚠️" in s

    def test_format_compact_missed_cycles(self) -> None:
        metrics = CadenceMetrics(
            cycle_duration_ms=150.0,
            duration_p50_ms=140.0,
            duration_p95_ms=200.0,
            cadence_lag_ms=100.0,
            missed_cycles=5,
        )
        s = metrics.format_compact()
        assert "5 skipped" in s


class TestCadenceScheduler:
    """Tests for CadenceScheduler class."""

    def test_first_cycle_sleeps_full_interval(self) -> None:
        """First cycle should sleep for the full interval."""
        scheduler = CadenceScheduler(interval_seconds=30.0)
        
        scheduler.mark_cycle_start()
        sleep_time = scheduler.mark_cycle_end()
        
        # First cycle should sleep approximately the full interval
        assert 29.5 <= sleep_time <= 30.5

    def test_fixed_cadence_accounts_for_work_time(self) -> None:
        """Sleep time should be reduced by the work duration."""
        scheduler = CadenceScheduler(interval_seconds=30.0)
        
        scheduler.mark_cycle_start()
        # Simulate work taking some time
        time.sleep(0.1)  # 100ms of work
        sleep_time = scheduler.mark_cycle_end()
        
        # Sleep should be roughly interval minus work time
        # Allow for some timing variance
        assert 29.3 <= sleep_time <= 30.0

    def test_skip_ahead_when_behind_schedule(self) -> None:
        """Should skip cycles when running behind to avoid catch-up storms."""
        scheduler = CadenceScheduler(interval_seconds=1.0)
        
        # First cycle
        scheduler.mark_cycle_start()
        scheduler.mark_cycle_end()
        
        # Simulate being 3.5 seconds behind schedule
        # After mark_cycle_end, _next_scheduled is ~1s in the future
        # Setting it 3.5s back puts us 2.5s behind (need to skip forward 3x)
        scheduler._next_scheduled -= 3.5
        
        scheduler.mark_cycle_start()
        sleep_time = scheduler.mark_cycle_end()
        
        # After decrementing by 3.5s:
        # - _next_scheduled is now ~2.5s in the past
        # - mark_cycle_end adds 1.0s -> ~1.5s in past, skip 1
        # - adds another 1.0s -> ~0.5s in past, skip 2  
        # - adds another 1.0s -> ~0.5s in future, stop
        # So we skip 2 cycles (accounting for timing variance)
        metrics = scheduler.get_metrics()
        assert metrics.missed_cycles >= 2
        # Sleep time should be positive (scheduled for future)
        assert sleep_time >= 0

    def test_metrics_track_duration_history(self) -> None:
        """Duration history should track cycle durations."""
        scheduler = CadenceScheduler(interval_seconds=0.1)
        
        for _ in range(5):
            scheduler.mark_cycle_start()
            time.sleep(0.01)  # 10ms work
            scheduler.mark_cycle_end()
            time.sleep(0.05)  # Shorter sleep for faster test
        
        metrics = scheduler.get_metrics()
        # Should have recorded durations
        assert metrics.duration_p50_ms > 0
        assert metrics.duration_p95_ms >= metrics.duration_p50_ms

    def test_reset_clears_scheduled_time(self) -> None:
        """Reset should clear the next scheduled time."""
        scheduler = CadenceScheduler(interval_seconds=30.0)
        
        scheduler.mark_cycle_start()
        scheduler.mark_cycle_end()
        
        assert scheduler._next_scheduled is not None
        
        scheduler.reset()
        
        assert scheduler._next_scheduled is None

    def test_cadence_lag_calculated_correctly(self) -> None:
        """Cadence lag should measure delay from scheduled start."""
        scheduler = CadenceScheduler(interval_seconds=0.1)  # 100ms interval
        
        # First cycle establishes schedule
        scheduler.mark_cycle_start()
        scheduler.mark_cycle_end()
        
        # Sleep longer than the interval to be late
        time.sleep(0.15)  # 150ms, should be ~50ms late
        lag = scheduler.mark_cycle_start()
        
        # Lag should be approximately 50ms (150ms sleep - 100ms interval)
        # Allow for timing variance
        assert lag >= 40, f"Expected lag >= 40ms, got {lag}ms"

    def test_set_interval_changes_interval(self) -> None:
        """set_interval should change the interval for future cycles."""
        scheduler = CadenceScheduler(interval_seconds=30.0)
        
        # Run one cycle to establish schedule
        scheduler.mark_cycle_start()
        scheduler.mark_cycle_end()
        
        # Change interval
        scheduler.set_interval(5.0)
        
        assert scheduler.interval_seconds == 5.0
        # Schedule should be reset to avoid catch-up storms
        assert scheduler._next_scheduled is None

    def test_set_interval_no_change_when_same(self) -> None:
        """set_interval should not reset if interval is unchanged."""
        scheduler = CadenceScheduler(interval_seconds=30.0)
        
        # Run one cycle to establish schedule
        scheduler.mark_cycle_start()
        scheduler.mark_cycle_end()
        
        original_scheduled = scheduler._next_scheduled
        
        # Set same interval
        scheduler.set_interval(30.0)
        
        # Schedule should NOT be reset
        assert scheduler._next_scheduled == original_scheduled

    def test_set_interval_rejects_invalid(self) -> None:
        """set_interval should reject non-positive intervals."""
        scheduler = CadenceScheduler(interval_seconds=30.0)
        
        with pytest.raises(ValueError):
            scheduler.set_interval(0.0)
        
        with pytest.raises(ValueError):
            scheduler.set_interval(-5.0)

    def test_set_interval_preserves_history(self) -> None:
        """set_interval should preserve duration history and missed_cycles count."""
        scheduler = CadenceScheduler(interval_seconds=0.1)
        
        # Run some cycles to build history
        for _ in range(5):
            scheduler.mark_cycle_start()
            time.sleep(0.01)
            scheduler.mark_cycle_end()
            time.sleep(0.05)
        
        metrics_before = scheduler.get_metrics()
        history_size_before = len(scheduler._duration_history)
        missed_before = scheduler._total_missed_cycles
        
        # Change interval
        scheduler.set_interval(5.0)
        
        # History should be preserved
        assert len(scheduler._duration_history) == history_size_before
        assert scheduler._total_missed_cycles == missed_before

    def test_set_interval_no_catchup_storm(self) -> None:
        """Changing interval should not cause catch-up storms from old timing."""
        scheduler = CadenceScheduler(interval_seconds=1.0)
        
        # Run one cycle
        scheduler.mark_cycle_start()
        scheduler.mark_cycle_end()
        
        # Simulate being behind by manipulating schedule
        scheduler._next_scheduled -= 5.0  # 5 seconds behind
        
        # Change interval (should reset schedule)
        scheduler.set_interval(0.5)
        
        # Next cycle should not report missed cycles from old timing
        scheduler.mark_cycle_start()
        sleep_time = scheduler.mark_cycle_end()
        
        # Sleep time should be approximately the new interval (not trying to catch up)
        assert 0.4 <= sleep_time <= 0.6


class TestComputeSleepTimeFixedCadence:
    """Tests for the pure function version."""

    def test_first_cycle_returns_full_interval(self) -> None:
        """First cycle (next_scheduled=None) should return full interval."""
        cycle_start = time.monotonic()
        sleep_time, next_sched, missed = compute_sleep_time_fixed_cadence(
            cycle_start_mono=cycle_start,
            interval_seconds=30.0,
            next_scheduled=None,
        )
        
        assert abs(sleep_time - 30.0) < 0.1
        assert missed == 0

    def test_skip_ahead_logic(self) -> None:
        """Should skip cycles when running significantly behind."""
        now = time.monotonic()
        # Pretend we were scheduled 5.5 intervals ago
        old_scheduled = now - 5.5 * 10.0  # 5.5 * 10s interval
        
        sleep_time, next_sched, missed = compute_sleep_time_fixed_cadence(
            cycle_start_mono=now - 0.1,  # Just started
            interval_seconds=10.0,
            next_scheduled=old_scheduled,
        )
        
        # Should skip 5 cycles (covers 0-5 intervals behind)
        assert missed == 5
        # Next scheduled should be in the future
        assert next_sched > now


@pytest.mark.asyncio
async def test_cadence_scheduler_integration_drift_bounded() -> None:
    """
    Integration test: verify cadence drift stays bounded over multiple cycles.
    
    This test runs a simulated service loop with variable work times
    and verifies that the overall timing stays close to target cadence.
    """
    scheduler = CadenceScheduler(interval_seconds=0.1)  # 100ms interval
    
    start_time = time.monotonic()
    cycle_count = 10
    
    for i in range(cycle_count):
        scheduler.mark_cycle_start()
        # Variable work time (10-30ms)
        work_time = 0.01 + (i % 3) * 0.01
        await asyncio.sleep(work_time)
        sleep_time = scheduler.mark_cycle_end()
        await asyncio.sleep(sleep_time)
    
    elapsed = time.monotonic() - start_time
    expected_elapsed = cycle_count * 0.1
    
    # Total elapsed should be close to expected (within 20% tolerance for test stability)
    drift_ratio = abs(elapsed - expected_elapsed) / expected_elapsed
    assert drift_ratio < 0.20, f"Drift too high: {drift_ratio:.2%}, elapsed={elapsed:.3f}s, expected={expected_elapsed:.3f}s"
    
    # Should not have missed any cycles in this controlled test
    metrics = scheduler.get_metrics()
    assert metrics.missed_cycles == 0


@pytest.mark.asyncio
async def test_service_loop_with_cadence_scheduler(tmp_path) -> None:
    """
    Integration test with the actual MarketAgentService using cadence scheduler.
    
    Verifies that the service integrates with the cadence scheduler correctly.
    """
    from pearlalgo.market_agent.service import MarketAgentService
    from pearlalgo.strategies.trading_bots.pearl_bot_auto import CONFIG as PEARL_BOT_CONFIG
    from tests.mock_data_provider import MockDataProvider
    
    # Create mock provider
    provider = MockDataProvider(base_price=17500.0, volatility=50.0)
    
    # Create config with short scan interval
    config = PEARL_BOT_CONFIG.copy()
    config.scan_interval = 0.1  # 100ms for fast test
    
    # Create service with fixed cadence mode
    with patch("pearlalgo.market_agent.service.load_service_config") as mock_config:
        mock_config.return_value = {
            "service": {
                "status_update_interval": 3600,  # Don't send dashboards during test
                "heartbeat_interval": 3600,
                "state_save_interval": 100,
                "cadence_mode": "fixed",
            },
            "circuit_breaker": {
                "max_consecutive_errors": 10,
                "max_connection_failures": 10,
                "max_data_fetch_errors": 5,
            },
            "data": {
                "stale_data_threshold_minutes": 10,
                "connection_timeout_minutes": 30,
                "buffer_size": 100,
            },
        }
        
        service = MarketAgentService(
            data_provider=provider,
            config=config,
            state_dir=tmp_path,
        )
    
    # Verify cadence scheduler is initialized
    assert service.cadence_mode == "fixed"
    assert service.cadence_scheduler is not None
    
    # Run service briefly
    task = asyncio.create_task(service.start())
    await asyncio.sleep(0.5)  # Run for ~5 cycles
    await service.stop("test")
    await asyncio.wait_for(task, timeout=2.0)
    
    # Verify metrics were tracked
    metrics = service.cadence_scheduler.get_metrics()
    assert metrics.cycle_duration_ms > 0
    
    # Verify status includes cadence info
    status = service.get_status()
    assert status["cadence_mode"] == "fixed"
    assert status["cadence_metrics"] is not None

