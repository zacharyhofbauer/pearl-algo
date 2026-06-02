#!/usr/bin/env python3
"""Minimal TradingView-webhook -> Discord bridge for the manual trading model.

TradingView posts the Pine strategy's JSON alert here; this formats a clean Discord
message and (optionally) appends the signal to a JSONL log so the journal can reconcile
manual fills against the signals that fired.

This is intentionally tiny. The manual model needs almost no code — if you don't need
journaling yet, you can skip this entirely and point TradingView's webhook straight at a
Discord channel webhook (see pine/README.md, "Zero-server").

Run:
    pip install fastapi uvicorn requests        # already-present deps in this repo
    DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
    TV_SHARED_SECRET="something-long" \
        uvicorn alerts.tv_to_discord:app --host 0.0.0.0 --port 8009

Then expose port 8009 to TradingView (Tailscale on the Beelink, or a cloudflared tunnel)
and set that URL as the alert webhook. TradingView cannot send custom headers, so auth is
a shared secret carried inside the JSON body ("secret": "...").
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import FastAPI, HTTPException, Request

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
TV_SHARED_SECRET = os.environ.get("TV_SHARED_SECRET", "")
SIGNAL_LOG = Path(os.environ.get("SIGNAL_LOG", "journal/signals.jsonl"))

app = FastAPI(title="TradingView -> Discord (manual model)")


def _format(payload: dict) -> str:
    action = str(payload.get("action", "?")).upper()
    emoji = {"BUY": "🟢", "SELL": "🔴"}.get(action, "⚪")
    sym = payload.get("symbol", "?")
    entry, stop, target = payload.get("entry"), payload.get("stop"), payload.get("target")
    maxc = payload.get("max_contracts", 5)
    return (
        f"{emoji} **{action} {sym}** ({payload.get('strat', 'manual')})\n"
        f"entry `{entry}`  stop `{stop}`  target `{target}`\n"
        f"_max {maxc} MNQ • RTH only • place by hand on MFF_"
    )


@app.get("/health")
def health() -> dict:
    return {"ok": True, "discord_configured": bool(DISCORD_WEBHOOK_URL)}


@app.post("/tv")
async def tradingview(request: Request) -> dict:
    raw = (await request.body()).decode("utf-8", "replace").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # TradingView can send plain text too; wrap it so nothing is lost.
        payload = {"action": "ALERT", "strat": "raw", "text": raw}

    if TV_SHARED_SECRET and payload.get("secret") != TV_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")
    payload.pop("secret", None)

    # Append to the signal log for journal reconciliation (best-effort).
    try:
        SIGNAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SIGNAL_LOG.open("a") as fh:
            fh.write(json.dumps({"ts": datetime.now(timezone.utc).isoformat(), **payload}) + "\n")
    except OSError:
        pass

    if not DISCORD_WEBHOOK_URL:
        raise HTTPException(status_code=500, detail="DISCORD_WEBHOOK_URL not set")

    content = payload.get("text") if payload.get("strat") == "raw" else _format(payload)
    resp = requests.post(DISCORD_WEBHOOK_URL, json={"content": content}, timeout=10)
    resp.raise_for_status()
    return {"delivered": True}
