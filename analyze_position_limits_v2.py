#!/usr/bin/env python3
"""
Analyze impact of position count limits on performance.

Tests: What if we capped concurrent positions at 5, 10, 15, 20?
"""

import json
import sys
from datetime import datetime
from pathlib import Path

def parse_iso(ts_str):
    """Parse ISO timestamp, handle timezone awareness."""
    try:
        return datetime.fromisoformat(ts_str.replace('+00:00', '').replace('Z', ''))
    except:
        return None

def load_completed_signals(signals_file):
    """Load only completed (exited) signals with valid PnL."""
    signals = []
    with open(signals_file) as f:
        for line in f:
            if line.strip():
                try:
                    sig = json.loads(line)
                    # Only take exited signals with PnL data
                    if sig.get('status') == 'exited' and 'pnl' in sig and 'entry_time' in sig and 'exit_time' in sig:
                        signals.append(sig)
                except json.JSONDecodeError:
                    continue
    return signals

def simulate_with_limit(signals, max_concurrent):
    """
    Simulate trading with position count limit.
    
    Strategy: When limit is hit, skip new entries until slots open.
    """
    # Sort all signals by entry time
    sorted_signals = sorted(signals, key=lambda x: parse_iso(x.get('entry_time', '')) or datetime.min)
    
    open_positions = []
    total_pnl = 0.0
    trades_taken = 0
    trades_skipped = 0
    max_concurrent_seen = 0
    
    for sig in sorted_signals:
        entry_time = parse_iso(sig.get('entry_time'))
        exit_time = parse_iso(sig.get('exit_time'))
        pnl = sig.get('pnl', 0.0)
        
        if not entry_time or not exit_time:
            continue
        
        # Close any positions that exited before this entry
        open_positions = [p for p in open_positions if parse_iso(p.get('exit_time')) > entry_time]
        
        # Check if we can take this trade
        if len(open_positions) >= max_concurrent:
            trades_skipped += 1
            continue
        
        # Take the trade
        open_positions.append(sig)
        total_pnl += pnl
        trades_taken += 1
        max_concurrent_seen = max(max_concurrent_seen, len(open_positions))
    
    return {
        'max_concurrent': max_concurrent,
        'total_pnl': total_pnl,
        'trades_taken': trades_taken,
        'trades_skipped': trades_skipped,
        'max_concurrent_seen': max_concurrent_seen,
    }

def main():
    signals_file = Path('/home/pearl/PearlAlgoProject/data/tradovate/paper/signals.jsonl')
    
    if not signals_file.exists():
        print(f"Error: {signals_file} not found")
        sys.exit(1)
    
    print("Loading signals...")
    signals = load_completed_signals(signals_file)
    print(f"Loaded {len(signals)} completed trades\n")
    
    if not signals:
        print("No completed trades found!")
        sys.exit(1)
    
    # Calculate baseline (unlimited)
    baseline = simulate_with_limit(signals, 9999)
    
    print("=" * 70)
    print("POSITION LIMIT BACKTEST — Impact Analysis")
    print("=" * 70)
    
    print(f"\nBaseline (Unlimited):")
    print(f"  Total Trades: {baseline['trades_taken']}")
    print(f"  Total PnL: ${baseline['total_pnl']:,.2f}")
    print(f"  Avg PnL/Trade: ${baseline['total_pnl']/baseline['trades_taken']:.2f}")
    print(f"  Peak Concurrent Positions: {baseline['max_concurrent_seen']}")
    
    print(f"\n{'-'*70}\n")
    
    # Test different limits
    for limit in [5, 10, 15, 20, 25]:
        result = simulate_with_limit(signals, limit)
        
        pnl_delta = result['total_pnl'] - baseline['total_pnl']
        pct_trades = (result['trades_taken'] / baseline['trades_taken']) * 100
        
        print(f"Max {limit} Concurrent Positions:")
        print(f"  Trades Taken: {result['trades_taken']} ({pct_trades:.1f}% of baseline)")
        print(f"  Trades Skipped: {result['trades_skipped']}")
        print(f"  Total PnL: ${result['total_pnl']:,.2f} (Δ ${pnl_delta:+,.2f})")
        
        if result['trades_taken'] > 0:
            avg_pnl = result['total_pnl'] / result['trades_taken']
            print(f"  Avg PnL/Trade: ${avg_pnl:.2f}")
        
        # Impact summary
        if pnl_delta > 0:
            print(f"  ✅ BETTER by ${pnl_delta:,.2f} (limited exposure prevented losses)")
        elif pnl_delta < 0:
            print(f"  ❌ WORSE by ${abs(pnl_delta):,.2f} (missed profitable trades)")
        else:
            print(f"  ➖ NEUTRAL (no impact)")
        
        print()

if __name__ == "__main__":
    main()
