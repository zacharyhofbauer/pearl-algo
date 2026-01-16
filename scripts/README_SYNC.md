# TradingView Chart Sync - Quick Start

## Two Ways to Sync

### Option 1: Chart Link (Fastest)
```bash
python3 scripts/sync_tradingview_chart.py
# Paste your TradingView chart URL
```

### Option 2: CSV Export (More Data)
```bash
python3 scripts/sync_tradingview_chart.py
# Choose option 2, provide CSV file path
```

Or pass directly:
```bash
python3 scripts/sync_tradingview_chart.py "https://tradingview.com/chart/..."
python3 scripts/sync_tradingview_chart.py chart_data.csv
```

## Getting Your Data

**Chart Link:**
1. TradingView > Chart Layout > Share
2. Copy URL

**CSV Export:**
1. TradingView > Menu (⋮) > Export data
2. Choose CSV format
3. Download file

## What Gets Synced

- ✅ Symbol (MNQ, NQ, ES, etc.)
- ✅ Timeframe (1m, 5m, 15m, etc.)
- ✅ Lookback hours (auto-calculated)
- ✅ Indicator detection (from CSV columns)
- ✅ Config file updates

All automatic! 🚀
