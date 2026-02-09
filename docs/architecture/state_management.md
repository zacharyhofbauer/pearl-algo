# State Management Architecture

## Overview

Pearl Algo uses a **dual-write state management pattern** to balance multiple requirements:
- Fast runtime access for the trading loop
- Mobile/Telegram compatibility
- Analytics and queryability
- Durability and recovery

## The Dual-Write Pattern

### Primary Store: JSON Files

Location: `data/agent_state/<MARKET>/`

Files:
- `state.json` - Current agent state (running, paused, counters)
- `signals.jsonl` - Append-only signal log (JSONL format)
- `performance.json` - Aggregated performance metrics

**Why JSON?**
1. Human-readable for debugging
2. Portable - works on any system
3. Mobile/Telegram bot compatible (can read without SQLite)
4. Fast atomic writes using temp file + rename pattern

### Secondary Store: SQLite Database

Location: `data/agent_state/<MARKET>/trades.db` (configurable)

Tables:
- `trades` - Completed trades with full context
- `signals` - All signals with status tracking
- `cycle_diagnostics` - Per-cycle observability data

**Why SQLite?**
1. Queryable for analytics (`/doctor`, performance reports)
2. Efficient aggregations (win rate by regime, time bucket analysis)
3. Long-term storage with indexes
4. Enables offline analysis tools

## Data Flow

```
Signal Generated
       │
       ├──▶ JSON: Append to signals.jsonl (immediate)
       │
       └──▶ SQLite: Insert into signals table (async or sync)

Trade Exited
       │
       ├──▶ JSON: Update signals.jsonl record
       │
       ├──▶ JSON: Update performance.json
       │
       └──▶ SQLite: Update trade record (async or sync)
```

## Configuration

In `config.yaml`:

```yaml
storage:
  sqlite_enabled: true          # Enable dual-write to SQLite
  db_path: null                 # null = default: state_dir/trades.db
  async_writes_enabled: true    # Non-blocking SQLite writes
  async_queue_max_size: 1000
  async_queue_priority_trades: true  # Trades get priority in queue
```

## Async Write Queue

When `async_writes_enabled: true`, SQLite writes happen in a background thread:

1. Trade/signal events are queued
2. Background worker processes queue in batches
3. Trades get priority over diagnostics
4. Queue has max size to prevent memory issues

Benefits:
- Main trading loop never blocks on SQLite
- Reduced latency for signal processing
- Graceful degradation if SQLite is slow

## Consistency Guarantees

### Strong Guarantees
- JSON files are always written synchronously
- Atomic writes using temp file + rename
- Signal IDs are unique (timestamp-based)

### Eventual Consistency
- SQLite may lag behind JSON by a few seconds (async mode)
- On crash, SQLite might be missing the last few events
- JSON is the source of truth for recovery

## Recovery

If SQLite becomes corrupted or out of sync:

```bash
# Rebuild SQLite from JSON (signals.jsonl is authoritative)
python scripts/maintenance/rebuild_sqlite_from_json.py
```

## Key Files

- `src/pearlalgo/market_agent/state_manager.py` - JSON state management (writes with exclusive locks)
- `src/pearlalgo/market_agent/state_reader.py` - Locked reads for external consumers (shared locks)
- `src/pearlalgo/learning/trade_database.py` - SQLite operations
- `src/pearlalgo/storage/async_sqlite_queue.py` - Async write queue

## Thread Safety

### state_manager.py
- Uses `fcntl.flock(LOCK_EX)` for atomic writes
- Provides TTL-cached `get_recent_signals()` (5-second cache with `collections.deque` tail-read)
- Incremental signal count (`get_signal_count()`) avoids full-file scans
- Provides `async_get_recent_signals()` for callers in async contexts
- Single writer expected (the agent process)

### state_reader.py
- Uses `fcntl.flock(LOCK_SH)` shared locks for reads
- Coordinates with state_manager's exclusive write locks
- Used by `api_server.py`, `scheduled_tasks.py`, and other read-only consumers
- Provides `async_read_state()` / `async_read_signals()` wrappers via `asyncio.to_thread()`

### trade_database.py
- SQLite with WAL mode for concurrent reads
- Single writer with connection per operation
- Async queue serializes writes from main process
- Feature inserts use `executemany()` for bulk performance

## Best Practices

1. **Never modify JSON files directly** - Use state_manager methods for writes, state_reader for reads
2. **For analytics, prefer SQLite** - Don't parse signals.jsonl manually
3. **For real-time state, read JSON** - It's always up-to-date
4. **After crashes, check consistency** - Run integrity check script
5. **In async contexts, use async wrappers** - `state_reader.async_read_state()`, `state_manager.async_get_recent_signals()`
6. **Operator actions use flag files** - Telegram and web API write `.flag` files; the agent processes them in the next cycle (avoids direct state.json race conditions)
