# IBKR Market Data Subscription (Error 354) — Canonical Guide

This is the **canonical** reference for resolving **IBKR Error 354** (“Requested market data is not subscribed”) for this repository.

This agent is **signal-only**. It requires market data (Level 1) to produce timely signals and to avoid stale/historical fallbacks.

---

## When to use this guide

Use this guide if any of the following are true:

- You see **Error 354** in Gateway/API logs while the market is open.
- `scripts/testing/smoke_test_ibkr.py` reports subscription/entitlement errors.
- The agent reports **stale data** while the market is open.
- The latest bar returns `NaN`/`None` for prices from live data.

---

## Fast triage checklist (do this first)

### 1) Confirm the market is actually open

For **CME futures (MNQ/NQ)**, market hours differ from equities:

- **ETH**: Sun 18:00 ET → Fri 17:00 ET
- **Maintenance break**: Mon–Thu 17:00–18:00 ET

If the market is closed, **Error 354 can be expected**. In that case the agent may fall back to historical bars (which can be stale by hours/days).

### 2) Confirm Gateway is up and API is listening

From the repo root:

```bash
./scripts/gateway/gateway.sh status
```

You should see:

- Gateway process **RUNNING**
- API port **4002 LISTENING**

### 3) Confirm you are using the intended port / client IDs

Canonical defaults (see `docs/PROJECT_SUMMARY.md`):

- `IBKR_PORT=4002`
- `IBKR_CLIENT_ID=10`
- `IBKR_DATA_CLIENT_ID=11`

If you change these, update `.env` consistently.

---

## Fix steps (market is open, Error 354 persists)

### Step A — Verify subscription is active

In the **IBKR Client Portal**:

- Go to **Settings → Account Settings → Market Data Subscriptions**
- Ensure a CME futures Level 1 subscription is active (commonly **“CME Real-Time (NP,L1)”**)

Portal link: [IBKR Client Portal](https://www.interactivebrokers.com/portal/)

### Step B — Complete “Market Data API Acknowledgement” (common root cause)

In the same portal area, look for:

- **Market Data API Acknowledgement**
- Click **Read and Acknowledge** / **Sign** (wording varies)

Also check:

- **Settings → Trading Permissions → API User Activity Certification**

If anything is pending, complete it and wait a few minutes for propagation.

### Step C — Restart Gateway after changes

From the repo root:

```bash
./scripts/gateway/gateway.sh stop
sleep 5
./scripts/gateway/gateway.sh start
```

### Step D — Validate via smoke test

From the repo root:

```bash
python3 scripts/testing/smoke_test_ibkr.py
```

If the smoke test still reports Error 354 while the market is open, return to **Step A/B** and verify the subscription is **active + acknowledged for API**.

---

## Related issue: Error 162 (TWS session conflict)

If you see **Error 162** (TWS session conflict / “different IP”):

- You cannot run **TWS** and **Gateway** simultaneously from different IPs.
- Close / fully disconnect TWS everywhere (desktop, laptop, remote sessions), wait ~60 seconds, then restart Gateway.

Helper:

```bash
./scripts/gateway/gateway.sh tws-conflict
```

---

## Notes on fallbacks (what “working” can still mean)

This codebase can fall back to historical bars when live data is unavailable. That can keep the system running, but it is **not equivalent to live data**:

- Signals may be delayed.
- “Latest price” may be stale.
- Risk calculations may be based on out-of-date bars.

Treat “historical fallback” as a **degradation mode**, not a fix.

---

## References

- `docs/GATEWAY.md` — operational gateway setup and lifecycle
- `docs/PROJECT_SUMMARY.md` — architecture + configuration source of truth




