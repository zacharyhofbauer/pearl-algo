"""
Backward compatibility: re-export from pearlalgo.notifications.

New code should use: from pearlalgo.notifications import ...
"""

from __future__ import annotations

from pearlalgo.notifications.formats import *  # noqa: F401, F403
from pearlalgo.notifications.formats import (  # noqa: F401
    _truncate_telegram_text,
    _format_uptime,
)
from pearlalgo.notifications.prefs import TelegramPrefs
from pearlalgo.notifications.alerts import TelegramAlerts
