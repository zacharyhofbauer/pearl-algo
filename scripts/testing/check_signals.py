#!/usr/bin/env python3
"""
Check signals file and show diagnostic information.

Usage:
    python3 scripts/testing/check_signals.py
"""

import json
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from pearlalgo.utils.paths import get_signals_file, ensure_state_dir
except ImportError:
    # Fallback if module not available
    def ensure_state_dir(state_dir=None):
        if state_dir is None:
            state_dir = Path("data/agent_state/NQ")
        state_path = Path(state_dir)
        state_path.mkdir(parents=True, exist_ok=True)
        return state_path
    
    def get_signals_file(state_dir):
        return state_dir / "signals.jsonl"


def main():
    """Check signals file."""
    state_dir = ensure_state_dir()
    signals_file = get_signals_file(state_dir)
    
    print(f"Signals file: {signals_file}")
    print(f"Exists: {signals_file.exists()}")
    
    if not signals_file.exists():
        print("\n❌ Signals file does not exist yet.")
        print("   Signals will be created when the agent generates trading opportunities.")
        return
    
    file_size = signals_file.stat().st_size
    print(f"Size: {file_size} bytes")
    
    if file_size == 0:
        print("\n⚠️  Signals file is empty.")
        print("   This could mean:")
        print("   • Signals haven't been generated yet")
        print("   • Signals were generated but not saved (check logs)")
        print("   • The file was cleared")
        return
    
    # Read and analyze signals
    signals = []
    errors = []
    line_num = 0
    
    with open(signals_file) as f:
        for line in f:
            line_num += 1
            line = line.strip()
            if not line:
                continue
            
            try:
                signal_data = json.loads(line)
                signals.append((line_num, signal_data))
            except json.JSONDecodeError as e:
                errors.append((line_num, str(e)))
    
    print(f"\nTotal lines: {line_num}")
    print(f"Valid signals: {len(signals)}")
    print(f"Parse errors: {len(errors)}")
    
    if errors:
        print(f"\n⚠️  Parse errors found:")
        for line_num, error in errors[:5]:  # Show first 5 errors
            print(f"   Line {line_num}: {error}")
        if len(errors) > 5:
            print(f"   ... and {len(errors) - 5} more errors")
    
    if signals:
        print(f"\n✅ Found {len(signals)} valid signal(s):")
        print()
        
        # Show format of first signal
        first_line, first_signal = signals[0]
        print(f"Line {first_line} format:")
        if "signal" in first_signal:
            print("   ✅ New format (wrapped): {'signal_id', 'timestamp', 'status', 'signal'}")
            signal_id = first_signal.get("signal_id", "unknown")
            timestamp = first_signal.get("timestamp", "unknown")
            status = first_signal.get("status", "unknown")
            print(f"   Signal ID: {signal_id}")
            print(f"   Timestamp: {timestamp}")
            print(f"   Status: {status}")
        elif "signal_id" in first_signal or "type" in first_signal:
            print("   ⚠️  Old format (direct signal dict): needs migration")
            signal_id = first_signal.get("signal_id", "unknown")
            signal_type = first_signal.get("type", "unknown")
            print(f"   Signal ID: {signal_id}")
            print(f"   Type: {signal_type}")
        else:
            print("   ❌ Unknown format")
        
        # Show last few signals
        print(f"\nLast {min(5, len(signals))} signal(s):")
        for line_num, signal_data in signals[-5:]:
            if "signal" in signal_data:
                sig = signal_data["signal"]
                signal_id = signal_data.get("signal_id", "unknown")
                status = signal_data.get("status", "unknown")
            else:
                sig = signal_data
                signal_id = sig.get("signal_id", "unknown")
                status = sig.get("status", "generated")
            
            signal_type = sig.get("type", "unknown")
            direction = sig.get("direction", "unknown")
            entry_price = sig.get("entry_price", 0)
            
            print(f"   Line {line_num}: {signal_type} {direction} @ ${entry_price:.2f} (ID: {signal_id[:16]}..., Status: {status})")
    else:
        print("\n❌ No valid signals found in file.")


if __name__ == "__main__":
    main()
