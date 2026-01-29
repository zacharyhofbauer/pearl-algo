# Live Main Chart + Telegram Mini App

This repo’s **canonical chart** is the web-based **Live Main Chart** (`live-chart/`).

It powers:
- A **browser dashboard** (local or deployed)
- A **Telegram dashboard screenshot** (`exports/dashboard_telegram_latest.png`)
- A **Telegram Mini App** (in-app “web_app” view)

![Telegram dashboard](assets/telegram-dashboard.png)

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

## Telegram Mini App (“Open App” stays inside Telegram)

Telegram requires a **public HTTPS URL** (BotFather rejects `localhost`).

![BotFather requires HTTPS](assets/botfather-miniapp-url.png)

### 1) Get a public HTTPS URL

Options:
- **Production**: deploy `live-chart/` to Vercel/Netlify/Cloud Run (HTTPS by default).
- **Dev**: use a tunnel (HTTPS) to your local chart.

Example (Cloudflare Tunnel):

```bash
cloudflared tunnel --url http://localhost:3001
```

### 2) Configure BotFather

In [@BotFather](https://t.me/botfather):
- Enable your bot’s Mini App
- Set the Mini App URL to your **public HTTPS** chart URL

### 3) Show a “📈 Live” button inside the dashboard

Set:
- **`PEARL_MINI_APP_URL`** = the same public HTTPS URL

The main menu will show a **📈 Live** button that opens the chart **inside Telegram** (no external browser).

---

## API server CORS (for deployments)

If your chart UI runs on a public domain, the API server must allow that origin.

Set:
- **`PEARL_LIVE_CHART_ORIGINS`** (comma-separated), e.g.

```bash
export PEARL_LIVE_CHART_ORIGINS="https://your-live-chart.example.com"
```

Also ensure the UI points at the right API:
- In `live-chart/`, set `NEXT_PUBLIC_API_URL` to your deployed API (HTTPS).

