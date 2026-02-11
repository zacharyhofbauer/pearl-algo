"""
Tests for Tradovate Paper account detection and routing logic.

Covers:
- is_tv_paper_account: equity=0 (True), equity present (True), missing equity (False),
  empty dict (False), corrupt state (False), non-dict tradovate_account (False)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from pearlalgo.api.data_layer import is_mffu_account


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_state(state_dir: Path, state: dict) -> None:
    """Write a state.json file from a dict."""
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps(state), encoding="utf-8")


# ---------------------------------------------------------------------------
# Parametrized edge case tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "state_data, expected",
    [
        # Tradovate Paper with positive equity
        ({"tradovate_account": {"equity": 50000.0}}, True),
        # Tradovate Paper with equity = 0 (was False, now fixed to True)
        ({"tradovate_account": {"equity": 0}}, True),
        # Tradovate Paper with equity = 0.0
        ({"tradovate_account": {"equity": 0.0}}, True),
        # Tradovate Paper with negative equity (drawdown)
        ({"tradovate_account": {"equity": -500.0}}, True),
        # tradovate_account present but no equity key → not Tradovate Paper
        ({"tradovate_account": {"positions": []}}, False),
        # tradovate_account is empty dict → not Tradovate Paper
        ({"tradovate_account": {}}, False),
        # tradovate_account is None → not Tradovate Paper
        ({"tradovate_account": None}, False),
        # tradovate_account is a string (bad data) → not Tradovate Paper
        ({"tradovate_account": "invalid"}, False),
        # No tradovate_account key at all → not Tradovate Paper (IBKR Virtual)
        ({"running": True}, False),
        # Empty state → not Tradovate Paper
        ({}, False),
    ],
    ids=[
        "equity_positive",
        "equity_zero_int",
        "equity_zero_float",
        "equity_negative",
        "no_equity_key",
        "empty_dict",
        "none_value",
        "string_value",
        "no_tv_key",
        "empty_state",
    ],
)
def test_is_tv_paper_account(tmp_path, state_data, expected):
    """Parametrized test for all edge cases of is_tv_paper_account."""
    _write_state(tmp_path, state_data)
    # Patch read_state_for_dir to read from our tmp_path
    with patch("pearlalgo.api.data_layer.read_state_for_dir") as mock_read:
        mock_read.return_value = state_data
        result = is_mffu_account(tmp_path)
    assert result is expected


def test_is_tv_paper_account_corrupt_state(tmp_path):
    """Corrupt state.json should not crash and should return False."""
    state_file = tmp_path / "state.json"
    state_file.write_text("{invalid json", encoding="utf-8")
    with patch("pearlalgo.api.data_layer.read_state_for_dir") as mock_read:
        mock_read.side_effect = Exception("JSON decode error")
        result = is_mffu_account(tmp_path)
    assert result is False


def test_is_tv_paper_account_missing_state_file(tmp_path):
    """Missing state.json should return False."""
    with patch("pearlalgo.api.data_layer.read_state_for_dir") as mock_read:
        mock_read.return_value = {}
        result = is_mffu_account(tmp_path)
    assert result is False


def test_equity_zero_logs_warning(tmp_path, caplog):
    """When equity is exactly 0, a warning should be logged."""
    state_data = {"tradovate_account": {"equity": 0}}
    with patch("pearlalgo.api.data_layer.read_state_for_dir") as mock_read:
        mock_read.return_value = state_data
        import logging
        with caplog.at_level(logging.WARNING, logger="pearlalgo.api.data_layer"):
            result = is_mffu_account(tmp_path)
    assert result is True
    assert "equity=0" in caplog.text
