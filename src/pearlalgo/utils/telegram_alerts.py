"""
Backward compatibility: re-export from pearlalgo.notifications.

New code should use: from pearlalgo.notifications import ...

This module remains only to avoid breaking older imports. Do not add new
notification logic here.
"""

from __future__ import annotations

from pearlalgo.notifications.formats import *  # noqa: F401, F403  — controlled by formats.__all__
from pearlalgo.notifications.formats import (  # noqa: F401  — underscore names excluded from __all__
    _truncate_telegram_text,
    _format_uptime,
)
from pearlalgo.notifications.prefs import TelegramPrefs  # noqa: F401
from pearlalgo.notifications.alerts import TelegramAlerts  # noqa: F401
