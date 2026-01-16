#!/usr/bin/env python3
"""
Sync TradingView Chart Configuration

This script helps keep your Python chart generator in sync with your TradingView setup.

Usage:
1. Export your TradingView chart template (Settings > Chart > Export Template)
2. Or share your chart and paste the link
3. Run this script to update your chart generator config
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

def parse_tradingview_url(url: str) -> Dict[str, Any]:
    """
    Parse TradingView chart URL to extract configuration.
    
    TradingView URLs contain chart settings in the query parameters.
    Example: https://www.tradingview.com/chart/?symbol=NASDAQ:MNQ&interval=5
    """
    config = {}
    
    # Extract symbol
    if "symbol=" in url:
        symbol = url.split("symbol=")[1].split("&")[0]
        config["symbol"] = symbol.replace("NASDAQ:", "").replace("CME:", "")
    
    # Extract interval/timeframe
    if "interval=" in url:
        interval = url.split("interval=")[1].split("&")[0]
        config["timeframe"] = interval
    
    # Extract theme
    if "theme=" in url:
        theme = url.split("theme=")[1].split("&")[0]
        config["theme"] = theme
    
    return config

def update_chart_config(tv_config: Dict[str, Any], config_path: Path) -> None:
    """Update chart generator config from TradingView settings."""
    import yaml
    
    # Load existing config
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f) or {}
    
    # Update chart settings
    if "chart" not in config:
        config["chart"] = {}
    
    # Map TradingView settings to our config
    if "symbol" in tv_config:
        # Update symbol in service config
        if "service" not in config:
            config["service"] = {}
        # Note: symbol is usually in service config, not chart
    
    if "timeframe" in tv_config:
        config["chart"]["timeframe"] = tv_config["timeframe"]
    
    if "theme" in tv_config:
        config["chart"]["theme"] = tv_config["theme"]
    
    # Save updated config
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    
    print(f"✅ Updated chart config in {config_path}")

def main():
    """Main sync function."""
    print("📊 TradingView Chart Sync Tool\n")
    
    config_path = project_root / "config" / "config.yaml"
    
    print("Options:")
    print("1. Sync from TradingView chart URL")
    print("2. Sync from exported Pine script")
    print("3. Manual config update")
    
    choice = input("\nEnter choice (1-3): ").strip()
    
    if choice == "1":
        url = input("Paste your TradingView chart URL: ").strip()
        tv_config = parse_tradingview_url(url)
        print(f"\n📋 Extracted config: {tv_config}")
        update_chart_config(tv_config, config_path)
        
    elif choice == "2":
        pine_file = input("Path to Pine script file: ").strip()
        print(f"\n📝 Reading Pine script: {pine_file}")
        # Parse Pine script for indicator settings
        # This would need custom parsing logic
        print("⚠️  Pine script parsing not yet implemented")
        print("   Please manually update indicators in:")
        print(f"   {project_root / 'src' / 'pearlalgo' / 'strategies' / 'nq_intraday' / 'indicators'}")
        
    elif choice == "3":
        print("\n📝 Manual config update")
        print(f"Edit config file: {config_path}")
        print("\nChart settings are in:")
        print("  - config/config.yaml (service.dashboard_chart_*)")
        print("  - src/pearlalgo/nq_agent/chart_generator.py (ChartConfig)")
        
    else:
        print("❌ Invalid choice")

if __name__ == "__main__":
    main()
