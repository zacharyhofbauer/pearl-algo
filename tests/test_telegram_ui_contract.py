"""
Telegram UI Contract Tests

Tests the callback_data contract between notifier and command handler:
- Canonical callback_data format resolution
- Legacy callback alias support
- Signal detail lookup and formatting
- Markdown safety for signal identifiers
"""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Tests for telegram_ui_contract module
# ---------------------------------------------------------------------------

class TestCallbackResolution:
    """Test the resolve_callback function normalizes legacy callbacks."""

    def test_resolve_legacy_start(self):
        """Legacy 'start' callback resolves to menu:main."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        result = resolve_callback("start")
        assert result == "menu:main"

    def test_resolve_legacy_signals(self):
        """Legacy 'signals' callback resolves to menu:signals."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        result = resolve_callback("signals")
        assert result == "menu:signals"

    def test_resolve_legacy_status(self):
        """Legacy 'status' callback resolves to menu:status."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        result = resolve_callback("status")
        assert result == "menu:status"

    def test_resolve_legacy_data_quality(self):
        """Legacy 'data_quality' callback resolves to action:data_quality."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        result = resolve_callback("data_quality")
        assert result == "action:data_quality"

    def test_resolve_legacy_gateway_status(self):
        """Legacy 'gateway_status' callback resolves to action:gateway_status."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        result = resolve_callback("gateway_status")
        assert result == "action:gateway_status"

    def test_resolve_legacy_signal_detail_underscore(self):
        """Legacy signal_detail_<id> (underscore) resolves to signal_detail:<id> (colon)."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        result = resolve_callback("signal_detail_abc123def456")
        assert result == "signal_detail:abc123def456"

    def test_resolve_canonical_unchanged(self):
        """Canonical callbacks pass through unchanged."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        assert resolve_callback("menu:signals") == "menu:signals"
        assert resolve_callback("action:data_quality") == "action:data_quality"
        assert resolve_callback("back") == "back"
        assert resolve_callback("confirm:restart_agent") == "confirm:restart_agent"

    def test_resolve_empty_string(self):
        """Empty string returns empty string."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        assert resolve_callback("") == ""

    def test_resolve_unknown_callback(self):
        """Unknown callbacks pass through unchanged."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        
        assert resolve_callback("unknown_action") == "unknown_action"


class TestCallbackParsing:
    """Test the parse_callback function extracts type, action, and param."""

    def test_parse_menu_callback(self):
        """Menu callbacks parse correctly."""
        from pearlalgo.utils.telegram_ui_contract import parse_callback
        
        callback_type, action, param = parse_callback("menu:signals")
        assert callback_type == "menu"
        assert action == "signals"
        assert param is None

    def test_parse_action_callback(self):
        """Action callbacks parse correctly."""
        from pearlalgo.utils.telegram_ui_contract import parse_callback
        
        callback_type, action, param = parse_callback("action:data_quality")
        assert callback_type == "action"
        assert action == "data_quality"
        assert param is None

    def test_parse_action_with_param(self):
        """Action callbacks with params parse correctly."""
        from pearlalgo.utils.telegram_ui_contract import parse_callback
        
        callback_type, action, param = parse_callback("action:toggle_pref:auto_chart_on_signal")
        assert callback_type == "action"
        assert action == "toggle_pref"
        assert param == "auto_chart_on_signal"

    def test_parse_back_callback(self):
        """Back callback parses correctly."""
        from pearlalgo.utils.telegram_ui_contract import parse_callback
        
        callback_type, action, param = parse_callback("back")
        assert callback_type == "back"
        assert action == ""
        assert param is None

    def test_parse_confirm_callback(self):
        """Confirm callbacks parse correctly."""
        from pearlalgo.utils.telegram_ui_contract import parse_callback
        
        callback_type, action, param = parse_callback("confirm:restart_agent")
        assert callback_type == "confirm"
        assert action == "restart_agent"
        assert param is None

    def test_parse_signal_detail_callback(self):
        """Signal detail callbacks parse correctly."""
        from pearlalgo.utils.telegram_ui_contract import parse_callback
        
        callback_type, action, param = parse_callback("signal_detail:abc123def456")
        assert callback_type == "signal_detail"
        assert action == "abc123def456"
        assert param is None


class TestCallbackBuilders:
    """Test the canonical callback builders."""

    def test_build_menu_callback(self):
        """callback_menu builds correct format."""
        from pearlalgo.utils.telegram_ui_contract import callback_menu
        
        assert callback_menu("main") == "menu:main"
        assert callback_menu("signals") == "menu:signals"
        assert callback_menu("status") == "menu:status"

    def test_build_action_callback(self):
        """callback_action builds correct format."""
        from pearlalgo.utils.telegram_ui_contract import callback_action
        
        assert callback_action("data_quality") == "action:data_quality"
        assert callback_action("toggle_pref", "auto_chart") == "action:toggle_pref:auto_chart"

    def test_build_signal_detail_callback(self):
        """callback_signal_detail builds correct format."""
        from pearlalgo.utils.telegram_ui_contract import callback_signal_detail
        
        assert callback_signal_detail("abc123") == "signal_detail:abc123"

    def test_build_confirm_callback(self):
        """callback_confirm builds correct format."""
        from pearlalgo.utils.telegram_ui_contract import callback_confirm
        
        assert callback_confirm("restart_agent") == "confirm:restart_agent"

    def test_build_back_callback(self):
        """callback_back returns 'back'."""
        from pearlalgo.utils.telegram_ui_contract import callback_back
        
        assert callback_back() == "back"


# ---------------------------------------------------------------------------
# Tests for Signal Detail Formatting
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_state_dir():
    """Create a temporary state directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        state_dir = Path(tmpdir) / "agent_state" / "NQ"
        state_dir.mkdir(parents=True)
        yield state_dir


@pytest.fixture
def sample_signal():
    """Create a sample signal for testing."""
    return {
        "signal_id": "test_signal_abc123def456789012",
        "symbol": "MNQ",
        "type": "breakout_momentum",
        "direction": "long",
        "status": "exited",
        "entry_price": 17500.00,
        "stop_loss": 17480.00,
        "take_profit": 17550.00,
        "exit_price": 17540.00,
        "pnl": 200.00,
        "confidence": 0.75,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "exit_time": datetime.now(timezone.utc).isoformat(),
        "exit_reason": "take_profit",
        "regime": {
            "regime": "trending_bullish",
            "volatility": "normal",
            "session": "morning_trend"
        },
        "mtf_analysis": {
            "alignment": "aligned"
        },
        "reason": "Strong breakout with volume confirmation"
    }


class TestSignalDetailFormatting:
    """Test signal detail message formatting."""

    def test_signal_detail_under_telegram_limit(self, temp_state_dir, sample_signal):
        """Signal detail message stays under Telegram's 4096 char limit."""
        # Write signal to file
        signals_file = temp_state_dir / "signals.jsonl"
        with open(signals_file, 'w') as f:
            f.write(json.dumps(sample_signal) + "\n")
        
        # Import and create handler
        from pearlalgo.market_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.state_dir = temp_state_dir
        
        # Find signal
        signal = handler._find_signal_by_prefix("test_signal")
        assert signal is not None
        
        # Format signal detail
        formatted = handler._format_signal_detail(sample_signal)
        
        # Verify under Telegram limit
        assert len(formatted) < 4096
        assert "MNQ" in formatted
        assert "LONG" in formatted
        assert "17500.00" in formatted

    def test_signal_detail_with_underscore_id(self, temp_state_dir):
        """Signal IDs with underscores are displayed safely."""
        signal = {
            "signal_id": "signal_with_many_underscores_in_id",
            "symbol": "MNQ",
            "type": "test_signal_type",
            "direction": "long",
            "status": "generated",
            "entry_price": 17500.00,
            "stop_loss": 17480.00,
            "take_profit": 17550.00,
            "confidence": 0.70,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
        # Write signal to file
        signals_file = temp_state_dir / "signals.jsonl"
        with open(signals_file, 'w') as f:
            f.write(json.dumps(signal) + "\n")
        
        from pearlalgo.market_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.state_dir = temp_state_dir
        
        # Format should not raise and should contain the ID
        formatted = handler._format_signal_detail(signal)
        assert "signal_with_many" in formatted or "signal with many" in formatted

    def test_find_signal_by_prefix(self, temp_state_dir, sample_signal):
        """Signal lookup by prefix works correctly."""
        # Write multiple signals
        signals_file = temp_state_dir / "signals.jsonl"
        
        other_signal = sample_signal.copy()
        other_signal["signal_id"] = "other_signal_xyz789"
        
        with open(signals_file, 'w') as f:
            f.write(json.dumps(other_signal) + "\n")
            f.write(json.dumps(sample_signal) + "\n")
        
        from pearlalgo.market_agent.telegram_command_handler import TelegramCommandHandler
        
        handler = TelegramCommandHandler.__new__(TelegramCommandHandler)
        handler.state_dir = temp_state_dir
        
        # Find by prefix
        found = handler._find_signal_by_prefix("test_signal")
        assert found is not None
        assert found["signal_id"] == sample_signal["signal_id"]
        
        # Find other signal
        found_other = handler._find_signal_by_prefix("other_signal")
        assert found_other is not None
        assert found_other["signal_id"] == "other_signal_xyz789"
        
        # Not found
        not_found = handler._find_signal_by_prefix("nonexistent")
        assert not_found is None


# ---------------------------------------------------------------------------
# Tests for Notifier Callback Emission
# ---------------------------------------------------------------------------

class TestNotifierCallbackFormat:
    """Test that notifier emits canonical callback_data."""

    def test_callback_menu_format(self):
        """Verify callback_menu produces correct format for notifier use."""
        from pearlalgo.utils.telegram_ui_contract import callback_menu, MENU_MAIN, MENU_SIGNALS
        
        # These are the values notifier should use
        main_cb = callback_menu(MENU_MAIN)
        signals_cb = callback_menu(MENU_SIGNALS)
        
        assert main_cb == "menu:main"
        assert signals_cb == "menu:signals"
        
        # Verify they resolve to themselves (already canonical)
        from pearlalgo.utils.telegram_ui_contract import resolve_callback
        assert resolve_callback(main_cb) == main_cb
        assert resolve_callback(signals_cb) == signals_cb

    def test_callback_action_format(self):
        """Verify callback_action produces correct format for notifier use."""
        from pearlalgo.utils.telegram_ui_contract import (
            callback_action, 
            ACTION_DATA_QUALITY, 
            ACTION_GATEWAY_STATUS
        )
        
        data_quality_cb = callback_action(ACTION_DATA_QUALITY)
        gateway_cb = callback_action(ACTION_GATEWAY_STATUS)
        
        assert data_quality_cb == "action:data_quality"
        assert gateway_cb == "action:gateway_status"

    def test_callback_signal_detail_format(self):
        """Verify callback_signal_detail produces correct format."""
        from pearlalgo.utils.telegram_ui_contract import callback_signal_detail
        
        cb = callback_signal_detail("abc123def456")
        assert cb == "signal_detail:abc123def456"
        
        # Verify it parses correctly
        from pearlalgo.utils.telegram_ui_contract import parse_callback
        cb_type, action, param = parse_callback(cb)
        assert cb_type == "signal_detail"
        assert action == "abc123def456"


# ---------------------------------------------------------------------------
# Tests for Action Cue Wording Fix
# ---------------------------------------------------------------------------

class TestActionCueWording:
    """Test the action cue wording fix."""

    def test_generated_signal_says_entry_price(self):
        """Generated signal action cue says 'entry price' not 'target price'."""
        from pearlalgo.utils.telegram_alerts import format_signal_action_cue
        
        cue = format_signal_action_cue("generated", "long")
        assert "entry price" in cue
        assert "target price" not in cue

    def test_entered_signal_action_cue(self):
        """Entered signal action cue is appropriate."""
        from pearlalgo.utils.telegram_alerts import format_signal_action_cue
        
        cue = format_signal_action_cue("entered", "long")
        assert "ACTIVE" in cue or "Position" in cue

    def test_exited_signal_action_cue(self):
        """Exited signal action cue is appropriate."""
        from pearlalgo.utils.telegram_alerts import format_signal_action_cue
        
        cue = format_signal_action_cue("exited", "long")
        assert "completed" in cue.lower() or "review" in cue.lower()


# ---------------------------------------------------------------------------
# Integration test: Full callback routing
# ---------------------------------------------------------------------------

class TestCallbackRouting:
    """Test that callbacks route correctly through the handler."""

    def test_legacy_callbacks_resolve_before_routing(self):
        """Legacy callbacks are resolved to canonical form before routing."""
        from pearlalgo.utils.telegram_ui_contract import resolve_callback, parse_callback
        
        # Simulate what handle_callback does
        legacy_callbacks = ["start", "signals", "data_quality", "status"]
        
        for legacy in legacy_callbacks:
            canonical = resolve_callback(legacy)
            cb_type, action, param = parse_callback(canonical)
            
            # All should resolve to known types
            assert cb_type in ("menu", "action", "back", "confirm", "signal_detail", "patch", "aiops", "other")
            
            # start -> menu:main
            if legacy == "start":
                assert cb_type == "menu"
                assert action == "main"
            
            # signals -> menu:signals
            elif legacy == "signals":
                assert cb_type == "menu"
                assert action == "signals"
            
            # data_quality -> action:data_quality
            elif legacy == "data_quality":
                assert cb_type == "action"
                assert action == "data_quality"
            
            # status -> menu:status
            elif legacy == "status":
                assert cb_type == "menu"
                assert action == "status"
