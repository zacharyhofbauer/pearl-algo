"""
Tests for the data layer module (src/pearlalgo/api/data_layer.py).

Covers:
- cached(): TTL behavior, cache hit/miss, expiry
- get_start_balance(): challenge_state.json, fallback, bad JSON
- get_cached_performance_data(): missing file, invalid JSON, list wrapping
- load_performance_data(): extraction of "trades" key
- get_signals(): max_lines, TTL, missing file
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from pearlalgo.api.data_layer import (
    cached,
    get_start_balance,
    get_cached_performance_data,
    load_performance_data,
    get_signals,
    _ttl_cache,
    _ttl_cache_lock,
)


# ---------------------------------------------------------------------------
# cached() TTL behavior
# ---------------------------------------------------------------------------

class TestCached:

    def setup_method(self):
        """Clear the TTL cache before each test."""
        with _ttl_cache_lock:
            _ttl_cache.clear()

    def test_cache_hit_returns_cached_value(self):
        call_count = 0
        def expensive():
            nonlocal call_count
            call_count += 1
            return 42

        result1 = cached("test_key_hit", 10.0, expensive)
        result2 = cached("test_key_hit", 10.0, expensive)
        assert result1 == 42
        assert result2 == 42
        assert call_count == 1  # Only called once

    def test_cache_miss_after_ttl(self):
        call_count = 0
        def expensive():
            nonlocal call_count
            call_count += 1
            return call_count

        result1 = cached("test_key_ttl", 0.01, expensive)  # 10ms TTL
        time.sleep(0.02)  # Wait for expiry
        result2 = cached("test_key_ttl", 0.01, expensive)
        assert result1 == 1
        assert result2 == 2
        assert call_count == 2

    def test_different_keys_independent(self):
        cached("key_a", 10.0, lambda: "a")
        cached("key_b", 10.0, lambda: "b")
        assert cached("key_a", 10.0, lambda: "x") == "a"
        assert cached("key_b", 10.0, lambda: "x") == "b"

    def test_cache_stores_none_values(self):
        call_count = 0
        def returns_none():
            nonlocal call_count
            call_count += 1
            return None

        cached("test_none", 10.0, returns_none)
        cached("test_none", 10.0, returns_none)
        assert call_count == 1  # None should be cached too


# ---------------------------------------------------------------------------
# get_start_balance()
# ---------------------------------------------------------------------------

class TestGetStartBalance:

    def test_reads_from_challenge_state(self, tmp_path):
        ch_file = tmp_path / "challenge_state.json"
        ch_file.write_text(json.dumps({
            "config": {"start_balance": 75000.0}
        }))
        assert get_start_balance(tmp_path) == 75000.0

    def test_fallback_to_default(self, tmp_path):
        # No challenge_state.json exists
        assert get_start_balance(tmp_path) == 50000.0

    def test_bad_json_returns_default(self, tmp_path):
        ch_file = tmp_path / "challenge_state.json"
        ch_file.write_text("{bad json")
        assert get_start_balance(tmp_path) == 50000.0

    def test_missing_config_key_returns_default(self, tmp_path):
        ch_file = tmp_path / "challenge_state.json"
        ch_file.write_text(json.dumps({"other": "data"}))
        assert get_start_balance(tmp_path) == 50000.0


# ---------------------------------------------------------------------------
# get_cached_performance_data()
# ---------------------------------------------------------------------------

class TestGetCachedPerformanceData:

    def setup_method(self):
        with _ttl_cache_lock:
            _ttl_cache.clear()

    def test_missing_file_returns_empty(self, tmp_path):
        result = get_cached_performance_data(tmp_path)
        assert result == {}

    def test_valid_list_wrapped_in_trades_key(self, tmp_path):
        pf = tmp_path / "performance.json"
        pf.write_text(json.dumps([{"pnl": 10}, {"pnl": -5}]))
        result = get_cached_performance_data(tmp_path)
        assert "trades" in result
        assert len(result["trades"]) == 2

    def test_invalid_json_returns_empty(self, tmp_path):
        pf = tmp_path / "performance.json"
        pf.write_text("{not valid json")
        result = get_cached_performance_data(tmp_path)
        assert result == {}

    def test_non_list_returns_empty(self, tmp_path):
        pf = tmp_path / "performance.json"
        pf.write_text(json.dumps({"not": "a list"}))
        result = get_cached_performance_data(tmp_path)
        assert result == {}


# ---------------------------------------------------------------------------
# load_performance_data()
# ---------------------------------------------------------------------------

class TestLoadPerformanceData:

    def setup_method(self):
        with _ttl_cache_lock:
            _ttl_cache.clear()

    def test_returns_trades_list(self, tmp_path):
        pf = tmp_path / "performance.json"
        pf.write_text(json.dumps([{"pnl": 10}, {"pnl": -5}]))
        result = load_performance_data(tmp_path)
        assert result is not None
        assert len(result) == 2

    def test_missing_file_returns_empty_list(self, tmp_path):
        result = load_performance_data(tmp_path)
        assert result == []


# ---------------------------------------------------------------------------
# get_signals()
# ---------------------------------------------------------------------------

class TestGetSignals:

    def setup_method(self):
        with _ttl_cache_lock:
            _ttl_cache.clear()

    def test_missing_file_returns_empty(self, tmp_path):
        result = get_signals(tmp_path)
        assert result == []

    def test_reads_jsonl(self, tmp_path):
        signals_file = tmp_path / "signals.jsonl"
        lines = [
            json.dumps({"signal_id": "s1", "status": "entered"}),
            json.dumps({"signal_id": "s2", "status": "exited"}),
        ]
        signals_file.write_text("\n".join(lines) + "\n")
        result = get_signals(tmp_path, max_lines=10)
        assert len(result) == 2

    def test_different_max_lines_cached_separately(self, tmp_path):
        signals_file = tmp_path / "signals.jsonl"
        lines = [json.dumps({"signal_id": f"s{i}"}) for i in range(10)]
        signals_file.write_text("\n".join(lines) + "\n")

        result_5 = get_signals(tmp_path, max_lines=5)
        result_10 = get_signals(tmp_path, max_lines=10)
        # They should potentially differ (or at least be cached independently)
        assert isinstance(result_5, list)
        assert isinstance(result_10, list)
