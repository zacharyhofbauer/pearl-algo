# PEARL Live Chart Setup

## Overview

The PEARL Live Chart provides a real-time TradingView-style chart interface displaying live IBKR market data with technical indicators, trade markers, and agent status.

## Architecture

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────┐
│  Next.js        │◄─────┤  FastAPI Server  │◄─────┤ IBKR        │
│  Frontend       │      │  (Port 8000)     │      │ Gateway     │
│  (Port 3001)    │      │                  │      │ (Port 4002) │
└─────────────────┘      └──────────────────┘      └─────────────┘
```

## Components

### 1. FastAPI API Server (`scripts/live-chart/api_server.py`)
- **Port**: 8000 (default)
- **IBKR Client ID**: 97 (configurable via `IB_CLIENT_ID_LIVE_CHART`)
- **Endpoints**:
  - `GET /api/candles` - OHLCV candle data
  - `GET /api/indicators` - EMA9, EMA21, VWAP, RSI
  - `GET /api/markers` - Trade entry/exit markers
  - `GET /api/sessions` - Market session highlighting
  - `GET /api/state` - Agent state (P&L, trades, status)
  - `GET /health` - Health check

### 2. Next.js Frontend (`live-chart/`)
- **Port**: 3001 (default)
- **Framework**: Next.js 14 with TypeScript
- **Chart Library**: Lightweight Charts (TradingView)
- **Features**:
  - Real-time price updates (10-second refresh)
  - Multiple timeframes (1m, 5m, 15m, 1h)
  - Technical indicators overlay
  - Trade markers with hover tooltips
  - Responsive design

## Configuration

### Environment Variables (`.env`)

```bash
# IBKR Connection (shared with main agent)
IBKR_HOST=127.0.0.1
IBKR_PORT=4002

# Live Chart Client ID (must be unique)
IB_CLIENT_ID_LIVE_CHART=97

# Optional: Custom ports
PEARL_API_PORT=8000
PEARL_CHART_PORT=3001

# Optional: Public URL for external access
PEARL_MINI_APP_URL=https://pearlalgo.io/
```

### Client ID Management

**Used Client IDs:**
- `10` - Main Market Agent
- `11` - Market Agent Data Provider
- `97` - Live Chart API Server
- `98` - ~~Reserved (conflict detected)~~

⚠️ **Important**: Each IBKR connection must use a unique client ID. If you get "Error 326: client id already in use", change `IB_CLIENT_ID_LIVE_CHART` to an unused ID (96, 95, etc.).

## Usage

### Start Live Chart

```bash
# Start both API server and frontend
./scripts/live-chart/start.sh --market NQ

# Start API server only
./scripts/live-chart/start.sh --market NQ --api-only

# Start frontend only (API must be running separately)
./scripts/live-chart/start.sh --chart-only
```

### Stop Live Chart

```bash
./scripts/live-chart/stop.sh
```

### Access

- **Local**: http://localhost:3001
- **Public** (via Cloudflare Tunnel): https://pearlalgo.io

## Data Flow

1. **Frontend** requests candles every 10 seconds
2. **API Server** receives request
3. **IBKR Provider** fetches historical data from Interactive Brokers
4. **API Server** converts data to TradingView format
5. **Frontend** renders chart with updated data

## Real-time Updates

The chart updates automatically:
- **Price Data**: Every 10 seconds
- **Indicators**: Calculated on-the-fly from price data
- **Trade Markers**: Loaded from `signals.jsonl`
- **Agent State**: P&L, active trades, win/loss stats

## Data Sources

### OHLCV Candles
- **Source**: IBKR real-time historical data
- **Format**: `{time, open, high, low, close, volume}`
- **No mock/dummy data** - all prices are live from IBKR

### Trade Markers
- **Source**: `data/agent_state/{MARKET}/signals.jsonl`
- **Displays**: Entry/exit points with P&L

### Agent State
- **Source**: `data/agent_state/{MARKET}/state.json`
- **Displays**: Running status, daily P&L, active positions

## Troubleshooting

### Chart shows "No Live Data"
1. Check IBKR Gateway is running: `./scripts/ibkr/check.sh`
2. Check API server logs: `tail -f logs/live_chart_api.log`
3. Verify IBKR connection: `curl http://localhost:8000/health`

### "Error 326: client id already in use"
1. Change client ID in `.env`: `IB_CLIENT_ID_LIVE_CHART=96`
2. Restart live chart: `./scripts/live-chart/stop.sh && ./scripts/live-chart/start.sh`

### Chart not updating
1. Check browser console for errors (F12)
2. Verify API endpoint: `curl http://localhost:8000/api/candles?symbol=MNQ&timeframe=5m&bars=10`
3. Check API server is running: `ps aux | grep api_server`

### Data appears delayed
- **This is normal!** The live chart often shows data AHEAD of TradingView
- IBKR data is fresher than most retail data feeds
- Typical delay: 0-2 candles vs. TradingView

## Performance

- **API Response Time**: ~200-500ms per request
- **Memory Usage**: ~150MB (API server) + ~70MB (Next.js)
- **CPU Usage**: <5% idle, 10-20% during updates
- **Bandwidth**: ~1KB/request every 10 seconds

## Development

### Install Dependencies

```bash
# Frontend
cd live-chart && npm install

# Backend (API server uses main project venv)
source .venv/bin/activate
pip install fastapi uvicorn
```

### Run in Development

```bash
# API server with auto-reload
cd scripts/live-chart
python api_server.py --market NQ --port 8000

# Frontend with hot-reload
cd live-chart
npm run dev
```

## Production Deployment

### Via Cloudflare Tunnel

The live chart is accessible at `https://pearlalgo.io` via Cloudflare Tunnel.

**Setup:**
1. Tunnel configured in Cloudflare Zero Trust
2. Domain `pearlalgo.io` points to localhost:3001
3. Start chart: `./scripts/live-chart/start.sh`

### Security Considerations

- ✅ API server binds to `127.0.0.1` (localhost only)
- ✅ Cloudflare Tunnel provides secure HTTPS
- ✅ No authentication required (read-only data)
- ⚠️ IBKR credentials stored in `.env` (ensure proper permissions)

## Files

```
live-chart/                    # Next.js frontend
├── app/
│   ├── page.tsx              # Main chart page
│   └── layout.tsx            # App layout
├── components/
│   └── CandlestickChart.tsx  # Chart component
└── public/
    └── logo.png              # PEARL logo

scripts/live-chart/
├── api_server.py             # FastAPI backend
├── start.sh                  # Start script
└── stop.sh                   # Stop script

logs/
├── live_chart_api.log        # API server logs
└── live_chart_web.log        # Next.js logs
```

## Status

✅ **Fully Operational**
- IBKR connection: Active
- Real-time data: Live
- Chart rendering: Working
- Trade markers: Displaying
- Public access: https://pearlalgo.io

---

**Last Updated**: 2026-01-29  
**Maintainer**: PEARLalgo Development Team
