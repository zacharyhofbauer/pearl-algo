# alerts/ — TradingView webhook → Discord

Delivers Pine alerts to your phone so you can place the trade by hand. Two modes:

## 1. Zero-server (start here, for validation)

No code, no tunnel. In TradingView's alert dialog:

- **Webhook URL** = a Discord channel webhook (Channel → Edit → Integrations → Webhooks → New).
- **Message** = Discord JSON, e.g.
  `{"content":"🟢 BUY MNQ @ {{close}} — RTH long, max 5, place by hand"}`

That's enough to validate the loop (alert → phone → manual order). You lose structured
journaling, which is fine until the edge is proven.

## 2. Structured receiver (when you want journaling)

`tv_to_discord.py` (FastAPI) parses the Pine JSON payload, posts a clean Discord message, and
appends every signal to `journal/signals.jsonl` so the journal can reconcile what *fired* against
what you *traded*.

```bash
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
TV_SHARED_SECRET="$(openssl rand -hex 16)" \
    uvicorn alerts.tv_to_discord:app --host 0.0.0.0 --port 8009
```

Then make port 8009 reachable from TradingView and set that `/tv` URL as the alert webhook:

- **Beelink + Tailscale** — the Beelink is already always-on; expose via Tailscale or a
  `cloudflared` tunnel (tunnel infra notes live in the xprs-hub webhook design).
- **Mission Control** — MC already has a hardened webhook receiver
  (`pearl-mission-control/src/app/api/webhooks/route.ts`) if you'd rather route through it.

TradingView can't send custom headers, so auth is a shared secret inside the JSON body
(`"secret":"..."`), checked by `TV_SHARED_SECRET`.

## Discord placement

Land alerts in a dedicated channel (e.g. `#mnq-signals`) so they don't mix with bot status.
The existing OpenClaw/Discord setup already carries pearl notifications — this is just one more
webhook sink.
