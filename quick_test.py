#!/usr/bin/env python3
"""
Quick test script to verify signal tracking and exit signal improvements.
Run this to quickly verify everything is working.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

def test_imports():
    """Test that all modules can be imported."""
    print("1️⃣  Testing imports...")
    try:
        from pearlalgo.futures.signal_tracker import SignalTracker, TrackedSignal, SignalLifecycleState
        from pearlalgo.futures.exit_signals import ExitSignalGenerator
        from pearlalgo.agents.langgraph_state import TradingState, MarketData
        print("   ✅ All imports successful")
        return True
    except Exception as e:
        print(f"   ❌ Import failed: {e}")
        return False

def test_signal_persistence():
    """Test signal persistence."""
    print("\n2️⃣  Testing signal persistence...")
    try:
        from pearlalgo.futures.signal_tracker import SignalTracker
        
        # Use temporary path
        test_path = Path("data/test_signals_quick.json")
        test_path.parent.mkdir(exist_ok=True)
        
        # Create tracker and add signal
        tracker1 = SignalTracker(persistence_path=test_path)
        success = tracker1.add_signal(
            symbol="ES",
            direction="long",
            entry_price=4500.0,
            size=1,
            stop_loss=4490.0,
            take_profit=4520.0,
        )
        
        if not success:
            print("   ❌ Failed to add signal")
            return False
        
        # Force immediate save (bypass debounce)
        tracker1._save_signals(immediate=True)
        
        # Small delay to ensure file is written
        import time
        time.sleep(0.1)
        
        # Load in new tracker
        tracker2 = SignalTracker(persistence_path=test_path)
        if "ES" not in tracker2.active_signals:
            print("   ❌ Signal not persisted")
            return False
        
        signal = tracker2.get_signal("ES")
        if signal.entry_price != 4500.0:
            print("   ❌ Signal data incorrect")
            return False
        
        # Cleanup
        tracker2.clear()
        print("   ✅ Signal persistence working")
        return True
    except Exception as e:
        print(f"   ❌ Persistence test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def test_exit_signals():
    """Test exit signal generation."""
    print("\n3️⃣  Testing exit signal generation...")
    try:
        from pearlalgo.futures.signal_tracker import SignalTracker
        from pearlalgo.futures.exit_signals import ExitSignalGenerator
        from pearlalgo.agents.langgraph_state import TradingState, MarketData
        
        tracker = SignalTracker()
        exit_gen = ExitSignalGenerator(signal_tracker=tracker)
        
        # Add signal
        tracker.add_signal("ES", "long", 4500.0, 1, stop_loss=4490.0)
        
        # Create state with price below stop loss
        state = TradingState(
            market_data={
                "ES": MarketData(
                    symbol="ES",
                    timestamp=datetime.now(timezone.utc),
                    open=4485.0,
                    high=4490.0,
                    low=4480.0,
                    close=4485.0,
                    volume=1000,
                )
            },
            signals={},
            position_decisions={},
        )
        
        exit_signals = await exit_gen.generate_exit_signals(state)
        
        if "ES" not in exit_signals:
            print("   ❌ Exit signal not generated")
            return False
        
        exit_type = exit_signals["ES"].indicators.get("exit_type")
        if exit_type != "stop_loss":
            print(f"   ❌ Wrong exit type: {exit_type}")
            return False
        
        print("   ✅ Exit signal generation working")
        return True
    except Exception as e:
        print(f"   ❌ Exit signal test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_metrics():
    """Test metrics collection."""
    print("\n4️⃣  Testing metrics...")
    try:
        from pearlalgo.futures.signal_tracker import SignalTracker
        from pearlalgo.futures.exit_signals import ExitSignalGenerator
        
        tracker = SignalTracker()
        tracker.add_signal("ES", "long", 4500.0, 1)
        
        metrics = tracker.get_metrics()
        if metrics["active_signals_count"] != 1:
            print(f"   ❌ Wrong signal count: {metrics['active_signals_count']}")
            return False
        
        exit_gen = ExitSignalGenerator(signal_tracker=tracker)
        exit_metrics = exit_gen.get_exit_metrics()
        
        if "exit_generation" not in exit_metrics:
            print("   ❌ Exit metrics missing")
            return False
        
        print("   ✅ Metrics collection working")
        return True
    except Exception as e:
        print(f"   ❌ Metrics test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Run all tests."""
    print("=" * 60)
    print("🧪 Quick Test: Signal Tracking & Exit Signal Improvements")
    print("=" * 60)
    print()
    
    results = []
    
    # Test imports
    results.append(test_imports())
    
    # Test persistence
    results.append(test_signal_persistence())
    
    # Test exit signals
    results.append(await test_exit_signals())
    
    # Test metrics
    results.append(test_metrics())
    
    # Summary
    print("\n" + "=" * 60)
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ ALL TESTS PASSED ({passed}/{total})")
        print("\n🎉 System is ready to run!")
        print("\nNext steps:")
        print("  1. Start service: python3 -m pearlalgo.monitoring.continuous_service --config config/config.yaml")
        print("  2. Check health: curl http://localhost:8080/healthz | jq")
        print("  3. Monitor logs: tail -f logs/continuous_service.log")
        return 0
    else:
        print(f"❌ SOME TESTS FAILED ({passed}/{total})")
        print("\nPlease check the errors above and ensure:")
        print("  1. Virtual environment is activated: source .venv/bin/activate")
        print("  2. Package is installed: pip install -e .")
        print("  3. Dependencies are installed: pip install pytest pytest-asyncio")
        return 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
