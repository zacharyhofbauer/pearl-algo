#!/usr/bin/env python3
"""
Soak Test for NQ Agent Service with Mock Provider

Runs the NQ Agent service loop for a bounded duration with mock data
and monitors resource usage (memory, CPU) and cadence metrics.

This is NOT a live/paper test - it uses synthetic data.

Usage:
    python3 scripts/testing/soak_test_mock_service.py [--duration SECONDS] [--verbose]

Default duration: 300 seconds (5 minutes)
"""

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def get_memory_usage_mb() -> float:
    """Get current process memory usage in MB using /proc/self/statm."""
    try:
        with open('/proc/self/statm', 'r') as f:
            # statm format: size resident share text lib data dt
            # All values are in pages (typically 4KB)
            parts = f.read().split()
            resident_pages = int(parts[1])
            page_size_kb = os.sysconf('SC_PAGE_SIZE') / 1024
            return (resident_pages * page_size_kb) / 1024  # Convert to MB
    except Exception:
        # Fallback for non-Linux systems
        try:
            import resource
            usage = resource.getrusage(resource.RUSAGE_SELF)
            return usage.ru_maxrss / 1024  # Convert to MB (on Linux, maxrss is in KB)
        except Exception:
            return -1.0


def format_duration(seconds: float) -> str:
    """Format duration in human-readable format."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    elif seconds < 3600:
        return f"{seconds/60:.1f}m"
    else:
        return f"{seconds/3600:.1f}h"


class SoakTestMonitor:
    """Monitor for soak test metrics."""
    
    def __init__(self):
        self.start_time = time.time()
        self.samples: List[Dict] = []
        self.initial_memory_mb = get_memory_usage_mb()
        
    def sample(self, service_status: Dict) -> Dict:
        """Take a sample of current metrics."""
        now = time.time()
        elapsed = now - self.start_time
        
        sample = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": elapsed,
            "memory_mb": get_memory_usage_mb(),
            "cycle_count": service_status.get("cycle_count", 0),
            "signal_count": service_status.get("signal_count", 0),
            "error_count": service_status.get("error_count", 0),
            "buffer_size": service_status.get("buffer_size", 0),
        }
        
        # Extract cadence metrics if available
        cadence_metrics = service_status.get("cadence_metrics", {})
        if cadence_metrics:
            sample["cadence_runs"] = cadence_metrics.get("total_runs", 0)
            sample["cadence_skips"] = cadence_metrics.get("total_skips", 0)
            sample["cadence_avg_latency_ms"] = cadence_metrics.get("avg_latency_ms", 0)
            sample["cadence_max_latency_ms"] = cadence_metrics.get("max_latency_ms", 0)
        
        # New-bar gating metrics
        sample["gating_skips"] = service_status.get("gating_skips", 0)
        sample["gating_runs"] = service_status.get("gating_runs", 0)
        
        self.samples.append(sample)
        return sample
    
    def get_summary(self) -> Dict:
        """Generate summary of soak test results."""
        if not self.samples:
            return {}
        
        final = self.samples[-1]
        duration = final["elapsed_seconds"]
        
        # Memory analysis
        memory_values = [s["memory_mb"] for s in self.samples if s["memory_mb"] > 0]
        memory_drift = 0.0
        if memory_values:
            memory_drift = memory_values[-1] - memory_values[0]
        
        # Cycles per minute
        cycles = final.get("cycle_count", 0)
        cycles_per_minute = (cycles / duration * 60) if duration > 0 else 0
        
        # Error rate
        errors = final.get("error_count", 0)
        error_rate = (errors / cycles * 100) if cycles > 0 else 0
        
        return {
            "duration_seconds": duration,
            "duration_formatted": format_duration(duration),
            "total_cycles": cycles,
            "cycles_per_minute": cycles_per_minute,
            "total_signals": final.get("signal_count", 0),
            "total_errors": errors,
            "error_rate_percent": error_rate,
            "initial_memory_mb": self.initial_memory_mb,
            "final_memory_mb": memory_values[-1] if memory_values else -1,
            "memory_drift_mb": memory_drift,
            "memory_drift_percent": (memory_drift / self.initial_memory_mb * 100) if self.initial_memory_mb > 0 else 0,
            "gating_skips": final.get("gating_skips", 0),
            "gating_runs": final.get("gating_runs", 0),
            "cadence_avg_latency_ms": final.get("cadence_avg_latency_ms", 0),
            "cadence_max_latency_ms": final.get("cadence_max_latency_ms", 0),
            "sample_count": len(self.samples),
        }


async def run_soak_test(duration_seconds: int = 300, verbose: bool = False) -> int:
    """
    Run soak test with mock provider.
    
    Args:
        duration_seconds: How long to run the test
        verbose: Enable verbose output
        
    Returns:
        Exit code (0 = pass, 1 = fail)
    """
    from tests.mock_data_provider import MockDataProvider
    from pearlalgo.nq_agent.service import NQAgentService
    from pearlalgo.strategies.nq_intraday.config import NQIntradayConfig
    from pearlalgo.utils.logging_config import setup_logging
    
    # Setup logging
    setup_logging(level="INFO" if verbose else "WARNING")
    
    print("=" * 70)
    print("NQ Agent Service Soak Test (Mock Provider)")
    print("=" * 70)
    print()
    print(f"⚠️  Using synthetic mock data - NOT real market data")
    print(f"Duration: {format_duration(duration_seconds)}")
    print()
    
    # Create mock provider with realistic behavior
    mock_provider = MockDataProvider(
        base_price=17500.0,
        volatility=25.0,
        trend=0.5,
        simulate_timeouts=False,
        simulate_connection_issues=False,
    )
    
    # Create config with fast scan interval for testing
    config = NQIntradayConfig(
        symbol="MNQ",
        timeframe="1m",
        scan_interval=5,  # Fast interval for soak testing
    )
    
    # Create service without Telegram (no notifications during soak test)
    service = NQAgentService(
        data_provider=mock_provider,
        config=config,
        telegram_bot_token=None,
        telegram_chat_id=None,
    )
    
    # Create monitor
    monitor = SoakTestMonitor()
    
    print("-" * 70)
    print("Starting service...")
    print("-" * 70)
    print()
    
    exit_code = 0
    
    try:
        # Start service in background
        service_task = asyncio.create_task(service.start())
        
        # Monitor loop
        sample_interval = 10  # Sample every 10 seconds
        start_time = time.time()
        last_sample_time = 0
        
        while time.time() - start_time < duration_seconds:
            await asyncio.sleep(1)
            
            # Take samples at interval
            if time.time() - last_sample_time >= sample_interval:
                status = service.get_status()
                sample = monitor.sample(status)
                
                if verbose:
                    elapsed = sample["elapsed_seconds"]
                    memory = sample["memory_mb"]
                    cycles = sample["cycle_count"]
                    errors = sample["error_count"]
                    print(f"[{format_duration(elapsed):>6}] cycles={cycles:4d} errors={errors:2d} mem={memory:.1f}MB")
                else:
                    # Print progress dots
                    print(".", end="", flush=True)
                
                last_sample_time = time.time()
        
        print()
        print()
        print("-" * 70)
        print("Stopping service...")
        print("-" * 70)
        
        # Stop service
        service.shutdown_requested = True
        await service.stop()
        
        # Cancel service task if still running
        if not service_task.done():
            service_task.cancel()
            try:
                await service_task
            except asyncio.CancelledError:
                pass
        
    except KeyboardInterrupt:
        print()
        print("Interrupted by user")
        service.shutdown_requested = True
        await service.stop()
    except Exception as e:
        print(f"❌ Error during soak test: {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1
    
    # Generate and print summary
    print()
    print("=" * 70)
    print("SOAK TEST SUMMARY")
    print("=" * 70)
    
    summary = monitor.get_summary()
    
    if not summary:
        print("❌ No samples collected")
        return 1
    
    print(f"  Duration:           {summary['duration_formatted']}")
    print(f"  Total Cycles:       {summary['total_cycles']}")
    print(f"  Cycles/Minute:      {summary['cycles_per_minute']:.1f}")
    print(f"  Total Signals:      {summary['total_signals']}")
    print(f"  Total Errors:       {summary['total_errors']}")
    print(f"  Error Rate:         {summary['error_rate_percent']:.2f}%")
    print()
    print(f"  Initial Memory:     {summary['initial_memory_mb']:.1f} MB")
    print(f"  Final Memory:       {summary['final_memory_mb']:.1f} MB")
    print(f"  Memory Drift:       {summary['memory_drift_mb']:+.1f} MB ({summary['memory_drift_percent']:+.1f}%)")
    print()
    print(f"  Gating Skips:       {summary['gating_skips']}")
    print(f"  Gating Runs:        {summary['gating_runs']}")
    print(f"  Cadence Avg Latency: {summary['cadence_avg_latency_ms']:.1f} ms")
    print(f"  Cadence Max Latency: {summary['cadence_max_latency_ms']:.1f} ms")
    print()
    
    # Evaluate results
    warnings = []
    failures = []
    
    # Check error rate
    if summary['error_rate_percent'] > 10:
        failures.append(f"High error rate: {summary['error_rate_percent']:.1f}% > 10%")
    elif summary['error_rate_percent'] > 5:
        warnings.append(f"Elevated error rate: {summary['error_rate_percent']:.1f}%")
    
    # Check memory drift (allow up to 50MB drift for a 5-minute test)
    if summary['memory_drift_mb'] > 50:
        warnings.append(f"Memory drift: {summary['memory_drift_mb']:.1f} MB")
    elif summary['memory_drift_mb'] > 100:
        failures.append(f"Excessive memory drift: {summary['memory_drift_mb']:.1f} MB")
    
    # Check cadence latency
    if summary['cadence_max_latency_ms'] > 5000:
        warnings.append(f"High max latency: {summary['cadence_max_latency_ms']:.0f} ms")
    
    # Check cycles ran
    expected_min_cycles = duration_seconds / config.scan_interval * 0.5  # 50% threshold
    if summary['total_cycles'] < expected_min_cycles:
        failures.append(f"Too few cycles: {summary['total_cycles']} (expected >={expected_min_cycles:.0f})")
    
    # Print evaluation
    if failures:
        print("❌ FAILURES:")
        for f in failures:
            print(f"   - {f}")
        exit_code = 1
    
    if warnings:
        print("⚠️  WARNINGS:")
        for w in warnings:
            print(f"   - {w}")
    
    if not failures and not warnings:
        print("✅ All checks passed")
    
    print()
    
    if exit_code == 0:
        print("=" * 70)
        print("✅ SOAK TEST PASSED")
        print("=" * 70)
    else:
        print("=" * 70)
        print("❌ SOAK TEST FAILED")
        print("=" * 70)
    
    return exit_code


def main():
    parser = argparse.ArgumentParser(description="NQ Agent Service Soak Test")
    parser.add_argument(
        "--duration", "-d",
        type=int,
        default=300,
        help="Test duration in seconds (default: 300)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose output",
    )
    args = parser.parse_args()
    
    exit_code = asyncio.run(run_soak_test(
        duration_seconds=args.duration,
        verbose=args.verbose,
    ))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()



