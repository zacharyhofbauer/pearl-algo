"""
Chart render profiles for consistent, trust-preserving outputs.

Profiles should be small, explicit, and used across all chart entry points
so visual changes remain centralized and testable.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple

# Universal Telegram template size - taller to accommodate bottom panels (RSI, PnL, Volume).
# 12:10 aspect gives more vertical space for indicator panels while remaining mobile-friendly.
TELEGRAM_UNIFIED_FIGSIZE: Tuple[float, float] = (12.0, 10.0)  # 6:5 ratio, taller for panels
TELEGRAM_UNIFIED_DPI: int = 200

# Telegram render framing (minimize dead space but preserve title/readability).
TELEGRAM_UNIFIED_SAVE_PAD_INCHES: float = 0.12
TELEGRAM_UNIFIED_TOP_HEADROOM_PCT: float = 0.045


def apply_telegram_unified_profile(cfg: Any) -> None:
    """
    Apply the unified Telegram profile to a ChartConfig-like object.

    This intentionally mutates cfg in-place (mirrors production usage).
    """
    if cfg is None:
        return

    # Mobile-first layout and decluttering defaults.
    desired: Dict[str, Any] = {
        "mobile_mode": True,
        "compact_labels": True,
        "show_session_range_stats": False,
        "max_right_labels": 6,
        "right_label_merge_ticks": 6,
        # Panel ratios: balance price prominence with readable indicator panels.
        # Increased volume/sub ratios for better RSI/PnL visibility.
        "panel_ratio_price": 8.0,
        "panel_ratio_volume": 1.6,
        "panel_ratio_sub": 1.8,
        # Keep only the long-term EMA for cleaner Telegram charts.
        "ma_periods": [200],
        # TradingView-style volume panel (bars + MA line).
        "volume_overlay_in_price": False,
        "show_volume_ma": True,
        "volume_ma_period": 20,
        # Trade recap replaces pressure panel on Telegram.
        "show_trade_recap_panel": True,
        "show_pressure_panel": False,
        # Hide VWAP bands (keep main VWAP line).
        "vwap_show_bands": False,
        # Optional badges (only render if regime_info is provided).
        "show_regime_label": True,
        "show_ml_confidence": True,
    }

    for key, value in desired.items():
        try:
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        except Exception:
            # Best-effort; config fields can differ by version.
            pass


def telegram_unified_render_kwargs() -> Dict[str, Any]:
    """
    Render kwargs for Telegram charts using the unified template size.
    """
    return {
        "figsize": TELEGRAM_UNIFIED_FIGSIZE,
        "dpi": TELEGRAM_UNIFIED_DPI,
        "save_pad_inches": TELEGRAM_UNIFIED_SAVE_PAD_INCHES,
        "telegram_top_headroom_pct": TELEGRAM_UNIFIED_TOP_HEADROOM_PCT,
    }


def apply_telegram_trade_overlay_defaults(cfg: Any) -> None:
    """
    Apply the Telegram trade overlay defaults (detailed path-only).
    """
    if cfg is None:
        return

    desired: Dict[str, Any] = {
        # Path-only overlay (no entry/exit markers or letters).
        "smart_marker_show_letters": False,
        "smart_marker_show_entry": False,
        "smart_marker_show_exit": False,
        "smart_marker_show_path": True,
        # Detailed path-only styling.
        "smart_marker_path_arrowheads": True,
        "smart_marker_path_fade_by_age": True,
        "smart_marker_path_label_last_pnl": True,
    }

    for key, value in desired.items():
        try:
            if hasattr(cfg, key):
                setattr(cfg, key, value)
        except Exception:
            pass
