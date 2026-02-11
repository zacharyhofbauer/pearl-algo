# Audit System

> Full audit trail for all trading activity, system events, and account reconciliation.

---

## 1. Overview

The audit system captures every meaningful event in PearlAlgo's lifecycle — from signal generation through trade execution to daily equity snapshots. All events are stored in a single SQLite database with structured JSON payloads, queryable via API, Telegram, or direct SQL.

### What Is Audited

| Category | Events |
|----------|--------|
| **Signals** | Generated signals (with confidence, direction, bar timestamp) and rejected signals (with rejection reason) |
| **Trades** | Entries (order placed, fill received) and exits (stop hit, target hit, manual close) |
| **System events** | Agent starts/stops, circuit breaker trips, connection drops, error threshold breaches, config reloads |
| **Equity snapshots** | Daily end-of-day balance for each account |
| **Reconciliation** | Agent-tracked P&L vs broker-reported P&L comparison results |

---

## 2. Storage

### Database

All audit events live in the `audit_events` table inside `data/trades.db` (SQLite).

### Schema

```sql
CREATE TABLE audit_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,   -- ISO 8601 (UTC)
    event_type  TEXT    NOT NULL,   -- e.g. 'signal_generated', 'trade_entry', 'circuit_breaker_trip'
    account     TEXT    NOT NULL,   -- e.g. 'inception', 'mffu'
    data_json   TEXT    NOT NULL,   -- structured JSON payload (event-specific)
    source      TEXT    NOT NULL    -- e.g. 'strategy', 'execution', 'system', 'reconciliation'
);
```

### Indexes

```sql
CREATE INDEX idx_audit_ts_account_type
    ON audit_events (timestamp, account, event_type);
```

The composite index on `(timestamp, account, event_type)` enables efficient queries for:
- All events for a specific account in a time range.
- All events of a specific type across accounts.
- Time-ordered retrieval for the audit UI.

### Retention Policy

| Event Category | Retention | Config Key |
|---------------|-----------|------------|
| General events (signals, trades, system) | 90 days | `audit.retention_days` |
| Equity snapshots | 365 days | `audit.equity_retention_days` |

Retention is configurable in `config.yaml`:

```yaml
audit:
  retention_days: 90
  equity_retention_days: 365
  db_path: "data/trades.db"
```

A nightly cleanup job prunes events older than the configured retention period.

---

## 3. Event Types

### Signal Events

| `event_type` | Trigger | `data_json` Fields |
|---|---|---|
| `signal_generated` | Strategy produces a trading signal | `direction`, `confidence`, `bar_timestamp`, `price`, `strategy_name`, `indicators` |
| `signal_rejected` | Signal fails eval gate or circuit breaker | `direction`, `confidence`, `bar_timestamp`, `rejection_reason`, `gate_name` |

### Trade Events

| `event_type` | Trigger | `data_json` Fields |
|---|---|---|
| `trade_entry` | Order placed and filled | `direction`, `entry_price`, `quantity`, `order_type`, `broker_order_id` |
| `trade_exit` | Position closed | `direction`, `exit_price`, `quantity`, `pnl`, `exit_reason` (stop/target/manual) |

### System Events

| `event_type` | Trigger | `data_json` Fields |
|---|---|---|
| `agent_start` | Agent process starts | `account`, `config_hash`, `version` |
| `agent_stop` | Agent process stops | `account`, `reason` (clean/crash/signal) |
| `circuit_breaker_trip` | Risk limit hit | `rule`, `threshold`, `current_value`, `action` |
| `connection_drop` | IBKR or Tradovate disconnect | `broker`, `duration_seconds`, `reconnected` |
| `error_threshold` | Error rate exceeds limit | `error_type`, `count`, `window_seconds` |

### Equity & Reconciliation

| `event_type` | Trigger | `data_json` Fields |
|---|---|---|
| `equity_snapshot` | Daily EOD capture | `account`, `balance`, `equity`, `unrealized_pnl`, `date` |
| `reconciliation` | Scheduled comparison | `account`, `agent_pnl`, `broker_pnl`, `difference`, `status` (match/mismatch) |

---

## 4. API Endpoints

All endpoints require the `PEARL_API_KEY` header. Times default to UTC.

### GET /api/audit/events

Query the full event log with filters.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `account` | string | all | Filter by account (`inception`, `mffu`) |
| `event_type` | string | all | Filter by event type |
| `start` | ISO 8601 | 24h ago | Start of time range |
| `end` | ISO 8601 | now | End of time range |
| `limit` | int | 100 | Max results (max 1000) |
| `offset` | int | 0 | Pagination offset |

```bash
curl -H "X-API-Key: $PEARL_API_KEY" \
  "http://localhost:8000/api/audit/events?account=mffu&event_type=trade_entry&start=2026-02-01T00:00:00Z&limit=50"
```

### GET /api/audit/equity-history

Daily equity snapshots for charting.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `account` | string | all | Filter by account |
| `days` | int | 30 | Number of days to return |

### GET /api/audit/reconciliation

Latest reconciliation results per account.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `account` | string | all | Filter by account |
| `days` | int | 7 | Lookback period |

### GET /api/audit/signals

Signal generation and rejection summary.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `account` | string | all | Filter by account |
| `days` | int | 7 | Lookback period |

### GET /api/audit/export

Export audit data as CSV.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `account` | string | all | Filter by account |
| `event_type` | string | all | Filter by event type |
| `start` | ISO 8601 | 30d ago | Start of time range |
| `end` | ISO 8601 | now | End of time range |
| `format` | string | `csv` | Export format (`csv`) |

---

## 5. Telegram Commands

All commands work in the PearlAlgo Telegram bot. Use `/audit` to open the interactive menu.

| Command | Description |
|---------|-------------|
| `/audit trades [7d\|30d]` | Trade summary: entries, exits, win rate, P&L |
| `/audit signals [7d\|30d]` | Signal decisions: generated vs rejected, top rejection reasons |
| `/audit health [7d\|30d]` | System health: restarts, connection drops, circuit breaker trips |
| `/audit reconcile` | Latest reconciliation: agent P&L vs broker P&L per account |
| `/audit export` | Download audit data as a CSV file |

**Default period:** 7 days if no period is specified.

---

## 6. Direct SQLite Queries

For ad-hoc analysis, query the database directly:

```bash
# Open the database
sqlite3 data/trades.db

# Recent trade entries (last 24h)
SELECT timestamp, account, json_extract(data_json, '$.direction') as direction,
       json_extract(data_json, '$.entry_price') as price
FROM audit_events
WHERE event_type = 'trade_entry'
  AND timestamp > datetime('now', '-1 day')
ORDER BY timestamp DESC;

# Rejection reasons breakdown
SELECT json_extract(data_json, '$.rejection_reason') as reason,
       COUNT(*) as count
FROM audit_events
WHERE event_type = 'signal_rejected'
  AND timestamp > datetime('now', '-7 days')
GROUP BY reason
ORDER BY count DESC;

# Daily equity for MFFU
SELECT json_extract(data_json, '$.date') as date,
       json_extract(data_json, '$.balance') as balance
FROM audit_events
WHERE event_type = 'equity_snapshot'
  AND account = 'mffu'
ORDER BY timestamp DESC
LIMIT 30;

# Circuit breaker trips
SELECT timestamp, json_extract(data_json, '$.rule') as rule,
       json_extract(data_json, '$.threshold') as threshold,
       json_extract(data_json, '$.current_value') as value
FROM audit_events
WHERE event_type = 'circuit_breaker_trip'
ORDER BY timestamp DESC
LIMIT 10;
```

---

## 7. AuditLogger Class Reference

The `AuditLogger` class provides typed methods for recording audit events. All methods accept keyword arguments matching the `data_json` fields for their event type.

```python
from pearlalgo.audit import AuditLogger

audit = AuditLogger(db_path="data/trades.db")

# Signals
audit.log_signal_generated(account="inception", direction="LONG", confidence=0.82,
                           bar_timestamp="2026-02-11T14:30:00Z", price=21450.25)
audit.log_signal_rejected(account="mffu", direction="LONG", confidence=0.65,
                          bar_timestamp="2026-02-11T14:30:00Z",
                          rejection_reason="circuit_breaker_daily_loss")

# Trades
audit.log_trade_entry(account="mffu", direction="LONG", entry_price=21450.25,
                      quantity=1, order_type="bracket", broker_order_id="TV-123456")
audit.log_trade_exit(account="mffu", direction="LONG", exit_price=21465.00,
                     quantity=1, pnl=14.75, exit_reason="target")

# System events
audit.log_agent_start(account="inception", version="0.2.4")
audit.log_agent_stop(account="inception", reason="clean_shutdown")
audit.log_circuit_breaker_trip(account="mffu", rule="max_daily_loss",
                               threshold=-2000, current_value=-2100)
audit.log_connection_drop(broker="ibkr", duration_seconds=12, reconnected=True)

# Equity & reconciliation
audit.log_equity_snapshot(account="mffu", balance=50250.00, equity=50250.00,
                          unrealized_pnl=0.0, date="2026-02-11")
audit.log_reconciliation(account="mffu", agent_pnl=250.00, broker_pnl=248.50,
                         difference=1.50, status="match")
```

All methods are **synchronous** and write to SQLite immediately. They are safe to call from async contexts via `asyncio.to_thread()`.
