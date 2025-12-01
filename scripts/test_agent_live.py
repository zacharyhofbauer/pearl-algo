#!/usr/bin/env python
"""
Quick test script to see the agent in action with verbose output.
This runs a short test cycle to demonstrate the thinking process.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pearlalgo.agents.automated_trading_agent import AutomatedTradingAgent

def main():
    print("\n" + "="*70)
    print("🧪 TESTING AUTOMATED TRADING AGENT - VERBOSE MODE")
    print("="*70 + "\n")
    
    # Create agent with short interval for testing
    agent = AutomatedTradingAgent(
        symbols=["NQ"],  # Just test with one symbol
        sec_types=["FUT"],
        strategy="sr",
        interval=60,  # 1 minute for quick testing
        tiny_size=1,
        max_retries=3,
        retry_delay=10,
    )
    
    print("\n💡 This will run for a few cycles to show the thinking process.")
    print("   Press Ctrl+C to stop early.\n")
    
    try:
        agent.start()
    except KeyboardInterrupt:
        print("\n\n✅ Test completed!")

if __name__ == "__main__":
    main()

