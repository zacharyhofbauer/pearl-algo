#!/usr/bin/env python3
"""TradingView-webhook -> Discord bridge for the manual MNQ model (v2).

TradingView posts the Pine strategy's JSON alert here; this builds a rich Discord embed,
retries on rate-limit/5xx, de-dups TradingView's retry-storms, and appends every signal to
a JSONL log so the journal can reconcile manual fills against the signals that fired.

⚠️  The signal behind these alerts FAILED cost-viability validation (see
docs/audits/validation-trial-ledger.md). This bridge is plumbing — it does not make the
strategy profitable. Paper-trade the gate before risking the MFF funded account.

Run (stdlib-only HTTP — no `requests`; needs only fastapi + uvicorn to serve):
    pip install fastapi uvicorn
    DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/..." \
    TV_SHARED_SECRET="$(openssl rand -hex 16)" \
        uvicorn alerts.tv_to_discord:app --host 0.0.0.0 --port 8009

Then expose port 8009 to TradingView (Beelink+Tailscale or a cloudflared tunnel) and set the
`/tv` URL as the alert webhook. TradingView cannot send custom headers, so auth is a shared
secret carried inside the JSON body ("secret": "..."), checked against TV_SHARED_SECRET.

Self-test the formatting + delivery path without TradingView:
    python -m alerts.tv_to_discord --selftest        # prints the embed it would post
"""
from __future__ import annotations

import json
import os
import sys
import time as _time
import urllib.error
import urllib.request
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")
TV_SHARED_SECRET = os.environ.get("TV_SHARED_SECRET", "")
SIGNAL_LOG = Path(os.environ.get("SIGNAL_LOG", "journal/signals.jsonl"))
DEDUP_TTL_SEC = float(os.environ.get("TV_DEDUP_TTL_SEC", "120"))   # drop identical re-posts within this window
HTTP_TIMEOUT = float(os.environ.get("TV_HTTP_TIMEOUT", "10"))
MAX_RETRIES = int(os.environ.get("TV_MAX_RETRIES", "3"))

app = FastAPI(title="TradingView -> Discord (manual MNQ model, v2)")


def _http_post(url: str, body: bytes) -> tuple[int, str]:
    """POST JSON via stdlib urllib. Returns (status, text). Seam for tests to stub."""
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # 4xx/5xx carry a body (e.g. 429 retry_after)
        return e.code, e.read().decode("utf-8", "replace")

# Action -> (emoji, embed color). Discord embed colors are ints.
_ACTION_STYLE = {
    "BUY":        ("🟢", 0x2ECC71),
    "SELL":       ("🔴", 0xE74C3C),
    "DAILY_STOP": ("🛑", 0xE67E22),
}
_DEFAULT_STYLE = ("⚪", 0x95A5A6)


def _num(v: Any) -> Optional[str]:
    """Format a numeric field for display, or None if absent/non-numeric."""
    if v is None:
        return None
    try:
        return f"{float(v):,.2f}"
    except (TypeError, ValueError):
        return str(v)


def build_embed(payload: dict) -> dict:
    """Pure: turn a parsed alert payload into a Discord embed dict. No network."""
    action = str(payload.get("action", "ALERT")).upper()
    emoji, color = _ACTION_STYLE.get(action, _DEFAULT_STYLE)
    sym = payload.get("symbol", "?")
    strat = payload.get("strat", "manual")

    if action == "DAILY_STOP":
        reason = payload.get("reason", "daily stop")
        pnl = _num(payload.get("daily_pnl_usd"))
        desc = f"**{reason}**"
        if pnl is not None:
            desc += f"\nrealized today: `${pnl}`  •  trades: `{payload.get('trades_today', '?')}`"
        return {
            "title": f"{emoji} DAILY STOP — {sym}",
            "description": desc,
            "color": color,
            "footer": {"text": f"{strat} • stop trading for the day (MFF discipline)"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    # Directional BUY/SELL entry.
    fields = []
    for label, key, inline in (
        ("Entry", "entry", True), ("Stop", "stop", True), ("Target", "target", True),
        ("ATR", "atr", True), ("R:R", "rr", True), ("Risk/contract", "risk_usd_per_contract", True),
    ):
        val = payload.get(key)
        if val is None:
            continue
        shown = _num(val)
        if key in ("risk_usd_per_contract",):
            shown = f"${shown}"
        fields.append({"name": label, "value": f"`{shown}`", "inline": inline})

    contracts = payload.get("contracts")
    maxc = payload.get("max_contracts", 5)
    size_line = f"{contracts}" if contracts is not None else "?"
    foot = f"{strat} • size {size_line}/max {maxc} MNQ • RTH • place by hand on MFF"
    if payload.get("trades_today") is not None:
        foot = f"trade #{payload['trades_today']} today • " + foot

    # Reason: old payload uses "reason"; the mnq-hourly payload uses "trigger"
    # (breakout/pullback). Regime + exec/regime timeframes are mnq-hourly extras.
    desc_bits = []
    reason = payload.get("reason") or payload.get("trigger")
    if reason:
        desc_bits.append(str(reason))
    if payload.get("regime"):
        desc_bits.append(f"regime {payload['regime']}")
    if payload.get("bar_time"):
        desc_bits.append(f"bar: {payload['bar_time']}")
    tf = payload.get("tf") or payload.get("exec_tf")
    if tf:
        tf_txt = f"tf {tf}"
        if payload.get("regime_tf"):
            tf_txt += f"/{payload['regime_tf']}"
        desc_bits.append(tf_txt)

    return {
        "title": f"{emoji} {action} {sym}",
        "description": "  •  ".join(desc_bits) if desc_bits else None,
        "color": color,
        "fields": fields,
        "footer": {"text": foot},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def dedup_key(payload: dict) -> str:
    """Stable key for a signal so TradingView retry-duplicates are dropped."""
    return "|".join(str(payload.get(k, "")) for k in ("strat", "action", "symbol", "bar_time", "entry"))


# Bounded LRU of recently-seen keys -> monotonic timestamp.
_seen: "OrderedDict[str, float]" = OrderedDict()


def _is_duplicate(key: str, now: float) -> bool:
    # Evict expired entries first.
    while _seen and next(iter(_seen.values())) < now - DEDUP_TTL_SEC:
        _seen.popitem(last=False)
    if key in _seen and _seen[key] >= now - DEDUP_TTL_SEC:
        return True
    _seen[key] = now
    _seen.move_to_end(key)
    while len(_seen) > 2048:
        _seen.popitem(last=False)
    return False


def post_to_discord(embed: dict, *, content: Optional[str] = None) -> dict:
    """Post an embed to Discord with retry/backoff on 429 + 5xx. Returns a small status dict."""
    if not DISCORD_WEBHOOK_URL:
        raise HTTPException(status_code=500, detail="DISCORD_WEBHOOK_URL not set")
    body: dict[str, Any] = {"embeds": [embed]}
    if content:
        body["content"] = content
    data = json.dumps(body).encode("utf-8")
    last_status = None
    for attempt in range(1, MAX_RETRIES + 1):
        status, text = _http_post(DISCORD_WEBHOOK_URL, data)
        last_status = status
        if status < 300:
            return {"delivered": True, "status": status, "attempt": attempt}
        if status == 429:
            try:
                wait = float(json.loads(text).get("retry_after", 1.0))
            except (ValueError, KeyError, AttributeError):
                wait = 1.0
            _time.sleep(min(wait, 5.0))
            continue
        if 500 <= status < 600:
            _time.sleep(min(2 ** attempt * 0.25, 5.0))
            continue
        # 4xx other than 429: not retryable.
        raise HTTPException(status_code=502, detail=f"Discord rejected ({status}): {text[:200]}")
    raise HTTPException(status_code=502, detail=f"Discord delivery failed after {MAX_RETRIES} tries (last {last_status})")


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "discord_configured": bool(DISCORD_WEBHOOK_URL),
        "auth_required": bool(TV_SHARED_SECRET),
        "dedup_ttl_sec": DEDUP_TTL_SEC,
        "recent_keys": len(_seen),
    }


@app.post("/tv")
async def tradingview(request: Request) -> dict:
    raw = (await request.body()).decode("utf-8", "replace").strip()
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        # TradingView can send plain text; wrap it so nothing is lost.
        payload = {"action": "ALERT", "strat": "raw", "text": raw}

    if TV_SHARED_SECRET and payload.get("secret") != TV_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")
    payload.pop("secret", None)

    # Append to the signal log for journal reconciliation (best-effort).
    try:
        SIGNAL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with SIGNAL_LOG.open("a") as fh:
            fh.write(json.dumps({"received_at": datetime.now(timezone.utc).isoformat(), **payload}) + "\n")
    except OSError:
        pass

    # Drop TradingView retry-duplicates (still 200 so TV doesn't retry-storm).
    key = dedup_key(payload)
    if payload.get("strat") != "raw" and _is_duplicate(key, _time.monotonic()):
        return {"delivered": False, "deduped": True}

    if payload.get("strat") == "raw":
        return post_to_discord({"description": payload.get("text", "")[:4000], "color": _DEFAULT_STYLE[1]})
    return post_to_discord(build_embed(payload))


def _selftest() -> int:
    """Render embeds for sample payloads without any network call."""
    samples = [
        {"strat": "mnq-rth-long-bias", "v": 2, "action": "BUY", "symbol": "MNQ1!", "tf": "5",
         "bar_time": "2026-06-03 10:15 ET", "entry": 21850.25, "stop": 21835.0, "target": 21880.75,
         "atr": 10.17, "rr": 2.0, "risk_pts": 15.25, "risk_usd_per_contract": 30.5,
         "risk_usd_total": 30.5, "contracts": 1, "max_contracts": 5, "trades_today": 1,
         "reason": "EMA9>21 cross, above VWAP"},
        {"strat": "mnq-rth-long-bias", "v": 2, "action": "DAILY_STOP", "symbol": "MNQ1!",
         "reason": "max trades/day hit — stop for the day", "daily_pnl_usd": -42.0, "trades_today": 3},
        # mnq-hourly v1 payload (trigger/regime/exec_tf/regime_tf instead of reason/tf).
        {"strat": "mnq-hourly", "v": 1, "status": "Candidate", "action": "SELL", "symbol": "MNQ1!",
         "exec_tf": "60", "regime_tf": "240", "bar_time": "2026-06-19 10:00 ET", "regime": "DOWN",
         "trigger": "pullback", "entry": 30592.75, "stop": 30625.0, "target": 30510.0, "atr": 40.0,
         "rr": 2.5, "risk_pts": 32.75, "risk_usd_per_contract": 65.5, "risk_usd_total": 65.5,
         "contracts": 1, "max_contracts": 5, "trades_today": 2},
    ]
    for s in samples:
        print(json.dumps(build_embed(s), indent=2))
        print(f"  dedup_key: {dedup_key(s)}")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print("Run via uvicorn (see module docstring) or with --selftest.", file=sys.stderr)
    raise SystemExit(1)
