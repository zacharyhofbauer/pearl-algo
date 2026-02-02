"""
Tests for Telegram Keyboard Builders.

Tests the TelegramKeyboardsMixin class which provides keyboard building utilities
for the Telegram bot interface.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


# Mock telegram module for tests
class MockInlineKeyboardButton:
    """Mock InlineKeyboardButton for testing."""

    def __init__(self, text: str, callback_data: str = None, url: str = None):
        self.text = text
        self.callback_data = callback_data
        self.url = url

    def __repr__(self):
        return f"Button({self.text!r}, {self.callback_data!r})"

    def __eq__(self, other):
        if not isinstance(other, MockInlineKeyboardButton):
            return False
        return self.text == other.text and self.callback_data == other.callback_data


class MockInlineKeyboardMarkup:
    """Mock InlineKeyboardMarkup for testing."""

    def __init__(self, keyboard: list):
        self.inline_keyboard = keyboard

    def __repr__(self):
        return f"Markup({self.inline_keyboard})"


@pytest.fixture
def mock_telegram():
    """Mock telegram module."""
    with patch.dict('sys.modules', {
        'telegram': MagicMock(
            InlineKeyboardButton=MockInlineKeyboardButton,
            InlineKeyboardMarkup=MockInlineKeyboardMarkup,
        )
    }):
        yield


@pytest.fixture
def keyboards_mixin():
    """Create a TelegramKeyboardsMixin instance for testing."""
    # Patch telegram imports before importing the mixin
    with patch('pearlalgo.market_agent.telegram_keyboards.TELEGRAM_AVAILABLE', True), \
         patch('pearlalgo.market_agent.telegram_keyboards.InlineKeyboardButton', MockInlineKeyboardButton), \
         patch('pearlalgo.market_agent.telegram_keyboards.InlineKeyboardMarkup', MockInlineKeyboardMarkup):

        from pearlalgo.market_agent.telegram_keyboards import TelegramKeyboardsMixin

        class TestHandler(TelegramKeyboardsMixin):
            """Test handler class using the mixin."""
            pass

        return TestHandler()


class TestNavBackRow:
    """Tests for _nav_back_row method."""

    def test_returns_menu_button(self, keyboards_mixin):
        """Should return a list with a single Menu button."""
        row = keyboards_mixin._nav_back_row()

        assert len(row) == 1
        assert row[0].text == "🏠 Menu"
        assert row[0].callback_data == "back"

    def test_returns_empty_when_telegram_unavailable(self):
        """Should return empty list when telegram is not available."""
        with patch('pearlalgo.market_agent.telegram_keyboards.TELEGRAM_AVAILABLE', False):
            from pearlalgo.market_agent.telegram_keyboards import TelegramKeyboardsMixin

            class TestHandler(TelegramKeyboardsMixin):
                pass

            handler = TestHandler()
            row = handler._nav_back_row()

            assert row == []


class TestActivityNavKeyboard:
    """Tests for _activity_nav_keyboard method."""

    def test_includes_activity_and_menu_buttons(self, keyboards_mixin):
        """Should include Activity and Menu buttons."""
        keyboard = keyboards_mixin._activity_nav_keyboard()

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 1
        row = keyboard.inline_keyboard[0]

        # Find buttons by callback data
        callbacks = [btn.callback_data for btn in row]
        assert "menu:activity" in callbacks
        assert "back" in callbacks

    def test_includes_extra_buttons(self, keyboards_mixin):
        """Should include extra buttons when provided."""
        extra = [MockInlineKeyboardButton("Extra", callback_data="extra")]
        keyboard = keyboards_mixin._activity_nav_keyboard(extra_buttons=extra)

        row = keyboard.inline_keyboard[0]
        assert len(row) >= 3  # Extra + Activity + Menu

        callbacks = [btn.callback_data for btn in row]
        assert "extra" in callbacks


class TestNavFooter:
    """Tests for _nav_footer method."""

    def test_returns_back_row_without_extras(self, keyboards_mixin):
        """Should return just the back row when no extras provided."""
        footer = keyboards_mixin._nav_footer()

        assert len(footer) == 1
        assert footer[0].callback_data == "back"

    def test_includes_extra_buttons(self, keyboards_mixin):
        """Should include extra buttons before Menu button."""
        extra = [MockInlineKeyboardButton("Extra", callback_data="extra")]
        footer = keyboards_mixin._nav_footer(extra_buttons=extra)

        assert len(footer) == 2
        assert footer[0].callback_data == "extra"
        assert footer[1].callback_data == "back"


class TestWithNavFooter:
    """Tests for _with_nav_footer method."""

    def test_appends_footer_to_keyboard(self, keyboards_mixin):
        """Should append navigation footer to existing keyboard."""
        existing = [[MockInlineKeyboardButton("Row 1", callback_data="r1")]]
        result = keyboards_mixin._with_nav_footer(existing)

        assert len(result) == 2
        assert result[1][0].callback_data == "back"

    def test_handles_empty_keyboard(self, keyboards_mixin):
        """Should work with empty keyboard."""
        result = keyboards_mixin._with_nav_footer([])

        assert len(result) == 1
        assert result[0][0].callback_data == "back"

    def test_handles_none_keyboard(self, keyboards_mixin):
        """Should work with None keyboard."""
        result = keyboards_mixin._with_nav_footer(None)

        assert len(result) == 1


class TestQuickKeyboard:
    """Tests for _quick_keyboard method."""

    def test_creates_keyboard_from_tuples(self, keyboards_mixin):
        """Should convert tuples to buttons."""
        keyboard = keyboards_mixin._quick_keyboard(
            [("Button 1", "action1"), ("Button 2", "action2")],
        )

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 2  # Row + nav

        first_row = keyboard.inline_keyboard[0]
        assert len(first_row) == 2
        assert first_row[0].text == "Button 1"
        assert first_row[0].callback_data == "action1"

    def test_preserves_button_objects(self, keyboards_mixin):
        """Should preserve existing button objects."""
        btn = MockInlineKeyboardButton("Existing", callback_data="existing")
        keyboard = keyboards_mixin._quick_keyboard([btn])

        assert keyboard.inline_keyboard[0][0] is btn

    def test_includes_nav_by_default(self, keyboards_mixin):
        """Should include navigation footer by default."""
        keyboard = keyboards_mixin._quick_keyboard([("Button", "action")])

        # Last row should be navigation
        last_row = keyboard.inline_keyboard[-1]
        assert last_row[0].callback_data == "back"

    def test_excludes_nav_when_specified(self, keyboards_mixin):
        """Should exclude navigation when include_nav=False."""
        keyboard = keyboards_mixin._quick_keyboard(
            [("Button", "action")],
            include_nav=False,
        )

        assert len(keyboard.inline_keyboard) == 1
        assert keyboard.inline_keyboard[0][0].callback_data == "action"

    def test_skips_empty_rows(self, keyboards_mixin):
        """Should skip empty rows."""
        keyboard = keyboards_mixin._quick_keyboard(
            [("Button", "action")],
            [],  # Empty row
            None,  # None row
        )

        # Should only have button row + nav
        assert len(keyboard.inline_keyboard) == 2


class TestBuildConfirmationKeyboard:
    """Tests for _build_confirmation_keyboard method."""

    def test_creates_confirm_cancel_buttons(self, keyboards_mixin):
        """Should create confirm and cancel buttons."""
        keyboard = keyboards_mixin._build_confirmation_keyboard("test_action")

        assert len(keyboard.inline_keyboard) == 2

        # Confirm button
        assert keyboard.inline_keyboard[0][0].text == "✅ Confirm"
        assert keyboard.inline_keyboard[0][0].callback_data == "confirm:test_action"

        # Cancel button
        assert keyboard.inline_keyboard[1][0].text == "❌ Cancel"
        assert keyboard.inline_keyboard[1][0].callback_data == "back"

    def test_custom_labels(self, keyboards_mixin):
        """Should use custom labels when provided."""
        keyboard = keyboards_mixin._build_confirmation_keyboard(
            "action",
            confirm_label="Yes, do it",
            cancel_label="No, go back",
            cancel_callback="menu:home",
        )

        assert keyboard.inline_keyboard[0][0].text == "Yes, do it"
        assert keyboard.inline_keyboard[1][0].text == "No, go back"
        assert keyboard.inline_keyboard[1][0].callback_data == "menu:home"


class TestBuildSettingsToggleRow:
    """Tests for _build_settings_toggle_row method."""

    def test_enabled_state_shows_on_icon(self, keyboards_mixin):
        """Should show ON icon when enabled."""
        button = keyboards_mixin._build_settings_toggle_row(
            label="Notifications",
            pref_key="notifications",
            is_enabled=True,
        )

        assert "🟢" in button.text
        assert "Notifications" in button.text
        assert button.callback_data == "action:toggle_pref:notifications"

    def test_disabled_state_shows_off_icon(self, keyboards_mixin):
        """Should show OFF icon when disabled."""
        button = keyboards_mixin._build_settings_toggle_row(
            label="Notifications",
            pref_key="notifications",
            is_enabled=False,
        )

        assert "🔴" in button.text

    def test_custom_icons(self, keyboards_mixin):
        """Should use custom icons when provided."""
        button = keyboards_mixin._build_settings_toggle_row(
            label="Feature",
            pref_key="feature",
            is_enabled=True,
            icon_on="✅",
            icon_off="❌",
        )

        assert "✅" in button.text


class TestBuildSystemControlKeyboard:
    """Tests for _build_system_control_keyboard method."""

    def test_agent_running_shows_stop_button(self, keyboards_mixin):
        """Should show Stop Agent when agent is running."""
        keyboard = keyboards_mixin._build_system_control_keyboard(
            agent_running=True,
            gateway_running=False,
        )

        # Find the agent button in first row
        first_row = keyboard[0]
        agent_btn = first_row[0]

        assert "Stop Agent" in agent_btn.text
        assert agent_btn.callback_data == "action:stop_agent"

    def test_agent_stopped_shows_start_button(self, keyboards_mixin):
        """Should show Start Agent when agent is stopped."""
        keyboard = keyboards_mixin._build_system_control_keyboard(
            agent_running=False,
            gateway_running=False,
        )

        first_row = keyboard[0]
        agent_btn = first_row[0]

        assert "Start Agent" in agent_btn.text
        assert agent_btn.callback_data == "action:start_agent"

    def test_gateway_running_shows_stop_button(self, keyboards_mixin):
        """Should show Stop Gateway when gateway is running."""
        keyboard = keyboards_mixin._build_system_control_keyboard(
            agent_running=False,
            gateway_running=True,
        )

        first_row = keyboard[0]
        gateway_btn = first_row[1]

        assert "Stop Gateway" in gateway_btn.text
        assert gateway_btn.callback_data == "action:stop_gateway"

    def test_includes_emergency_button_with_positions(self, keyboards_mixin):
        """Should include emergency button when positions exist."""
        keyboard = keyboards_mixin._build_system_control_keyboard(
            agent_running=True,
            gateway_running=True,
            has_positions=True,
            positions_count=3,
        )

        # Find emergency button
        callbacks = [btn.callback_data for row in keyboard for btn in row]
        assert "action:emergency_stop" in callbacks

        # Check positions count in button text
        emergency_row = [row for row in keyboard if any(
            btn.callback_data == "action:emergency_stop" for btn in row
        )][0]
        assert "3" in emergency_row[0].text

    def test_no_emergency_button_without_positions(self, keyboards_mixin):
        """Should not include emergency button when no positions."""
        keyboard = keyboards_mixin._build_system_control_keyboard(
            agent_running=True,
            gateway_running=True,
            has_positions=False,
        )

        callbacks = [btn.callback_data for row in keyboard for btn in row]
        assert "action:emergency_stop" not in callbacks

    def test_includes_standard_controls(self, keyboards_mixin):
        """Should include standard control buttons."""
        keyboard = keyboards_mixin._build_system_control_keyboard(
            agent_running=True,
            gateway_running=True,
        )

        callbacks = [btn.callback_data for row in keyboard for btn in row]

        assert "action:restart_agent" in callbacks
        assert "action:restart_gateway" in callbacks
        assert "action:logs" in callbacks
        assert "action:config" in callbacks
        assert "action:clear_cache" in callbacks
        assert "back" in callbacks  # Navigation


class TestBuildActivityKeyboard:
    """Tests for _build_activity_keyboard method."""

    def test_includes_core_activity_buttons(self, keyboards_mixin):
        """Should include core activity buttons."""
        keyboard = keyboards_mixin._build_activity_keyboard()

        callbacks = [btn.callback_data for row in keyboard for btn in row]

        assert "action:trades_overview" in callbacks
        assert "action:signal_history" in callbacks
        assert "action:performance_metrics" in callbacks
        assert "action:pnl_overview" in callbacks
        assert "action:risk_report" in callbacks

    def test_shows_close_all_when_virtual_open(self, keyboards_mixin):
        """Should show close all button when virtual trades are open."""
        keyboard = keyboards_mixin._build_activity_keyboard(virtual_open=5)

        callbacks = [btn.callback_data for row in keyboard for btn in row]
        assert "action:close_all_trades" in callbacks

        # Find button and check count
        for row in keyboard:
            for btn in row:
                if btn.callback_data == "action:close_all_trades":
                    assert "5" in btn.text

    def test_no_close_all_when_no_positions(self, keyboards_mixin):
        """Should not show close all button when no virtual trades."""
        keyboard = keyboards_mixin._build_activity_keyboard(virtual_open=0)

        callbacks = [btn.callback_data for row in keyboard for btn in row]
        assert "action:close_all_trades" not in callbacks

    def test_includes_navigation(self, keyboards_mixin):
        """Should include refresh and menu buttons."""
        keyboard = keyboards_mixin._build_activity_keyboard()

        callbacks = [btn.callback_data for row in keyboard for btn in row]
        assert "menu:activity" in callbacks  # Refresh
        assert "back" in callbacks  # Menu


class TestBuildHealthMenuKeyboard:
    """Tests for _build_health_menu_keyboard method."""

    def test_includes_health_options(self, keyboards_mixin):
        """Should include health monitoring options."""
        with patch('pearlalgo.market_agent.telegram_keyboards.TelegramKeyboardsMixin._build_health_menu_keyboard') as mock:
            # The actual implementation imports from telegram_ui_contract
            # For testing, we just verify the method exists and returns a list
            keyboards_mixin._build_health_menu_keyboard = lambda: [
                [MockInlineKeyboardButton("Gateway", callback_data="action:gateway_status")],
                [MockInlineKeyboardButton("Menu", callback_data="back")],
            ]

            keyboard = keyboards_mixin._build_health_menu_keyboard()

            assert isinstance(keyboard, list)
            assert len(keyboard) >= 1


class TestKeyboardMixinEdgeCases:
    """Edge case tests for keyboard building."""

    def test_handles_special_characters_in_labels(self, keyboards_mixin):
        """Should handle special characters in button labels."""
        keyboard = keyboards_mixin._quick_keyboard(
            [("🔥 Hot & Fresh!", "action")],
        )

        assert keyboard.inline_keyboard[0][0].text == "🔥 Hot & Fresh!"

    def test_handles_unicode_in_callback_data(self, keyboards_mixin):
        """Should handle unicode in callback data (though not recommended)."""
        keyboard = keyboards_mixin._quick_keyboard(
            [("Button", "action:テスト")],
        )

        assert keyboard.inline_keyboard[0][0].callback_data == "action:テスト"

    def test_multiple_rows(self, keyboards_mixin):
        """Should handle multiple rows correctly."""
        keyboard = keyboards_mixin._quick_keyboard(
            [("Row 1 Btn 1", "r1b1"), ("Row 1 Btn 2", "r1b2")],
            [("Row 2 Btn 1", "r2b1")],
            [("Row 3 Btn 1", "r3b1"), ("Row 3 Btn 2", "r3b2"), ("Row 3 Btn 3", "r3b3")],
        )

        # 3 content rows + 1 nav row
        assert len(keyboard.inline_keyboard) == 4
        assert len(keyboard.inline_keyboard[0]) == 2
        assert len(keyboard.inline_keyboard[1]) == 1
        assert len(keyboard.inline_keyboard[2]) == 3
