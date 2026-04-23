# All-Time Archive — Trades + Candles for Backtesting

Status: **design doc, awaiting approval to implement.**

## Problem
Today pearlalgo.io shows a shallow slice:
- **Chart**: ~7 hours on 5m TF, ~8 hours on 1m TF (`candle_cache_MNQ_*.json` are rolling 500-bar windows — everything older is discarded).
- **Trades**: 24 days of trades (`performance.json` starts 2026-03-30) but **99.5% of the PnL is estimated, not fills** ([audit F3](../audits/2026-04-23-dashboard-data-audit.md#f3)). Stats tab totals for Week/Month/All-Time are wrong.

Goal: make "all time" mean all time on the dashboard, and give backtests the same data the live agent saw.

## Two sub-problems, two solutions

### A. Trade archive (fixable in a week)
The fills are already permanent — Tradovate keeps them forever and we already sync them to `tradovate_fills.json` (1,942 fills since 2026-03-30). The `performance.json` is what's broken:
- Only 5/971 entries have `pnl_source: fill_matched`.
- The rest (966) are `estimated` — computed from signal-time TP/SL levels, not actual execution prices.
- **Fix**: re-pair all historical fills (`tradovate_fills.json`) against signals (`signals.jsonl` + `signals_archive.jsonl`), compute actual PnL per round-trip, write `performance.json.new`, atomic swap.
- Going forward: ensure the live `performance_tracker.py` always prefers broker fills over estimates when both exist.
- **Exposure**: Stats tab's `td/yday/wtd/mtd/ytd/all` slices already exist — they just become trustworthy.

### B. Candle archive (the bigger lift)
No historical store exists. The 15 `candle_cache_MNQ_*TF*_*N*.json` files on disk are rolling windows of the last N bars, overwritten on each refresh. On 5m TF with N=500 we retain ~41h; on 1m with N=500 we retain ~8h. Nothing older survives.

Design below.

---

## Candle archive — design

### Storage: SQLite at `~/var/pearl-algo/state/candles.db`

Schema (one table, multi-symbol, multi-timeframe):

```sql
CREATE TABLE candles (
  symbol   TEXT    NOT NULL,
  tf       TEXT    NOT NULL,        -- '1m', '5m', '15m', '30m', '1h', '4h', '1d'
  ts       INTEGER NOT NULL,        -- bar-open unix seconds (UTC)
  open     REAL    NOT NULL,
  high     REAL    NOT NULL,
  low      REAL    NOT NULL,
  close    REAL    NOT NULL,
  volume   REAL    NOT NULL,
  source   TEXT    NOT NULL,        -- 'ibkr_live', 'ibkr_historical', 'backfill_csv'
  inserted_at INTEGER NOT NULL,     -- when we learned about it
  PRIMARY KEY (symbol, tf, ts)
);

CREATE INDEX idx_candles_lookup ON candles(symbol, tf, ts DESC);
```

Why SQLite:
- Already the house pattern (`trades.db`, `zoho.db`, MC's `/tools/sqlite` viewer).
- Free dedup via `INSERT OR REPLACE` on the composite PK — no worry when a re-scan overlaps the live write.
- Fast range queries (`WHERE symbol=? AND tf=? AND ts BETWEEN ? AND ? ORDER BY ts`).
- Single file, easy to back up / copy to laptop for offline backtesting.
- Python `sqlite3` + `better-sqlite3` (already a MC dep per memory) both speak it.

Storage cost — ballpark for MNQ 1m bars:
- RTH only: ~390 bars/day × 250 sessions/yr = 97,500 rows/yr
- 24/7 futures: ~1,440 bars/day × 365 = 525,600 rows/yr
- Row size ≈ 80 bytes (SQLite overhead included) → **~42 MB/yr for 1m MNQ**. Trivial.
- Multi-TF (1m, 5m, 15m, 30m, 1h, 4h, 1d) ≈ ~50 MB/yr for one symbol. Still trivial.

### Source-of-truth rule: store 1m, aggregate the rest
Storing every TF duplicates data and opens consistency risk (what if 5m says something different from an aggregated 1m?). Recommendation:

- **Write 1m bars from live.** They're the atomic unit the agent already consumes.
- **Materialize 5m/15m/30m/1h/4h/1d** via SQL views or triggers that aggregate from 1m on read:
  ```sql
  CREATE VIEW candles_5m AS
    SELECT symbol, '5m' AS tf,
           (ts / 300) * 300 AS bucket_ts,
           MIN(open)  AS open,   -- not quite right — need first(open), last(close)
           MAX(high)  AS high,
           MIN(low)   AS low,
           MAX(close) AS close,  -- also not quite right
           SUM(volume) AS volume
    FROM candles WHERE tf = '1m' GROUP BY symbol, bucket_ts;
  ```
  (Real impl needs `FIRST_VALUE`/`LAST_VALUE` window fns to get proper open/close — doable in SQLite 3.25+.)
- Or simpler: pre-aggregate on write via a Python helper that runs after every 1m write, inserts into the same table at the right TF. Space cost is tiny.

Tradeoff: views are always-correct but slower on big reads; pre-aggregation is faster but has to be kept in sync. For the chart widget querying 500 × 5m bars, view-based is fine.

### Writer: hook into the live data loop
`src/pearlalgo/market_agent/service_loop.py` already fetches 1m bars from IBKR and updates the rolling caches. Add a single call inside the bar-close handler:

```python
# src/pearlalgo/market_agent/persistence/candle_archive.py
def append_bar(symbol: str, tf: str, bar: dict, source: str = "ibkr_live"):
    conn.execute(
      "INSERT OR REPLACE INTO candles VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
      (symbol, tf, bar["time"], bar["open"], bar["high"], bar["low"],
       bar["close"], bar["volume"], source, int(time.time()))
    )
```

Cost to live loop: one insert per closed bar = negligible (<1ms).

### Backfill: one-shot from IBKR historical
IBKR's `reqHistoricalData` returns up to ~180 days of 1m bars (rate limited, requires pacing). One-time script to fill in the past:

```bash
# New: scripts/ops/backfill-candles.py
python scripts/ops/backfill-candles.py --symbol MNQ --tf 1m --lookback-days 180
```

Rate limits will force pacing (~1 request per 10s) — 180 days in 1m chunks is maybe a few hours to run. Safe to run overnight. Marks rows `source='ibkr_historical'` so we can distinguish later.

Alternative sources worth knowing if IBKR is a pain:
- **Databento** ($$) — CME futures bars, can pull years in seconds
- **Polygon.io** (equities) — cheap, CME futures coming
- **CSV dump from a broker** — free, slower workflow
- **Tradovate** — broker only, no historical bar API afaik

### Reader: new API endpoint + chart wiring

```
GET /api/candles?symbol=MNQ&tf=5m&from=1776000000&to=1776543200&limit=1000
→ { candles: [{time, open, high, low, close, volume}, ...] }
```

Existing `useChartManager.ts` already consumes arrays of this shape. The chart currently loads once from the in-memory cache at page load — we extend it so **dragging the chart left past the leftmost loaded bar triggers a fetch of older bars from the archive.** TradingView-lightweight-charts ships `onTimeRangeChange` for exactly this.

### Migration path (how existing caches become the archive)
The 15 rolling-window JSON caches we have now can be ingested once on first run:
```bash
python scripts/ops/ingest-existing-caches.py
# reads candle_cache_MNQ_1m_500.json etc, dedupes into candles table
```
Gives us a starting corpus of ~8–41 hours per TF (depending on which file) without touching IBKR. Useful sanity check before the big backfill.

---

## Implementation phases

| Phase | Deliverable | Est |
|---|---|---|
| 1 | **SQLite schema + write path** — create `candles.db`, hook `append_bar` into service_loop on bar-close, ingest existing caches. Live data now archived. | 3–4h |
| 2 | **Read endpoint** — `GET /api/candles`, return JSON in chart's expected shape, validate against a small set of queries. | 1–2h |
| 3 | **Chart lazy-load on pan-left** — `onTimeRangeChange` handler in `useChartManager.ts`, fetch older bars when leftmost visible bar < leftmost loaded bar. | 2–3h |
| 4 | **IBKR historical backfill** — one-shot script, rate-limited, idempotent (safe to re-run), tagged as `ibkr_historical`. | 3–5h (plus the actual data-fetch time, which runs unattended) |
| 5 | **Fix F3 from audit** — re-pair `tradovate_fills.json` × `signals.jsonl` to rebuild `performance.json` with `fill_matched` PnL everywhere broker data exists. Then the dashboard's Stats tab becomes trustworthy for all periods. | 2–3h |
| 6 | **(Optional) MC SQLite viewer registration** — register `candles.db` with MC so `/tools/sqlite` can browse it. | 15 min |

Total: ~1–2 days of focused work for a working end-to-end, plus IBKR's pacing for the actual historical pull.

## Non-goals (explicit)

- **Tick-level storage.** Bars are 100× smaller and sufficient for every indicator the pinescript strategy uses (EMA, RSI, VWAP, BB, ATR). Revisit only if we add a strategy that needs finer granularity.
- **Multi-instrument expansion right now.** Schema supports it, but the first cut stays MNQ. Symbols can be added one at a time with `--symbol NQ` backfill runs.
- **Order-book / DOM data.** Not needed for the current strategies.
- **"Make it real-time via websocket push".** Chart already polls 10s which is fine; websocket can come later if needed.

## Open questions (for you)

1. **How far back is "all time"?** IBKR free tier gives 180 days of 1m reliably. If you want years, we need a paid data provider (Databento ~$0–$30/mo for MNQ depending on tier). My lean: start at 180d, see if it's enough for the backtesting you have in mind.
2. **Are other symbols coming?** NQ, ES, CL, etc. Design supports them natively; just affects how much backfill to budget.
3. **Does backtesting live on the Beelink (cheaper, always-on) or on the Mac (faster iteration)?** This affects whether we expose the candles via HTTP or just copy the .db file around.
4. **Priority order** — which of phases 1–5 above do you want first? My recommendation: **5 → 1 → 2 → 3 → 4.** Phase 5 fixes the trust issue with existing 24 days of data (visible win). Then build the new archive.

## What I can do next turn without more input

If you want something ticking, Phase 5 (re-pair fills → rebuild performance.json) is the highest leverage: it's ~3h, uses data we already have locally, makes the Stats tab honest, and is a prerequisite for any "all time trades" claim being accurate. I can start there without any of the open questions resolved.

Phases 1–4 (candle archive) should wait on question #1 (how far back) since it determines which data source to wire.
