"""
Audit API Router

FastAPI router for querying audit events, equity history, and reconciliation results.
Mounted in server.py via ``app.include_router(audit_router)``.
"""

from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import StreamingResponse

from pearlalgo.utils.logger import logger

# Module-level audit logger reference (set by server.py on startup)
_audit_logger = None

# Simple TTL cache for historical queries
_cache: Dict[str, tuple] = {}  # key -> (value, expiry_timestamp)
_CACHE_TTL_SECONDS = 60.0
_MAX_CACHE_SIZE = 500


def set_audit_logger(audit_logger) -> None:
    """Set the AuditLogger instance (called by server.py on startup)."""
    global _audit_logger
    _audit_logger = audit_logger


def _cached(key: str, ttl: float, fn, *args, **kwargs):
    """Simple TTL cache wrapper with max-size eviction."""
    now = time.monotonic()
    if key in _cache:
        value, expiry = _cache[key]
        if now < expiry:
            return value
    result = fn(*args, **kwargs)
    _cache[key] = (result, now + ttl)
    # Evict oldest entries if cache exceeds max size
    if len(_cache) > _MAX_CACHE_SIZE:
        keys_to_evict = sorted(_cache.keys(), key=lambda k: _cache[k][1])[:100]
        for k in keys_to_evict:
            _cache.pop(k, None)
    return result


def _is_recent_query(start_date: Optional[str], end_date: Optional[str]) -> bool:
    """Check if query covers recent data (last hour) - skip cache for these."""
    if not start_date and not end_date:
        return True  # No date filter = includes recent
    now = datetime.now(timezone.utc)
    if end_date:
        try:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if (now - end_dt).total_seconds() < 3600:
                return True
        except (ValueError, TypeError):
            pass
    if start_date and not end_date:
        return True  # Open-ended = includes recent
    return False


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

audit_router = APIRouter(prefix="/api/audit", tags=["audit"])


@audit_router.get("/events")
async def get_audit_events(
    account: Optional[str] = Query(None, description="Filter by account"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    start_date: Optional[str] = Query(None, description="ISO datetime start"),
    end_date: Optional[str] = Query(None, description="ISO datetime end"),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    page_size: int = Query(50, ge=1, le=500, description="Items per page"),
):
    """Query audit events with optional filters and pagination."""
    if _audit_logger is None:
        return {"events": [], "total": 0, "page": page, "page_size": page_size}

    offset = (page - 1) * page_size

    # Use cache for historical queries
    cache_key = f"events:{account}:{event_type}:{start_date}:{end_date}:{page}:{page_size}"
    if not _is_recent_query(start_date, end_date):
        cached = _cached(
            cache_key, _CACHE_TTL_SECONDS,
            lambda: {
                "events": _audit_logger.query_events(
                    event_type=event_type, account=account,
                    start_date=start_date, end_date=end_date,
                    limit=page_size, offset=offset,
                ),
                "total": _audit_logger.count_events(
                    event_type=event_type, account=account,
                    start_date=start_date, end_date=end_date,
                ),
            },
        )
        return {**cached, "page": page, "page_size": page_size}

    events = _audit_logger.query_events(
        event_type=event_type, account=account,
        start_date=start_date, end_date=end_date,
        limit=page_size, offset=offset,
    )
    total = _audit_logger.count_events(
        event_type=event_type, account=account,
        start_date=start_date, end_date=end_date,
    )
    return {"events": events, "total": total, "page": page, "page_size": page_size}


@audit_router.get("/equity-history")
async def get_equity_history(
    account: Optional[str] = Query(None, description="Filter by account"),
    start_date: Optional[str] = Query(None, description="ISO datetime start"),
    end_date: Optional[str] = Query(None, description="ISO datetime end"),
):
    """Query equity snapshot history for charting."""
    if _audit_logger is None:
        return {"snapshots": []}

    cache_key = f"equity:{account}:{start_date}:{end_date}"
    if not _is_recent_query(start_date, end_date):
        snapshots = _cached(
            cache_key, _CACHE_TTL_SECONDS,
            _audit_logger.query_equity_history,
            account=account, start_date=start_date, end_date=end_date,
        )
    else:
        snapshots = _audit_logger.query_equity_history(
            account=account, start_date=start_date, end_date=end_date,
        )
    return {"snapshots": snapshots}


@audit_router.get("/reconciliation")
async def get_reconciliation(
    account: Optional[str] = Query(None, description="Filter by account"),
    start_date: Optional[str] = Query(None, description="ISO datetime start"),
    end_date: Optional[str] = Query(None, description="ISO datetime end"),
):
    """Query reconciliation results."""
    if _audit_logger is None:
        return {"reconciliations": []}

    cache_key = f"recon:{account}:{start_date}:{end_date}"
    if not _is_recent_query(start_date, end_date):
        results = _cached(
            cache_key, _CACHE_TTL_SECONDS,
            _audit_logger.query_reconciliation,
            account=account, start_date=start_date, end_date=end_date,
        )
    else:
        results = _audit_logger.query_reconciliation(
            account=account, start_date=start_date, end_date=end_date,
        )
    return {"reconciliations": results}


@audit_router.get("/signals")
async def get_signal_decisions(
    account: Optional[str] = Query(None, description="Filter by account"),
    outcome: Optional[str] = Query(None, description="Filter: accepted | rejected"),
    start_date: Optional[str] = Query(None, description="ISO datetime start"),
    end_date: Optional[str] = Query(None, description="ISO datetime end"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
):
    """Query signal decision log (generated + rejected signals)."""
    if _audit_logger is None:
        return {"signals": [], "total": 0, "page": page, "page_size": page_size}

    offset = (page - 1) * page_size

    # Map outcome filter to event types
    event_type = None
    if outcome == "accepted":
        event_type = "signal_generated"
    elif outcome == "rejected":
        event_type = "signal_rejected"

    signals = _audit_logger.query_events(
        event_type=event_type, account=account,
        start_date=start_date, end_date=end_date,
        limit=page_size, offset=offset,
    )
    total = _audit_logger.count_events(
        event_type=event_type, account=account,
        start_date=start_date, end_date=end_date,
    )

    # If no outcome filter, include both generated and rejected
    if outcome is None:
        generated = _audit_logger.query_events(
            event_type="signal_generated", account=account,
            start_date=start_date, end_date=end_date,
            limit=page_size, offset=offset,
        )
        rejected = _audit_logger.query_events(
            event_type="signal_rejected", account=account,
            start_date=start_date, end_date=end_date,
            limit=page_size, offset=offset,
        )
        # Merge and sort by timestamp
        signals = sorted(
            generated + rejected,
            key=lambda x: x.get("timestamp", ""),
            reverse=True,
        )[:page_size]
        total = _audit_logger.count_events(
            event_type="signal_generated", account=account,
            start_date=start_date, end_date=end_date,
        ) + _audit_logger.count_events(
            event_type="signal_rejected", account=account,
            start_date=start_date, end_date=end_date,
        )

    return {"signals": signals, "total": total, "page": page, "page_size": page_size}


@audit_router.get("/export")
async def export_audit_events(
    format: str = Query("csv", description="Export format: csv or json"),
    account: Optional[str] = Query(None),
    event_type: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    """Export audit events as CSV or JSON file."""
    if _audit_logger is None:
        if format == "json":
            return {"events": []}
        return Response(content="", media_type="text/csv")

    # Fetch all matching events (up to 10000)
    events = _audit_logger.query_events(
        event_type=event_type, account=account,
        start_date=start_date, end_date=end_date,
        limit=10000, offset=0,
    )

    if format == "json":
        return {"events": events}

    # CSV export
    output = io.StringIO()
    if events:
        writer = csv.DictWriter(
            output,
            fieldnames=["id", "timestamp", "event_type", "account", "source", "data"],
            extrasaction="ignore",
        )
        writer.writeheader()
        for event in events:
            row = {
                "id": event.get("id", ""),
                "timestamp": event.get("timestamp", ""),
                "event_type": event.get("event_type", ""),
                "account": event.get("account", ""),
                "source": event.get("source", ""),
                "data": str(event.get("data", {})),
            }
            writer.writerow(row)

    csv_content = output.getvalue()
    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"audit_export_{timestamp_str}.csv"

    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
