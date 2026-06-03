"""Tests for the TradingView -> Discord bridge (alerts/tv_to_discord.py).

Covers the pure formatting + dedup logic and the retry/backoff delivery path with a fake
HTTP session (no network, no TradingView, no Discord).
"""
from __future__ import annotations

import pytest

from alerts import tv_to_discord as t


def _buy():
    return {"strat": "mnq-rth-long-bias", "v": 2, "action": "BUY", "symbol": "MNQ1!", "tf": "5",
            "bar_time": "2026-06-03 10:15 ET", "entry": 21850.25, "stop": 21835.0, "target": 21880.75,
            "atr": 10.17, "rr": 2.0, "risk_usd_per_contract": 30.5, "contracts": 1,
            "max_contracts": 5, "trades_today": 1, "reason": "EMA9>21 cross, above VWAP"}


# ── build_embed ────────────────────────────────────────────────────────────────
def test_embed_buy_has_levels_and_green():
    e = t.build_embed(_buy())
    assert "BUY MNQ1!" in e["title"] and e["color"] == 0x2ECC71
    names = {f["name"] for f in e["fields"]}
    assert {"Entry", "Stop", "Target", "ATR", "R:R", "Risk/contract"} <= names
    assert "MFF" in e["footer"]["text"] and "trade #1" in e["footer"]["text"]
    assert "above VWAP" in e["description"]


def test_embed_sell_is_red():
    p = _buy(); p["action"] = "SELL"
    assert t.build_embed(p)["color"] == 0xE74C3C


def test_embed_daily_stop():
    e = t.build_embed({"strat": "x", "action": "DAILY_STOP", "symbol": "MNQ1!",
                       "reason": "max trades/day hit", "daily_pnl_usd": -42.0, "trades_today": 3})
    assert "DAILY STOP" in e["title"] and e["color"] == 0xE67E22
    assert "max trades/day hit" in e["description"] and "-42" in e["description"]


def test_embed_v1_minimal_payload_does_not_crash():
    # Old v1 payload: only action/symbol/entry/stop/target/max_contracts.
    e = t.build_embed({"strat": "mnq-rth-long-bias", "action": "BUY", "symbol": "MNQ",
                       "entry": 100.0, "stop": 99.0, "target": 102.0, "max_contracts": 5})
    names = {f["name"] for f in e["fields"]}
    assert {"Entry", "Stop", "Target"} <= names      # present
    assert "ATR" not in names                          # absent fields simply omitted


# ── dedup ──────────────────────────────────────────────────────────────────────
def test_dedup_drops_repeat_within_ttl():
    t._seen.clear()
    k = t.dedup_key(_buy())
    assert t._is_duplicate(k, now=1000.0) is False     # first time
    assert t._is_duplicate(k, now=1000.5) is True       # repeat within TTL
    assert t._is_duplicate(k, now=1000.0 + t.DEDUP_TTL_SEC + 1) is False  # expired -> allowed again


def test_dedup_key_distinguishes_bars():
    a, b = _buy(), _buy()
    b["bar_time"] = "2026-06-03 10:20 ET"
    assert t.dedup_key(a) != t.dedup_key(b)


# ── delivery: retry/backoff (stub the _http_post seam) ───────────────────────────
class _Poster:
    """Returns queued (status, text) tuples and records the bodies POSTed."""
    def __init__(self, results):
        self._results, self.calls = list(results), []

    def __call__(self, url, body):
        self.calls.append(body)
        return self._results.pop(0)


def test_post_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(t, "DISCORD_WEBHOOK_URL", "https://example/webhook")
    monkeypatch.setattr(t._time, "sleep", lambda *a: None)
    poster = _Poster([(429, '{"retry_after": 0.01}'), (204, "")])
    monkeypatch.setattr(t, "_http_post", poster)
    out = t.post_to_discord({"title": "x"})
    assert out["delivered"] is True and out["attempt"] == 2
    assert len(poster.calls) == 2 and b"embeds" in poster.calls[0]


def test_post_raises_after_exhausting_retries(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(t, "DISCORD_WEBHOOK_URL", "https://example/webhook")
    monkeypatch.setattr(t._time, "sleep", lambda *a: None)
    monkeypatch.setattr(t, "_http_post", _Poster([(500, ""), (500, ""), (500, "")]))
    with pytest.raises(HTTPException):
        t.post_to_discord({"title": "x"})


def test_post_without_webhook_raises(monkeypatch):
    from fastapi import HTTPException
    monkeypatch.setattr(t, "DISCORD_WEBHOOK_URL", "")
    with pytest.raises(HTTPException):
        t.post_to_discord({"title": "x"})


# ── /tv endpoint (drives the real ASGI app in-process via TestClient) ─────────────
from fastapi.testclient import TestClient   # noqa: E402  (local import: optional dep)


def _client(monkeypatch, results=((204, ""),), secret=""):
    monkeypatch.setattr(t, "DISCORD_WEBHOOK_URL", "https://example/webhook")
    monkeypatch.setattr(t, "TV_SHARED_SECRET", secret)
    monkeypatch.setattr(t._time, "sleep", lambda *a: None)
    poster = _Poster(list(results))
    monkeypatch.setattr(t, "_http_post", poster)
    t._seen.clear()
    return TestClient(t.app), poster


def test_endpoint_delivers_buy(monkeypatch):
    client, poster = _client(monkeypatch)
    r = client.post("/tv", json=_buy())
    assert r.status_code == 200 and r.json()["delivered"] is True
    assert len(poster.calls) == 1 and b"BUY MNQ1!" in poster.calls[0]


def test_endpoint_rejects_bad_secret(monkeypatch):
    client, poster = _client(monkeypatch, secret="topsecret")
    r = client.post("/tv", json={**_buy(), "secret": "wrong"})
    assert r.status_code == 401 and len(poster.calls) == 0


def test_endpoint_dedupes_duplicate(monkeypatch):
    client, poster = _client(monkeypatch, results=((204, ""), (204, "")))
    r1 = client.post("/tv", json=_buy())
    r2 = client.post("/tv", json=_buy())
    assert r1.json().get("delivered") is True
    assert r2.json().get("deduped") is True
    assert len(poster.calls) == 1   # duplicate not delivered


def test_endpoint_raw_text_fallback(monkeypatch):
    client, poster = _client(monkeypatch)
    r = client.post("/tv", content="hello world not json")
    assert r.status_code == 200 and len(poster.calls) == 1
