#!/usr/bin/env python3
"""
Analyze impact of position count limits on performance.

Tests: What if we capped concurrent positions at 5, 10, 15, 20?
"""

import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

def load_signals(signals_file):
    """Load all signals from JSONL."""
    signals = []
    with open(signals_file) as f:
        for line in f:
            if line.strip():
                try:
                    signals.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return signals

def analyze_concurrent_positions(signals, max_concurrent):
    """
    Simulate trading with a max concurrent position limit.
    
    Returns: PnL, trades taken, trades skipped
    """
    open_positions = {}
    total_pnl = 0.0
    trades_taken = 0
    trades_skipped = 0
    
    # Sort by timestamp
    events = sorted(signals, key=lambda x: x.get('timestamp', ''))
    
    for event in events:
        ts = event.get('timestamp', '')
        signal_id = event.get('signal_id')
        status = event.get('status')
        
        # Entry event
        if status == 'active' and signal_id not in open_positions:
            # Check if we're at limit
            if len(open_positions) >= max_concurrent:
                trades_skipped += 1
                continue
            
            # Open position
            open_positions[signal_id] = {
                'entry_time': ts,
                'entry_price': event.get('entry_price'),
            }
            trades_taken += 1
        
        # Exit event
        elif status == 'exited' and signal_id in open_positions:
            pnl = event.get('pnl', 0.0)
            total_pnl += pnl
            del open_positions[signal_id]
    
    return {
        'max_concurrent': max_concurrent,
        'total_pnl': total_pnl,
        'trades_taken': trades_taken,
        'trades_skipped': trades_skipped,
        'final_open_positions': len(open_positions),
    }

def main():
    signals_file = Path('/home/pearl/PearlAlgoProject/data/tradovate/paper/signals.jsonl')
    
    if not signals_file.exists():
        print(f"Error: {signals_file} not found")
        sys.exit(1)
    
    print("Loading signals...")
    signals = load_signals(signals_file)
    print(f"Loaded {len(signals)} signal events\n")
    
    print("=" * 60)
    print("POSITION LIMIT BACKTEST")
    print("=" * 60)
    
    # Test different limits
    for limit in [5, 10, 15, 20, 999]:
        result = analyze_concurrent_positions(signals, limit)
        
        label = f"Max {limit}" if limit < 999 else "Unlimited"
        print(f"\n{label} Concurrent Positions:")
        print(f"  Trades Taken: {result['trades_taken']}")
        print(f"  Trades Skipped: {result['trades_skipped']}")
        print(f"  Total PnL: ${result['total_pnl']:,.2f}")
        print(f"  Still Open: {result['final_open_positions']}")
        
        if result['trades_taken'] > 0:
            avg_pnl = result['total_pnl'] / result['trades_taken']
            print(f"  Avg PnL/Trade: ${avg_pnl:.2f}")

if __name__ == "__main__":
    main()
