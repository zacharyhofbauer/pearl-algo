# Live Main Chart + Telegram Mini App

This repo's **canonical chart** is the web-based **Live Main Chart** (`live-chart/`).

It powers:
- A **browser dashboard** (local or deployed)
- A **Telegram dashboard screenshot** (`exports/dashboard_telegram_latest.png`)
- A **Telegram Mini App** (in-app "web_app" view)

![Telegram dashboard](assets/telegram-dashboard.png)

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

## Chart Features

| Feature | Description |
|---------|-------------|
| **Timeframe Selector** | Switch between 1m, 5m, 15m, 1h (header buttons) |
| **Dynamic Viewport** | Bar count adjusts to screen width automatically |
| **Fit All / Go Live** | Quick buttons (top-right) to fit all data or jump to live edge |
| **Indicators** | EMA9 (cyan), EMA21 (yellow), VWAP (purple dashed) |
| **RSI Panel** | Separate RSI(14) panel with overbought/oversold lines |
| **Trade Markers** | Entry arrows and Exit dots with hover tooltips showing signal details |

---

## Local run (dev)

Start API server + Next.js chart:

```bash
./scripts/live-chart/start.sh --market NQ
```

Open the chart:
- `http://localhost:3001`

Stop:

```bash
./scripts/live-chart/stop.sh
```

---

## Telegram dashboard screenshot (optional)

The Market Agent Service + Telegram Command Handler will attach a PNG screenshot stored at:

- `data/agent_state/<MARKET>/exports/dashboard_telegram_latest.png`

Screenshot capture requirements:

```bash
pip install playwright
playwright install chromium
```

Runtime env:
- **`PEARL_LIVE_CHART_URL`**: URL that Playwright will screenshot (default `http://localhost:3001`)

---

## Telegram Mini App ("Open App" stays inside Telegram)

Telegram requires a **public HTTPS URL** (BotFather rejects `localhost`).

![BotFather requires HTTPS](assets/botfather-miniapp-url.png)

### Option A: Quick Tunnel (ephemeral, for testing)

```bash
cloudflared tunnel --url http://localhost:3001
```

This gives you a random URL like `https://xxx-yyy-zzz.trycloudflare.com` (changes each run).

### Option B: Named Tunnel (persistent, for production)

A named tunnel gives you a **persistent HTTPS URL** that survives restarts.

#### 1) Install cloudflared

```bash
# Download
curl -L -o cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared
sudo mv cloudflared /usr/local/bin/

# Verify
cloudflared --version
```

#### 2) Login and create tunnel

```bash
# Login (opens browser)
cloudflared tunnel login

# Create named tunnel
cloudflared tunnel create pearlalgo-miniapp

# Route DNS (requires domain in Cloudflare)
cloudflared tunnel route dns pearlalgo-miniapp your-domain.com
cloudflared tunnel route dns pearlalgo-miniapp www.your-domain.com
```

#### 3) Create config file

```bash
# Get your tunnel ID from the create output
# Credentials are saved to ~/.cloudflared/<tunnel-id>.json

cat > ~/.cloudflared/config.yml << 'EOF'
tunnel: pearlalgo-miniapp
credentials-file: /home/pearlalgo/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: your-domain.com
    service: http://localhost:3001
  - hostname: www.your-domain.com
    service: http://localhost:3001
  - service: http_status:404
EOF
```

#### 4) Run the tunnel

```bash
# Foreground (for testing)
cloudflared tunnel run pearlalgo-miniapp

# Background (for production)
nohup cloudflared tunnel run pearlalgo-miniapp > /dev/null 2>&1 &
```

#### 5) (Optional) Run as systemd service

```bash
sudo cloudflared service install
sudo systemctl enable cloudflared
sudo systemctl start cloudflared
```

---

## Configure BotFather

In [@BotFather](https://t.me/botfather):
1. Select your bot
2. Go to **Bot Settings** → **Menu Button** → **Configure Menu Button**
3. Set URL to your **public HTTPS** chart URL (e.g., `https://your-domain.com`)

Or use the Mini App feature:
1. Go to **Bot Settings** → **Configure Mini App**
2. Enable Mini App
3. Set the Mini App URL

### Show a "📈 Live" button inside the dashboard

Set:
- **`PEARL_MINI_APP_URL`** = the same public HTTPS URL

The main menu will show a **📈 Live** button that opens the chart **inside Telegram** (no external browser).

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PEARL_LIVE_CHART_URL` | `http://localhost:3001` | URL for Playwright screenshot capture |
| `PEARL_MINI_APP_URL` | *(unset)* | Public HTTPS URL shown as "📈 Live" button |
| `PEARL_API_PORT` | `8000` | API server port |
| `PEARL_CHART_PORT` | `3001` | Chart web interface port |
| `PEARL_LIVE_CHART_ORIGINS` | *(unset)* | CORS origins for API (comma-separated) |

---

## API server CORS (for deployments)

If your chart UI runs on a public domain, the API server must allow that origin.

Set:
- **`PEARL_LIVE_CHART_ORIGINS`** (comma-separated), e.g.

```bash
export PEARL_LIVE_CHART_ORIGINS="https://your-domain.com,https://www.your-domain.com"
```

Also ensure the UI points at the right API:
- In `live-chart/`, set `NEXT_PUBLIC_API_URL` to your deployed API (HTTPS).

---

## Troubleshooting

### "No ingress rules" warning
If you see `No ingress rules were defined`, your `~/.cloudflared/config.yml` is missing or misconfigured. Create it as shown above.

### Tunnel not connecting
Check that:
1. `cloudflared tunnel login` was completed
2. Credentials file exists at the path in config.yml
3. DNS routes are configured (`cloudflared tunnel route dns`)

### Chart shows "No Data"
Ensure:
1. Market Agent is running (`./scripts/lifecycle/check_agent_status.sh --market NQ`)
2. IBKR Gateway is connected (`./scripts/gateway/gateway.sh status`)
3. API server is running (check `http://localhost:8000/health`)
