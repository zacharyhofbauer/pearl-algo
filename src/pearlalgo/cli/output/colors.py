"""Color scheme definitions for consistent console output."""

from typing import Literal

# Color scheme for trading console
class Colors:
    """Standardized color scheme for trading operations."""
    
    # Status colors
    SUCCESS = "green"
    WARNING = "yellow"
    ERROR = "red"
    INFO = "cyan"
    DATA = "blue"
    RISK = "magenta"
    DIM = "dim"
    
    # Trade direction colors
    BUY = "bold green"
    SELL = "bold red"
    FLAT = "dim white"
    
    # Risk status colors
    RISK_OK = "green"
    RISK_NEAR_LIMIT = "yellow"
    RISK_HARD_STOP = "red"
    RISK_COOLDOWN = "yellow"
    RISK_PAUSED = "red"
    
    # P&L colors
    PNL_POSITIVE = "green"
    PNL_NEGATIVE = "red"
    PNL_NEUTRAL = "dim"
    
    # Border styles
    BORDER_SUCCESS = "green"
    BORDER_WARNING = "yellow"
    BORDER_ERROR = "red"
    BORDER_INFO = "cyan"
    BORDER_DEFAULT = "cyan"

# Emoji/icons for visual clarity
class Icons:
    """Standardized icons/emojis for console output."""
    
    # Status icons
    SUCCESS = "✅"
    WARNING = "⚠️"
    ERROR = "❌"
    INFO = "ℹ️"
    
    # Trading icons
    BUY = "🟢"
    SELL = "🔴"
    FLAT = "⚪"
    TRADE = "💰"
    POSITION = "📊"
    
    # System icons
    GATEWAY = "🔌"
    DATA = "📥"
    SIGNAL = "📋"
    REPORT = "📄"
    RISK = "⚠️"
    ANALYSIS = "🧠"
    CYCLE = "🔄"
    
    # Direction indicators
    LONG = "📈"
    SHORT = "📉"
    FLAT_DIR = "➖"

