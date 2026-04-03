# Pearl Algo Web App

This repo's **canonical chart** is the web-based **Pearl Algo Web App** (`apps/pearl-algo-app/`).

It powers:
- A **browser dashboard** (local or deployed)
- API-backed charting and dashboard panels
- Operator workflows exposed through the web UI and API

Historical Telegram screenshot assets and mini-app notes were archived during
the 2026-04-03 documentation cleanup under `docs/legacy/telegram/` and
`resources/legacy/`. The active product surface is the browser dashboard.

---

## Prerequisites

**Node.js 20.x** is required for the Next.js 14 chart:

```bash
# Ubuntu/Debian
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs

# Verify
node --version  # v20.x.x
```

---

## Architecture

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────┐
│  Next.js        │◄────►│  FastAPI Server  │◄─────┤ IBKR        │
│  Frontend       │  WS  │  (Port 8001)     │      │ Gateway     │
│  (Port 3001)    │      │                  │      │ (Port 4001) │
└─────────────────┘      └──────────────────┘      └─────────────┘
        │                         │
        ▼                         ▼
   Zustand Stores           WebSocket Broadcast
   (agentStore,             (real-time updates)
    chartStore,
    uiStore)
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Timeframe Selector** | Switch between 1m, 5m, 15m, 1h (header buttons) |
| **Dynamic Viewport** | Bar count adjusts to screen width automatically |
| **Fit All / Go Live** | Quick buttons (top-right) to fit all data or jump to live edge |
| **Indicators** | EMA9 (cyan), EMA21 (yellow), VWAP (purple dashed) |
| **Trade Markers** | Entry arrows and Exit dots with hover tooltips showing signal details |
| **WebSocket Updates** | Real-time state updates via WebSocket (2-second broadcast) |
| **Error Boundaries** | Graceful component failure handling with `role="alert"` |
| **API Authentication** | API key authentication for protected endpoints (enabled by default) |
| **Passcode Gate** | Optional passcode login screen for shared/public dashboards |
| **Status Badges** | Header badges for Agent, GW, AI, Market, Data, ML, Shadow savings (with hover tooltips) |
| **SystemStatusPanel** | Readiness (Offline/Paused/Cooldown/Disarmed/Armed), kill switch with operator lock, session P&L, circuit breaker state |
| **Agent Banner** | Agent offline / execution disabled banner with clear visual indicator |
| **Pull-to-Refresh** | Mobile gesture support for dashboard refresh |
| **Pearl AI Chat (LLM)** | Optional LLM chat box (local/Ollama + Claude) backed by `/api/pearl/*` |
| **Accessibility** | WCAG AA contrast, focus indicators, ARIA roles/labels, keyboard navigation, skip-link, reduced-motion support |
| **Commission Handling** | Tradovate Paper fill P&L auto-adjusted against Tradovate equity to account for broker fees |

---

## Components

### 1. FastAPI API Server (`src/pearlalgo/api/server.py`)
- **Port**: 8001 (Tradovate Paper — the only active account)
- **IBKR Client ID**: 96 (configurable via `IB_CLIENT_ID_LIVE_CHART`)
- **Auth**: Enabled by default (`PEARL_API_AUTH_ENABLED=true`). Set `PEARL_API_AUTH_ENABLED=false` to disable for local dev.
- **Rate limiting**: Operator endpoints (`/api/kill-switch`, `/api/close-all-trades`, `/api/close-trade`) are rate-limited to 5 requests per 60 seconds.
- **State reads**: Uses `StateReader` with shared file locks for safe concurrent reads of `state.json` (prevents torn reads during agent writes).
- **Endpoints**:
  - `GET /api/candles` - OHLCV candle data
  - `GET /api/indicators` - EMA9, EMA21, VWAP, Bollinger Bands, ATR Bands, Volume Profile
  - `GET /api/markers` - Trade entry/exit markers (authenticated)
  - `GET /api/state` - Agent state with full system health (authenticated)
  - `GET /api/trades` - Recent trades (authenticated)
  - `GET /api/analytics` - Session analytics (authenticated)
  - `GET /api/market-status` - Market open/closed status
  - `WS /ws` - WebSocket for real-time updates
  - `GET /health` - Health check

### 2. Next.js Frontend (`apps/pearl-algo-app/`)
- **Port**: 3001 (default)
- **Framework**: Next.js 14 with TypeScript
- **Chart Library**: Lightweight Charts (TradingView)
- **State Management**: Zustand stores
- **Features**:
  - Real-time WebSocket updates
  - Fallback HTTP polling when WebSocket disconnected
  - Multiple data panels (Performance, Risk, Analytics, System Health)
  - Error boundaries for graceful failures

---

## Local run (dev)

Start API server + Next.js chart:

```bash
./pearl.sh chart start
# or
./pearl.sh chart restart
```

Open the chart:
- `http://localhost:3001`

Stop:

```bash
./pearl.sh chart stop
```

---

## UI iteration with Cursor Browser Visual Editor ("Visuals")

Cursor includes a **visual editor inside the built-in Browser** that lets you manipulate rendered UI (layout + styles) and then have Cursor apply the corresponding changes back into your codebase.

Official references:
- Blog: [Cursor blog: Browser Visual Editor](https://cursor.com/blog/browser-visual-editor)
- Changelog (2.2): [Cursor changelog 2.2](https://cursor.com/changelog/2-2)
- Docs: [Cursor docs: Agent Browser](https://cursor.com/docs/agent/browser)

### Quick workflow (recommended for `apps/pearl-algo-app/`)

1. Start the app (`./pearl.sh chart start`) and open `http://localhost:3001`.
2. In Cursor, open the Browser on that URL and open the **design sidebar / Visual Editor**.
3. Select an element (and multi-select when helpful) to:
   - rearrange with drag-and-drop
   - adjust styles with visual controls (spacing, flex/grid, typography, colors, shadows/opacity, etc.)
   - inspect components/props (React) to test variants
4. When it looks right, click **Apply** so Cursor updates the underlying files. Review the diff before keeping it.

### Practical tips

- **Point-and-prompt**: select elements and describe changes; Cursor can use multi-selection as broader context (useful for “make these consistent” edits).
- **Responsive sanity-check**: resize the Browser pane to approximate different widths, but still validate on real viewport sizes and add explicit responsive rules in code (CSS media queries / Tailwind breakpoints).
- **Undo/redo/delete**: depending on Cursor version, common shortcuts (Cmd/Ctrl+Z, Cmd/Ctrl+Shift+Z) and Backspace may work inside the visual editor.
- **QoL improvements to look for** (varies by Cursor version): reduced selection animations (snappier selection) and finer-grained blur controls (e.g., 0.1 steps).
- **Text/content changes**: if direct text editing isn’t available in your build, edit the JSX/HTML source for copy changes.

### Safety checklist (before big UI edits)

This prevents “9-hour rollback” situations.

1. **Work on a branch** (avoid direct edits on `main` during market hours):

```bash
git switch -c ui/webapp-$(date -u +%Y-%m-%d)
```

2. **Capture a baseline** (optional but recommended):

```bash
# Lightweight tag you can roll back to quickly
git tag "baseline/webapp-$(date -u +%Y-%m-%d-%H%MZ)" -m "Known-good web app UI"
```

3. **Preflight build before/after changes**:

```bash
cd apps/pearl-algo-app && npm run build
```

### Emergency rollback (UI/layout/CSS)

If the UI gets messy, do a **path-scoped rollback** (no history rewrite) using:

- `scripts/maintenance/git_rollback_paths.sh`

Example (rollback web app + API server to a known-good commit/tag):

Known-good baseline tag:
- `baseline/webapp-2026-02-03-0803Z`

```bash
./scripts/maintenance/git_rollback_paths.sh \
  --target baseline/webapp-2026-02-03-0803Z \
  --path apps/pearl-algo-app \
  --path scripts/pearlalgo_web_app \
  --run "cd apps/pearl-algo-app && npm run build" \
  --commit \
  --message "Rollback web app UI to known-good template" \
  --yes
```

Notes:
- The script **requires a clean working tree** and creates a backup branch automatically (`backup/pre-rollback-...`).
- To undo the rollback: `git switch <that-backup-branch>`.

---

## State Management

The app uses Zustand stores for centralized state:

| Store | Purpose |
|-------|---------|
| `useAgentStore` | Agent state, performance, trades, analytics |
| `useChartStore` | Candles, indicators, markers, timeframe |
| `useUIStore` | WebSocket status, theme, notifications |

---

## API Authentication (Recommended)

Auth is enabled by default. Store the API key in the secrets file:

```bash
# ~/.config/pearlalgo/secrets.env
PEARL_API_KEY=your-secret-key
```

When starting via `./pearl.sh chart start`, the script exports
`NEXT_PUBLIC_READONLY_API_KEY` from `PEARL_API_KEY` so the frontend sends the
read-only `X-API-Key` header automatically. `NEXT_PUBLIC_API_KEY` remains a
supported legacy fallback for compatibility.

If you change the key, restart the web app and hard refresh the browser.

To disable auth for local development only:

```bash
export PEARL_API_AUTH_ENABLED=false
```

Read-only endpoints require the `X-API-Key` header. Mutating/operator endpoints
also require the `X-PEARL-OPERATOR` header and will reject browser API keys.

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PEARL_API_PORT` | `8001` | API server port |
| `PEARL_CHART_PORT` | `3001` | Chart web interface port |
| `PEARL_LIVE_CHART_ORIGINS` | *(unset)* | CORS origins for API (comma-separated) |
| `PEARL_WEBAPP_AUTH_ENABLED` | `false` | Enable passcode-gated access to the Next.js dashboard |
| `PEARL_WEBAPP_PASSCODE` | *(unset)* | Passcode required when `PEARL_WEBAPP_AUTH_ENABLED=true` (set in local secrets) |
| `PEARL_AI_API_ENABLED` | `false` | Enable Pearl AI LLM endpoints on the API server (`/api/pearl/*`) |
| `PEARL_API_AUTH_ENABLED` | `true` | Enable API authentication |
| `PEARL_API_KEY` | *(secrets.env)* | Read-only API key for browser/API access |
| `NEXT_PUBLIC_READONLY_API_KEY` | *(auto from `PEARL_API_KEY`)* | Preferred frontend read-only API key |
| `NEXT_PUBLIC_API_KEY` | *(legacy fallback)* | Legacy frontend key name retained for compatibility |
| `PEARL_RATE_LIMIT_REQUESTS` | `50000` | Rate limit requests per window |
| `PEARL_RATE_LIMIT_WINDOW` | `60` | Rate limit window (seconds) |

---

## Testing

Run the test suite:

```bash
cd apps/pearl-algo-app
npm test              # Run all tests
npm run test:watch    # Watch mode
npm run test:coverage # With coverage
```

---

## Troubleshooting

### Chart shows "No Data"
Ensure:
1. Market Agent is running (`./pearl.sh status`)
2. IBKR Gateway is connected (`./pearl.sh gateway status`)
3. API server is running (check `http://localhost:8001/health`)

### API returns "Missing API key"
1. Set `PEARL_API_KEY` in your local secrets file (for example, $HOME/.config/pearlalgo/secrets.env)
2. Restart the web app (`./pearl.sh chart restart`)
3. Hard refresh the browser (client env is baked at startup)

### WebSocket not connecting
1. Check API server logs for WebSocket errors
2. Verify port 8001 is accessible
3. Check browser console for connection errors

---

**Last Updated**: 2026-04-02
**Maintainer**: PEARLalgo Development Team
