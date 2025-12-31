# Mini App Guide (PearlAlgo Terminal)

This guide covers setup and operation of the **PearlAlgo Terminal** — a Telegram Mini App that provides a Bloomberg-style interactive trading terminal inside Telegram.

---

## Overview

The Mini App ("Decision Room") provides:
- **Interactive candlestick charts** with volume, entry/stop/TP overlays
- **Explainability panels** showing why a signal was generated (MTF, regime, VWAP, pressure)
- **Risk/invalidation view** showing what breaks the thesis
- **ATS constraints** (armed/disarmed, daily loss limits, session windows)
- **ML diagnostics** (feature snapshot, confidence decomposition)
- **Claude panel** for AI-powered critique and explanation
- **Notes** for quick journaling tied to signals

The Mini App runs **inside Telegram's WebView** (not in an external browser), providing a seamless experience.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Telegram Chat                          │
│   (alerts, commands, inline buttons)                        │
└─────────────────┬───────────────────────────────────────────┘
                  │ "Open Terminal" / signal button
                  ▼
┌─────────────────────────────────────────────────────────────┐
│               Telegram WebView (in-app)                      │
│   ┌─────────────────────────────────────────────────────┐   │
│   │           Mini App Frontend (HTML/JS/CSS)            │   │
│   │   - Telegram WebApp SDK for theme + auth             │   │
│   │   - Lightweight charting library                     │   │
│   └─────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────┘
                  │ REST API + initData auth
                  ▼
┌─────────────────────────────────────────────────────────────┐
│              Mini App Backend (FastAPI)                      │
│   - Validates Telegram initData signature                    │
│   - Enforces me-only access (TELEGRAM_CHAT_ID)              │
│   - Serves JSON endpoints for Decision Room state            │
│   - Reads from existing state files (signals.jsonl, etc.)    │
└─────────────────────────────────────────────────────────────┘
```

---

## Prerequisites

1. **Telegram Bot** already configured with `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
2. **HTTPS endpoint** accessible from the internet (required by Telegram)
3. **Python 3.12+** with the `[miniapp]` extra installed

---

## Installation

### 1. Install Mini App dependencies

```bash
cd /path/to/pearlalgo-dev-ai-agents
pip install -e ".[miniapp]"
```

This installs FastAPI and Uvicorn.

### 2. Configure environment

Add to your `.env`:

```bash
# Mini App base URL (must be HTTPS, accessible from internet)
MINIAPP_BASE_URL=https://your-domain.com

# Optional: customize port/host
# MINIAPP_PORT=8080
# MINIAPP_HOST=127.0.0.1
```

---

## HTTPS Setup Options

Telegram Mini Apps **require HTTPS**. Choose one approach:

### Option A: Cloudflare Tunnel (Recommended)

Fastest setup, no DNS changes needed for testing.

1. **Install cloudflared**:
   ```bash
   # Ubuntu/Debian
   curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg
   echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
   sudo apt update && sudo apt install cloudflared
   ```

2. **Quick tunnel (testing)**:
   ```bash
   # This gives you a temporary HTTPS URL
   cloudflared tunnel --url http://localhost:8080
   ```

3. **Named tunnel (production)**:
   ```bash
   cloudflared tunnel login
   cloudflared tunnel create pearlalgo-miniapp
   cloudflared tunnel route dns pearlalgo-miniapp miniapp.yourdomain.com
   cloudflared tunnel run --url http://localhost:8080 pearlalgo-miniapp
   ```

### Option B: Your Own Domain + Caddy

If you have a domain with DNS pointing to your server:

```bash
# Install Caddy
sudo apt install -y caddy

# /etc/caddy/Caddyfile
miniapp.yourdomain.com {
    reverse_proxy localhost:8080
}

sudo systemctl reload caddy
```

### Option C: Nginx + Let's Encrypt

```bash
sudo apt install nginx certbot python3-certbot-nginx
sudo certbot --nginx -d miniapp.yourdomain.com
```

---

## Starting the Mini App Server

### Quick Start

```bash
./scripts/miniapp/start_miniapp.sh
```

### Manual Start

```bash
cd /path/to/pearlalgo-dev-ai-agents
python -m pearlalgo.miniapp.server
```

### Check Status

```bash
./scripts/miniapp/check_miniapp.sh
```

---

## BotFather Configuration

### 1. Set the Menu Button (opens Mini App from chat)

1. Open [@BotFather](https://t.me/botfather) in Telegram
2. Send `/setmenubutton`
3. Select your bot
4. Choose "Web App"
5. Enter title: `Terminal`
6. Enter URL: `https://your-miniapp-url.com`

### 2. Set the Domain (required for Web Apps)

1. Send `/setdomain` to BotFather
2. Select your bot
3. Enter your domain: `your-miniapp-url.com`

### 3. Verify Setup

Send `/terminal` to your bot — you should see an "Open Terminal" button that launches the Mini App inside Telegram.

---

## Available Commands

| Command | Description |
|---------|-------------|
| `/terminal` | Send button to open the Mini App terminal |

---

## API Endpoints

The Mini App backend exposes these endpoints:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Mini App frontend (HTML) |
| `/api/health` | GET | Health check |
| `/api/status` | GET | Agent status + data quality |
| `/api/signals` | GET | Recent signals list |
| `/api/signals/{id}` | GET | Single signal details |
| `/api/decision-room/{id}` | GET | Full Decision Room data for a signal |
| `/api/ohlcv` | GET | OHLCV data for charting |
| `/api/notes` | POST | Save note for a signal |

All `/api/*` endpoints require valid Telegram `initData` in the `X-Telegram-Init-Data` header.

---

## Security

### Authentication Flow

1. Telegram WebView provides `initData` (signed by Telegram)
2. Mini App frontend sends `initData` with each API request
3. Backend validates signature using `TELEGRAM_BOT_TOKEN`
4. Backend checks `user.id == TELEGRAM_CHAT_ID` (me-only access)

### Read-Only Policy (v1)

The Mini App is **read-only** in v1:
- No execution actions (arm/disarm/kill)
- No configuration changes
- Only viewing and note-taking

This prevents accidental actions from the mobile terminal.

---

## Troubleshooting

### Mini App won't load

1. **Check HTTPS**: Telegram requires HTTPS. Verify your URL works in a browser.
2. **Check domain in BotFather**: Must match exactly (no trailing slash).
3. **Check server is running**: `./scripts/miniapp/check_miniapp.sh`

### "Unauthorized" errors

1. **Verify TELEGRAM_CHAT_ID** in `.env` matches your Telegram user ID
2. **Verify TELEGRAM_BOT_TOKEN** is correct
3. **Check initData is being sent** (browser dev tools → Network tab)

### Charts not loading

1. **Check OHLCV endpoint**: `curl https://your-url/api/ohlcv`
2. **Verify Gateway is running**: Charts need market data

### Server won't start

1. **Install miniapp extra**: `pip install -e ".[miniapp]"`
2. **Check port availability**: `ss -tuln | grep 8080`
3. **Check logs**: Server prints to stdout

---

## Development

### Running locally (no HTTPS)

For local development, you can use ngrok or cloudflared quick tunnel:

```bash
# Terminal 1: Start Mini App server
python -m pearlalgo.miniapp.server

# Terminal 2: Expose via tunnel
cloudflared tunnel --url http://localhost:8080
```

Use the tunnel URL in BotFather for testing.

### Frontend Development

The frontend is plain HTML/JS/CSS in `src/pearlalgo/miniapp/static/`. No build step required.

To iterate quickly:
1. Edit files in `static/`
2. Refresh the Mini App in Telegram (pull down to refresh)

### Adding New Endpoints

1. Add route in `src/pearlalgo/miniapp/server.py`
2. Add schema in `src/pearlalgo/miniapp/models.py`
3. Add data fetching in `src/pearlalgo/miniapp/data.py`

---

## References

- [Telegram Web Apps Documentation](https://core.telegram.org/bots/webapps)
- [Telegram Bot Features](https://core.telegram.org/bots/features)
- [Telegram WebApp JS SDK](https://telegram.org/js/telegram-web-app.js)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

---

## Document History

| Date | Change |
|------|--------|
| 2025-12-31 | Initial Mini App guide |



