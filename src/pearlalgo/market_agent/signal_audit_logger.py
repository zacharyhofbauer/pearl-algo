"""Signal audit logger — JSONL writer for Phase 1 observability.

Writes one record per ``GateDecision`` to ``signal_audit.jsonl`` in the
agent's state directory, alongside ``signals.jsonl``. The writer is
non-blocking: records are enqueued and drained by a background thread so
audit I/O never slows the signal loop. If the queue is full or the worker
crashes, records are dropped with a warning — audit logging must never
break trading.

Rotation happens at 20MB (configurable) by renaming the current file to
``signal_audit.jsonl.1`` and starting fresh. Retention trims numbered
backups older than ``retention_days``.

See ``docs/design/observability-phase-1.md`` for the data model.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from pearlalgo.market_agent.gate_decision import GateDecision
from pearlalgo.utils.logger import logger

_DEFAULT_MAX_QUEUE_SIZE = 5000
_DEFAULT_ROTATION_BYTES = 20 * 1024 * 1024  # 20 MB
_DEFAULT_RETENTION_DAYS = 14
_SENTINEL = object()  # signals worker to shut down
_SCHEMA_VERSION = 1


class SignalAuditLogger:
    """Non-blocking JSONL logger for signal-gate decisions.

    The logger is safe to instantiate with ``enabled=False``, in which case
    every ``record()`` call is a no-op. This lets callers wire the logger
    unconditionally and the config flag controls runtime behavior.
    """

    def __init__(
        self,
        state_dir: Path,
        *,
        enabled: bool = True,
        max_queue_size: int = _DEFAULT_MAX_QUEUE_SIZE,
        rotation_bytes: int = _DEFAULT_ROTATION_BYTES,
        retention_days: int = _DEFAULT_RETENTION_DAYS,
        filename: str = "signal_audit.jsonl",
    ) -> None:
        self._enabled = bool(enabled)
        self._path: Path = Path(state_dir) / filename
        self._rotation_bytes = int(rotation_bytes)
        self._retention_days = int(retention_days)
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max_queue_size)
        self._worker: Optional[threading.Thread] = None
        self._stopped = threading.Event()
        self._write_lock = threading.Lock()
        self._dropped_count = 0

        if self._enabled:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._start_worker()

    # ----- public API -------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def path(self) -> Path:
        return self._path

    def record(self, signal: Dict[str, Any], decision: GateDecision) -> None:
        """Enqueue one audit record. Never blocks; drops on overflow."""
        if not self._enabled:
            return
        try:
            payload = self._build_payload(signal, decision)
        except Exception as exc:
            # Building the payload should be essentially infallible; if it
            # isn't, surface and move on — never raise into the caller.
            logger.warning(f"signal_audit_logger: payload build failed: {exc}")
            return
        try:
            self._queue.put_nowait(payload)
        except queue.Full:
            self._dropped_count += 1
            if self._dropped_count % 100 == 1:  # log first and every 100th drop
                logger.warning(
                    f"signal_audit_logger: queue full, dropped {self._dropped_count} records"
                )

    def shutdown(self, timeout: float = 2.0) -> None:
        """Drain and stop the worker. Safe to call multiple times."""
        if not self._enabled or self._stopped.is_set():
            return
        self._stopped.set()
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass  # worker will notice _stopped flag on next drain
        if self._worker is not None:
            self._worker.join(timeout=timeout)

    # ----- internals --------------------------------------------------

    def _build_payload(
        self, signal: Dict[str, Any], decision: GateDecision
    ) -> Dict[str, Any]:
        """Construct the JSONL record from a signal + decision pair."""
        ts = datetime.now(timezone.utc).isoformat()
        # Pull a compact snapshot of the signal's identifying fields.
        # We intentionally do NOT include the full signal dict — that
        # belongs in signals.jsonl. The audit record is a decision log,
        # not a signal log.
        snapshot = {
            "signal_id": signal.get("signal_id"),
            "signal_type": signal.get("type") or signal.get("signal_type"),
            "direction": signal.get("direction"),
            "confidence": signal.get("confidence"),
            "entry_price": signal.get("entry_price"),
        }
        # Optional regime / volatility context, if the caller attached it.
        regime_info = signal.get("market_regime") or {}
        if isinstance(regime_info, dict):
            if "regime" in regime_info:
                snapshot["regime"] = regime_info["regime"]
            if "volatility_ratio" in regime_info:
                snapshot["atr_ratio"] = regime_info["volatility_ratio"]
        return {
            "_schema": _SCHEMA_VERSION,
            "ts": ts,
            **snapshot,
            **decision.to_dict(),
        }

    def _start_worker(self) -> None:
        self._worker = threading.Thread(
            target=self._run_worker,
            name="signal-audit-writer",
            daemon=True,
        )
        self._worker.start()

    def _run_worker(self) -> None:
        while not self._stopped.is_set():
            try:
                item = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if item is _SENTINEL:
                break
            try:
                self._write_one(item)
            except Exception as exc:
                logger.warning(f"signal_audit_logger: write failed: {exc}")
        # Drain remaining items on shutdown (best effort).
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is _SENTINEL:
                continue
            try:
                self._write_one(item)
            except Exception:
                pass

    def _write_one(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload, default=str, separators=(",", ":")) + "\n"
        with self._write_lock:
            self._rotate_if_needed()
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(line)

    def _rotate_if_needed(self) -> None:
        try:
            if not self._path.exists():
                return
            size = self._path.stat().st_size
        except OSError:
            return
        if size < self._rotation_bytes:
            return
        backup = self._path.with_suffix(self._path.suffix + ".1")
        try:
            if backup.exists():
                backup.unlink()
            self._path.rename(backup)
        except OSError as exc:
            logger.warning(f"signal_audit_logger: rotation failed: {exc}")
            return
        self._trim_old_backups()

    def _trim_old_backups(self) -> None:
        """Delete rotated files older than retention_days."""
        cutoff = datetime.now() - timedelta(days=self._retention_days)
        try:
            for p in self._path.parent.glob(f"{self._path.name}.*"):
                try:
                    mtime = datetime.fromtimestamp(p.stat().st_mtime)
                except OSError:
                    continue
                if mtime < cutoff:
                    try:
                        p.unlink()
                    except OSError:
                        pass
        except OSError:
            pass
