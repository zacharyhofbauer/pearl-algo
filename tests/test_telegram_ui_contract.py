"""Tests for pearlalgo.utils.telegram_ui_contract — pure functions, no mocking."""

from __future__ import annotations

import pytest

from pearlalgo.utils.telegram_ui_contract import (
    # Prefixes
    PREFIX_MENU,
    PREFIX_ACTION,
    PREFIX_CONFIRM,
    PREFIX_SIGNAL_DETAIL,
    PREFIX_PATCH,
    PREFIX_AIOPS,
    PREFIX_PEARL,
    # Functions
    connection_status_to_label,
    resolve_callback,
    parse_callback,
    build_callback,
    # Builder helpers
    callback_menu,
    callback_action,
    callback_signal_detail,
    callback_confirm,
    callback_back,
    callback_pearl,
    callback_pearl_dismiss,
    # Legacy map
    LEGACY_CALLBACK_ALIASES,
)


# ---------------------------------------------------------------------------
# connection_status_to_label
# ---------------------------------------------------------------------------

class TestConnectionStatusToLabel:
    def test_true(self):
        label, emoji = connection_status_to_label(True)
        assert label == "CONNECTED"
        assert emoji == "🟢"

    def test_false(self):
        label, emoji = connection_status_to_label(False)
        assert label == "DISCONNECTED"
        assert emoji == "🔴"

    def test_none(self):
        label, emoji = connection_status_to_label(None)
        assert label == "UNKNOWN"
        assert emoji == "⚪"

    def test_string_connected(self):
        label, _ = connection_status_to_label("connected")
        assert label == "CONNECTED"

    def test_string_disconnected(self):
        label, _ = connection_status_to_label("disconnected")
        assert label == "DISCONNECTED"

    def test_string_ok(self):
        label, _ = connection_status_to_label("ok")
        assert label == "CONNECTED"

    def test_unknown_string(self):
        label, emoji = connection_status_to_label("degraded")
        assert label == "DEGRADED"
        assert emoji == "⚪"


# ---------------------------------------------------------------------------
# resolve_callback
# ---------------------------------------------------------------------------

class TestResolveCallback:
    def test_empty(self):
        assert resolve_callback("") == ""

    def test_legacy_start(self):
        assert resolve_callback("start") == "menu:main"

    def test_legacy_signals(self):
        assert resolve_callback("signals") == "menu:activity"

    def test_legacy_data_quality(self):
        assert resolve_callback("data_quality") == "action:data_quality"

    def test_legacy_restart_agent(self):
        assert resolve_callback("restart_agent") == "confirm:restart_agent"

    def test_canonical_menu_signals_to_activity(self):
        assert resolve_callback("menu:signals") == "menu:activity"

    def test_canonical_action_active_trades(self):
        assert resolve_callback("action:active_trades") == "action:trades_overview"

    def test_legacy_signal_detail_underscore(self):
        assert resolve_callback("signal_detail_abc123") == "signal_detail:abc123"

    def test_already_canonical(self):
        assert resolve_callback("menu:main") == "menu:main"

    def test_unrecognized(self):
        assert resolve_callback("something_random") == "something_random"


# ---------------------------------------------------------------------------
# parse_callback
# ---------------------------------------------------------------------------

class TestParseCallback:
    def test_empty(self):
        assert parse_callback("") == ("other", "", None)

    def test_back(self):
        assert parse_callback("back") == ("back", "", None)

    def test_menu(self):
        assert parse_callback("menu:activity") == ("menu", "activity", None)

    def test_action_simple(self):
        assert parse_callback("action:data_quality") == ("action", "data_quality", None)

    def test_action_with_param(self):
        assert parse_callback("action:toggle_pref:auto_chart_on_signal") == (
            "action", "toggle_pref", "auto_chart_on_signal"
        )

    def test_confirm(self):
        assert parse_callback("confirm:restart_agent") == ("confirm", "restart_agent", None)

    def test_signal_detail(self):
        assert parse_callback("signal_detail:abc123") == ("signal_detail", "abc123", None)

    def test_patch(self):
        assert parse_callback("patch:fix_something") == ("patch", "fix_something", None)

    def test_aiops(self):
        assert parse_callback("aiops:diagnose") == ("aiops", "diagnose", None)

    def test_pearl(self):
        assert parse_callback("pearl:dismiss") == ("pearl", "dismiss", None)

    def test_unrecognized(self):
        assert parse_callback("random_thing") == ("other", "random_thing", None)


# ---------------------------------------------------------------------------
# build_callback
# ---------------------------------------------------------------------------

class TestBuildCallback:
    def test_back(self):
        assert build_callback("back", "") == "back"

    def test_menu(self):
        assert build_callback("menu", "activity") == "menu:activity"

    def test_action_no_param(self):
        assert build_callback("action", "data_quality") == "action:data_quality"

    def test_action_with_param(self):
        assert build_callback("action", "toggle_pref", "auto_chart") == "action:toggle_pref:auto_chart"

    def test_confirm(self):
        assert build_callback("confirm", "restart_agent") == "confirm:restart_agent"

    def test_signal_detail(self):
        assert build_callback("signal_detail", "abc123") == "signal_detail:abc123"

    def test_unknown_type(self):
        assert build_callback("something", "val") == "val"


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------

class TestCallbackBuilders:
    def test_callback_menu(self):
        assert callback_menu("main") == "menu:main"

    def test_callback_action(self):
        assert callback_action("data_quality") == "action:data_quality"

    def test_callback_action_with_param(self):
        assert callback_action("toggle_pref", "auto_chart") == "action:toggle_pref:auto_chart"

    def test_callback_signal_detail(self):
        assert callback_signal_detail("abc123") == "signal_detail:abc123"

    def test_callback_confirm(self):
        assert callback_confirm("restart_agent") == "confirm:restart_agent"

    def test_callback_back(self):
        assert callback_back() == "back"

    def test_callback_pearl(self):
        assert callback_pearl("check_data") == "pearl:check_data"

    def test_callback_pearl_dismiss(self):
        assert callback_pearl_dismiss() == "pearl:dismiss"


# ---------------------------------------------------------------------------
# Round-trip: build → parse
# ---------------------------------------------------------------------------

class TestRoundTrip:
    @pytest.mark.parametrize("cb_type,action,param", [
        ("menu", "main", None),
        ("menu", "activity", None),
        ("action", "data_quality", None),
        ("action", "toggle_pref", "auto_chart"),
        ("confirm", "restart_agent", None),
        ("signal_detail", "abc123", None),
    ])
    def test_build_then_parse(self, cb_type, action, param):
        built = build_callback(cb_type, action, param)
        parsed_type, parsed_action, parsed_param = parse_callback(built)
        assert parsed_type == cb_type
        assert parsed_action == action
        assert parsed_param == param
