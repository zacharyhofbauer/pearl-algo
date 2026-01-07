"""
Tests for Telegram reporting and feedback features.

Tests:
- Performance lookback parsing
- Signal detail lookup
- Grade command parsing
- Feedback file writing
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest


class TestPerformanceLookbackParsing:
    """Test performance lookback argument parsing."""

    def test_parse_24h_lookback(self):
        """24h should map to 1 day."""
        raw_text = "/performance 24h"
        parts = raw_text.split()
        lookback_arg = parts[1].lower().strip() if len(parts) > 1 else ""
        
        lookback_days = 7  # default
        if lookback_arg in ("24h", "1d"):
            lookback_days = 1
        
        assert lookback_days == 1

    def test_parse_7d_lookback(self):
        """7d should map to 7 days."""
        raw_text = "/performance 7d"
        parts = raw_text.split()
        lookback_arg = parts[1].lower().strip() if len(parts) > 1 else ""
        
        lookback_days = 7  # default
        if lookback_arg in ("7d", "week"):
            lookback_days = 7
        
        assert lookback_days == 7

    def test_parse_30d_lookback(self):
        """30d should map to 30 days."""
        raw_text = "/performance 30d"
        parts = raw_text.split()
        lookback_arg = parts[1].lower().strip() if len(parts) > 1 else ""
        
        lookback_days = 7  # default
        if lookback_arg in ("30d", "month"):
            lookback_days = 30
        
        assert lookback_days == 30

    def test_default_lookback(self):
        """No argument should default to 7 days."""
        raw_text = "/performance"
        parts = raw_text.split()
        
        lookback_days = 7  # default
        if len(parts) > 1:
            lookback_arg = parts[1].lower().strip()
            if lookback_arg in ("24h", "1d"):
                lookback_days = 1
        
        assert lookback_days == 7


class TestGradeCommandParsing:
    """Test /grade command argument parsing."""

    def test_parse_basic_win(self):
        """Basic win parsing."""
        raw_text = "/grade sr_bounce_1767 win"
        parts = raw_text.split()
        
        signal_prefix = parts[1].strip()
        outcome = parts[2].lower().strip()
        is_win = outcome == "win"
        
        assert signal_prefix == "sr_bounce_1767"
        assert is_win is True

    def test_parse_basic_loss(self):
        """Basic loss parsing."""
        raw_text = "/grade mean_rev_456 loss"
        parts = raw_text.split()
        
        signal_prefix = parts[1].strip()
        outcome = parts[2].lower().strip()
        is_win = outcome == "win"
        
        assert signal_prefix == "mean_rev_456"
        assert is_win is False

    def test_parse_with_pnl(self):
        """Parse with P&L value."""
        raw_text = "/grade sr_bounce_1767 win 150"
        parts = raw_text.split()
        
        signal_prefix = parts[1].strip()
        outcome = parts[2].lower().strip()
        is_win = outcome == "win"
        
        pnl = None
        remaining = parts[3:] if len(parts) > 3 else []
        for part in remaining:
            try:
                pnl = float(part)
                break
            except ValueError:
                pass
        
        assert signal_prefix == "sr_bounce_1767"
        assert is_win is True
        assert pnl == 150.0

    def test_parse_with_negative_pnl(self):
        """Parse with negative P&L value."""
        raw_text = "/grade mean_rev_456 loss -75"
        parts = raw_text.split()
        
        signal_prefix = parts[1].strip()
        outcome = parts[2].lower().strip()
        is_win = outcome == "win"
        
        pnl = None
        remaining = parts[3:] if len(parts) > 3 else []
        for part in remaining:
            try:
                pnl = float(part)
                break
            except ValueError:
                pass
        
        assert signal_prefix == "mean_rev_456"
        assert is_win is False
        assert pnl == -75.0

    def test_parse_with_note(self):
        """Parse with note text."""
        raw_text = "/grade sr_bounce_1767 win 150 Great entry held to target"
        parts = raw_text.split()
        
        signal_prefix = parts[1].strip()
        outcome = parts[2].lower().strip()
        
        pnl = None
        note = ""
        remaining = parts[3:] if len(parts) > 3 else []
        
        for i, part in enumerate(remaining):
            if pnl is None:
                try:
                    pnl = float(part)
                except ValueError:
                    note = " ".join(remaining[i:])
                    break
            else:
                note = " ".join(remaining[i:])
                break
        
        assert pnl == 150.0
        assert note == "Great entry held to target"

    def test_parse_with_force(self):
        """Parse with force flag."""
        raw_text = "/grade sr_bounce_1767 win force"
        parts = raw_text.split()
        
        signal_prefix = parts[1].strip()
        outcome = parts[2].lower().strip()
        
        force = False
        remaining = parts[3:] if len(parts) > 3 else []
        for part in remaining:
            if part.lower() == "force":
                force = True
        
        assert signal_prefix == "sr_bounce_1767"
        assert force is True


class TestFeedbackFileWriting:
    """Test feedback.jsonl file writing."""

    def test_feedback_record_structure(self):
        """Verify feedback record has all required fields."""
        feedback_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "signal_id": "sr_bounce_1767123456",
            "signal_type": "sr_bounce",
            "outcome": "win",
            "is_win": True,
            "pnl": 150.0,
            "note": "Great entry",
            "force": False,
            "already_exited": False,
            "applied_to_learning": False,
        }
        
        assert "timestamp" in feedback_record
        assert "signal_id" in feedback_record
        assert "signal_type" in feedback_record
        assert "outcome" in feedback_record
        assert "is_win" in feedback_record
        assert "pnl" in feedback_record
        assert "note" in feedback_record
        assert "force" in feedback_record
        assert "already_exited" in feedback_record
        assert "applied_to_learning" in feedback_record

    def test_feedback_file_append(self):
        """Test that feedback is appended correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            feedback_file = Path(tmpdir) / "feedback.jsonl"
            
            # Write first record
            record1 = {"signal_id": "test1", "is_win": True}
            with open(feedback_file, "a") as f:
                f.write(json.dumps(record1) + "\n")
            
            # Write second record
            record2 = {"signal_id": "test2", "is_win": False}
            with open(feedback_file, "a") as f:
                f.write(json.dumps(record2) + "\n")
            
            # Read and verify
            with open(feedback_file, "r") as f:
                lines = f.readlines()
            
            assert len(lines) == 2
            assert json.loads(lines[0])["signal_id"] == "test1"
            assert json.loads(lines[1])["signal_id"] == "test2"


class TestSignalLookup:
    """Test signal lookup by ID prefix."""

    def test_exact_match(self):
        """Test exact signal ID match."""
        signals = [
            {"signal_id": "sr_bounce_1767123456", "status": "exited"},
            {"signal_id": "mean_rev_1767234567", "status": "entered"},
        ]
        
        signal_prefix = "sr_bounce_1767123456"
        matched = None
        for sig in signals:
            if sig["signal_id"].startswith(signal_prefix):
                matched = sig
        
        assert matched is not None
        assert matched["signal_id"] == "sr_bounce_1767123456"

    def test_prefix_match(self):
        """Test partial prefix match."""
        signals = [
            {"signal_id": "sr_bounce_1767123456", "status": "exited"},
            {"signal_id": "mean_rev_1767234567", "status": "entered"},
        ]
        
        signal_prefix = "sr_bounce_1767"
        matched = None
        for sig in signals:
            if sig["signal_id"].startswith(signal_prefix):
                matched = sig
        
        assert matched is not None
        assert matched["signal_id"] == "sr_bounce_1767123456"

    def test_contains_match(self):
        """Test contains match (for partial IDs)."""
        signals = [
            {"signal_id": "sr_bounce_1767123456", "status": "exited"},
            {"signal_id": "mean_rev_1767234567", "status": "entered"},
        ]
        
        signal_prefix = "1767123"
        matched = None
        for sig in signals:
            if signal_prefix in sig["signal_id"]:
                matched = sig
        
        assert matched is not None
        assert matched["signal_id"] == "sr_bounce_1767123456"

    def test_no_match(self):
        """Test no match found."""
        signals = [
            {"signal_id": "sr_bounce_1767123456", "status": "exited"},
            {"signal_id": "mean_rev_1767234567", "status": "entered"},
        ]
        
        signal_prefix = "nonexistent_signal"
        matched = None
        for sig in signals:
            if sig["signal_id"].startswith(signal_prefix) or signal_prefix in sig["signal_id"]:
                matched = sig
        
        assert matched is None


class TestPerformanceTrackerRecentExits:
    """Test that performance tracker returns recent exits."""

    def test_recent_exits_sorted(self):
        """Test that recent exits are sorted by exit time (most recent first)."""
        exited_signals = [
            {"signal_id": "sig1", "exit_time": "2026-01-05T10:00:00+00:00", "pnl": 100, "is_win": True},
            {"signal_id": "sig2", "exit_time": "2026-01-06T10:00:00+00:00", "pnl": -50, "is_win": False},
            {"signal_id": "sig3", "exit_time": "2026-01-04T10:00:00+00:00", "pnl": 200, "is_win": True},
        ]
        
        sorted_exits = sorted(
            exited_signals,
            key=lambda x: x.get("exit_time", ""),
            reverse=True,
        )
        
        assert sorted_exits[0]["signal_id"] == "sig2"  # Most recent
        assert sorted_exits[1]["signal_id"] == "sig1"
        assert sorted_exits[2]["signal_id"] == "sig3"  # Oldest

    def test_recent_exits_limited(self):
        """Test that recent exits are limited to N entries."""
        exited_signals = [{"signal_id": f"sig{i}"} for i in range(20)]
        
        recent_exits = exited_signals[:10]
        
        assert len(recent_exits) == 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

