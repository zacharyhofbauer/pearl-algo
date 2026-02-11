"""
Signal Forwarder – IBKR Virtual -> Tradovate Paper signal sharing via JSONL file.

Extracted from service.py to isolate the shared-signal read/write concern.
Writer mode (IBKR Virtual): appends signals to a JSONL file after processing.
Follower mode (Tradovate Paper): reads signals from the shared file instead of running
strategy.analyze() locally.
"""

from __future__ import annotations

import fcntl
import json
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.utils.market_hours import get_market_hours
from pearlalgo.utils.paths import get_utc_timestamp

# Maximum number of dedup keys to retain before trimming.
_DEDUP_MAX_KEYS = 2000
# Number of most-recent keys to keep after trimming.
_DEDUP_TRIM_TARGET = 1000


class SignalForwarder:
    """Manages reading/writing shared signals between IBKR Virtual and Tradovate Paper agents.

    Lifecycle:
      1. Constructed with the ``signal_forwarding`` config section.
      2. On follower startup, call :meth:`clear_stale_signals`.
      3. Writer calls :meth:`write_shared_signal` after each processed signal.
      4. Follower calls :meth:`read_shared_signals` (or the higher-level
         :meth:`process_forwarded_signals`) each scan cycle.
    """

    def __init__(self, config: dict) -> None:
        """
        Args:
            config: The ``signal_forwarding`` section of the service config.
        """
        self._enabled = bool(config.get("enabled", False))
        self._mode = str(config.get("mode", "off")).strip().lower()
        self.follower_mode: bool = self._enabled and self._mode == "follower"
        self.writer_mode: bool = self._enabled and self._mode == "writer"
        self.shared_signals_path: Path = Path(
            config.get("shared_file", "data/shared_signals.jsonl")
        )
        self._max_lines: int = int(config.get("max_lines", 500))
        # OrderedDict preserves insertion order so we can trim oldest keys
        # when the dedup set grows too large.  Values are unused (always True).
        self._processed_keys: OrderedDict[tuple[str, str], bool] = OrderedDict()
        self._last_read_offset: int = 0

    # ------------------------------------------------------------------
    # Startup helpers
    # ------------------------------------------------------------------

    def clear_stale_signals(self) -> None:
        """Remove stale shared-signals file on follower startup."""
        try:
            if self.shared_signals_path.exists():
                self.shared_signals_path.unlink()
                logger.info("Cleared stale shared_signals.jsonl on follower startup")
            self._last_read_offset = 0
        except Exception as e:
            logger.debug(f"Non-critical: {e}")

    # ------------------------------------------------------------------
    # Writer API
    # ------------------------------------------------------------------

    def write_shared_signal(
        self, signal: Dict, signal_id: str, bar_timestamp: str
    ) -> None:
        """Write a signal to the shared JSONL file for the Tradovate Paper agent to read.

        Called by IBKR Virtual (writer mode) after signal processing and
        ``signal_id`` assignment.  Non-fatal: errors are logged but never
        crash the IBKR Virtual agent.
        """
        try:
            self.shared_signals_path.parent.mkdir(parents=True, exist_ok=True)

            # Build a JSON-safe copy (strip internal/non-serializable keys)
            safe_signal: Dict[str, Any] = {}
            for k, v in signal.items():
                if k.startswith("_"):
                    continue  # skip internal metadata keys
                try:
                    json.dumps(v)
                    safe_signal[k] = v
                except (TypeError, ValueError):
                    safe_signal[k] = str(v)

            record = {
                "signal_id": signal_id,
                "bar_timestamp": bar_timestamp,
                "timestamp": get_utc_timestamp(),
                "signal": safe_signal,
            }

            lock_path = Path(str(self.shared_signals_path) + ".lock")
            with open(lock_path, "w") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    # Append the new record
                    with open(self.shared_signals_path, "a") as f:
                        f.write(json.dumps(record) + "\n")

                    # Rotate if file exceeds max_lines (atomic via temp + rename)
                    try:
                        with open(self.shared_signals_path, "r") as f:
                            lines = f.readlines()
                        if len(lines) > self._max_lines:
                            keep = lines[-self._max_lines :]
                            import tempfile
                            tmp_fd, tmp_name = tempfile.mkstemp(
                                dir=str(self.shared_signals_path.parent),
                                suffix=".tmp",
                            )
                            try:
                                with os.fdopen(tmp_fd, "w") as tmp_f:
                                    tmp_f.writelines(keep)
                                    tmp_f.flush()
                                    os.fsync(tmp_f.fileno())
                                os.replace(tmp_name, self.shared_signals_path)
                            except BaseException:
                                try:
                                    os.unlink(tmp_name)
                                except OSError:
                                    pass
                                raise
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}")  # rotation is non-critical
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

            logger.debug(
                f"Shared signal written: {signal_id[:16]} | "
                f"bar={bar_timestamp} | direction={signal.get('direction')}"
            )
        except Exception as e:
            logger.debug(f"Could not write shared signal (non-critical): {e}")

    # ------------------------------------------------------------------
    # Follower API
    # ------------------------------------------------------------------

    def read_shared_signals(self) -> list[Dict]:
        """Read new signals from the shared JSONL file (Tradovate Paper follower mode).

        Uses byte-offset tracking so only new lines since the last read are
        processed.  Deduplicates by ``(direction, bar_timestamp)`` as a safety
        net so the same EMA cross signal is processed at most once per bar per
        direction.

        Returns:
            List of signal dicts ready for processing.
        """
        if not self.shared_signals_path.exists():
            self._last_read_offset = 0
            return []

        new_signals: list[Dict] = []
        try:
            lock_path = Path(str(self.shared_signals_path) + ".lock")
            with open(lock_path, "w") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_SH)  # shared (read) lock
                try:
                    with open(self.shared_signals_path, "r") as f:
                        f.seek(self._last_read_offset)
                        lines = f.readlines()
                        self._last_read_offset = f.tell()
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Shared signal: skipping malformed JSON line")
                    continue

                sig = record.get("signal")
                if not isinstance(sig, dict):
                    continue

                direction = str(sig.get("direction") or "")
                bar_ts = str(record.get("bar_timestamp") or "")
                if not direction or not bar_ts:
                    continue

                dedup_key = (direction, bar_ts)
                if dedup_key in self._processed_keys:
                    continue

                self._processed_keys[dedup_key] = True
                # Ensure position_size defaults to 1 (strategy doesn't always set it)
                if not sig.get("position_size"):
                    sig["position_size"] = 1
                new_signals.append(sig)

            # Prevent unbounded memory growth: trim oldest keys when over limit.
            # We keep the most-recent _DEDUP_TRIM_TARGET entries so that valid
            # dedup history is preserved across batches.
            if len(self._processed_keys) > _DEDUP_MAX_KEYS:
                excess = len(self._processed_keys) - _DEDUP_TRIM_TARGET
                for _ in range(excess):
                    self._processed_keys.popitem(last=False)  # remove oldest

        except Exception as e:
            logger.warning(f"Error reading shared signals: {e}")

        return new_signals

    # ------------------------------------------------------------------
    # High-level follower helper
    # ------------------------------------------------------------------

    async def process_forwarded_signals(
        self,
        signal_handler: Any,
        sync_counters: Callable[[], None],
        market_data: Optional[Dict] = None,
    ) -> None:
        """Read and process forwarded signals from IBKR Virtual (Tradovate Paper follower mode).

        Called in the main loop's early-exit paths (connection error, fetch
        exception, empty data) so the Tradovate Paper agent never misses a signal even
        when its own IBKR data connection is broken.

        Args:
            signal_handler: The service's ``SignalHandler`` instance.
            sync_counters: Callback to sync counters after each processed signal.
            market_data: Optional market data dict (used for ``buffer_data``).
        """
        if not self.follower_mode:
            return
        # Never process signals when market is closed
        try:
            if not get_market_hours().is_market_open():
                return
        except Exception as e:
            logger.debug(f"Non-critical: {e}")
        try:
            forwarded = self.read_shared_signals()
            if not forwarded:
                return
            logger.info(
                f"Tradovate Paper: Processing {len(forwarded)} forwarded signal(s) from IBKR Virtual"
            )
            buffer: Optional[Any] = None
            if isinstance(market_data, dict):
                _df = market_data.get("df")
                if _df is not None and not getattr(_df, "empty", True):
                    buffer = _df
            for sig in forwarded:
                await signal_handler.process_signal(sig, buffer_data=buffer)
                sync_counters()
        except Exception as e:
            logger.warning(f"Tradovate Paper signal forwarding error: {e}")
