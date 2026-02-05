# Pearl AI Baseline Metrics (2026-02-04)

Captured from live `/api/pearl/metrics` and `/api/pearl/metrics/sources` on
`localhost:8000` with operator access enabled.

## Key snapshots

- p95 latency (ms): 0.0
- total cost (USD): 0.0
- total requests (24h): 0

## /api/pearl/metrics

```
{"period_hours":24,"total_requests":0,"total_tokens":0,"total_cost_usd":0.0,"avg_latency_ms":0.0,"p50_latency_ms":0.0,"p95_latency_ms":0.0,"p99_latency_ms":0.0,"cache_hit_rate":0.0,"error_rate":0.0,"fallback_rate":0.0,"by_endpoint":{},"by_model":{},"cache":{"size":0,"max_size":100,"hits":0,"misses":0,"hit_rate":0,"evictions":0,"avg_entry_age_seconds":0,"misses_by_reason":{"expired":0,"never_seen":0,"skipped_pattern":0,"state_changed":0},"misses_by_reason_pct":{"expired":0.0,"never_seen":0.0,"skipped_pattern":0.0,"state_changed":0.0}}}
```

## /api/pearl/metrics/sources

```
{"counts":{"cache":0,"local":0,"claude":0,"template":0},"percentages":{"cache":0.0,"local":0.0,"claude":0.0,"template":0.0},"total":0,"period_hours":24}
```

## Eval and test baseline

- `python3 -m pearl_ai.eval.ci --mock`: PASS (25/25)
- `pytest tests/test_pearl_*.py` (venv): 126 passed, coverage gate failed (2.25% < 40%)
