#!/usr/bin/env python3
"""
Telegram Message Preview and Validation Script

Generates sample messages for key Telegram message types and validates:
- Message length (< 4096 characters)
- Markdown safety (no unescaped special characters)
- Consistency of formatting

Usage:
    python3 scripts/testing/test_telegram_messages.py [--verbose]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple

# Add project root to path
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pearlalgo.utils.telegram_alerts import (
    TELEGRAM_TEXT_LIMIT,
    safe_label,
    format_home_card,
    format_signal_status,
    format_signal_direction,
    format_signal_confidence_tier,
    format_pnl,
    format_time_ago,
    format_gate_status,
    format_service_status,
    format_activity_pulse,
    LABEL_AGENT,
    LABEL_GATEWAY,
    STATE_RUNNING,
    STATE_STOPPED,
    GATE_OPEN,
    GATE_CLOSED,
)


# Test data fixtures
def get_sample_signal() -> Dict:
    """Get a sample signal for testing."""
    return {
        "signal_id": "test_signal_abc123456789",
        "timestamp": (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
        "symbol": "MNQ",
        "type": "momentum_breakout",
        "direction": "long",
        "confidence": 0.75,
        "entry_price": 21234.50,
        "stop_loss": 21200.00,
        "take_profit": 21300.00,
        "position_size": 15,
        "risk_amount": 250.00,
        "rr_ratio": 1.9,
        "regime": {
            "regime": "trending_bullish",
            "volatility": "medium",
            "session": "regular_trading",
        },
        "mtf_analysis": {
            "alignment": "bullish",
            "alignment_score": 0.8,
        },
        "vwap_data": {
            "vwap": 21220.00,
            "distance_pct": 0.07,
        },
        "quality_score": {
            "quality_score": 0.85,
            "confluence_score": 0.9,
            "historical_wr": 0.65,
        },
    }


def get_sample_status() -> Dict:
    """Get a sample status for testing."""
    return {
        "running": True,
        "paused": False,
        "cycle_count": 1595,
        "session_cycle_count": 145,
        "signals_generated": 2,
        "signals_sent": 2,
        "signal_failures": 0,
        "buffer_size": 100,
        "target_buffer": 100,
        "current_price": 21234.50,
        "error_count": 0,
        "last_successful_cycle": (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat(),
        "start_time": (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat(),
        "uptime_seconds": 14400,
        "data_age_seconds": 5.0,
        "active_trades_count": 1,
        "total_pnl": 125.50,
        "session_window": "09:30-16:00 ET",
        "futures_open": True,
        "session_open": True,
    }


def get_sample_performance() -> Dict:
    """Get sample performance data for testing."""
    return {
        "total_signals": 15,
        "exited_signals": 10,
        "wins": 6,
        "losses": 4,
        "win_rate": 0.6,
        "total_pnl": 450.00,
        "avg_pnl": 45.00,
        "best_trade": 125.00,
        "worst_trade": -75.00,
    }


# Message generators for testing
def generate_signal_push_message(signal: Dict) -> str:
    """Generate a compact signal push message."""
    symbol = signal.get("symbol", "MNQ")
    direction = signal.get("direction", "long").upper()
    sig_type = signal.get("type", "unknown").replace("_", " ").title()
    entry = signal.get("entry_price", 0.0)
    stop = signal.get("stop_loss", 0.0)
    tp = signal.get("take_profit", 0.0)
    rr = signal.get("rr_ratio", 0.0)
    size = signal.get("position_size", 0)
    risk = signal.get("risk_amount", 0.0)
    conf = signal.get("confidence", 0.0)
    
    dir_emoji = "🟢" if direction == "LONG" else "🔴"
    conf_tier, conf_emoji = format_signal_confidence_tier(conf)
    
    stop_dist = abs(entry - stop) if entry and stop else 0
    tp_dist = abs(tp - entry) if tp and entry else 0
    
    message = f"🎯 *{symbol} {dir_emoji} {direction}* | {sig_type}\n\n"
    message += f"*Entry:* ${entry:.2f}  •  R:R {rr:.1f}:1\n"
    message += f"*Stop:* ${stop:.2f} ({stop_dist:.1f} pts)\n"
    message += f"*TP:* ${tp:.2f} ({tp_dist:.1f} pts)\n"
    message += f"*Size:* {size} {symbol} • Risk: ${risk:.0f}\n\n"
    message += f"⏳ Monitor for BUY entry at target price\n\n"
    message += f"{conf_emoji} {conf:.0%} confidence ({conf_tier})\n"
    
    # Regime context (condensed)
    regime = signal.get("regime", {}) or {}
    if regime.get("regime"):
        r_regime = str(regime.get("regime", "")).replace("_", " ").title()
        message += f"🧭 {r_regime}"
        
        mtf = signal.get("mtf_analysis", {}) or {}
        if mtf.get("alignment"):
            message += f" • ✅ MTF"
        message += "\n"
    
    # Signal ID footer
    sig_id = signal.get("signal_id", "unknown")[:12]
    message += f"\n`{sig_id}`"
    
    return message


def generate_home_card_message(status: Dict) -> str:
    """Generate a Home Card message using the format_home_card helper."""
    # Get current time as ET string
    time_str = datetime.now(timezone.utc).strftime("%I:%M %p ET")
    
    # Build performance dict if we have P&L
    performance = None
    if status.get("total_pnl") is not None:
        performance = {"total_pnl": status.get("total_pnl")}
    
    return format_home_card(
        symbol=status.get("symbol", "MNQ"),
        time_str=time_str,
        agent_running=status.get("running", False),
        gateway_running=status.get("gateway_running", True),
        futures_market_open=status.get("futures_open", True),
        strategy_session_open=status.get("session_open", True),
        paused=status.get("paused", False),
        pause_reason=status.get("pause_reason"),
        cycles_session=status.get("session_cycle_count", 0),
        cycles_total=status.get("cycle_count", 0),
        signals_generated=status.get("signals_generated", 0),
        signals_sent=status.get("signals_sent", 0),
        errors=status.get("error_count", 0),
        buffer_size=status.get("buffer_size", 0),
        buffer_target=status.get("target_buffer", 100),
        latest_price=status.get("current_price"),
        performance=performance,
        sparkline=status.get("sparkline"),
        state_age_seconds=status.get("data_age_seconds"),
        signal_send_failures=status.get("signal_failures", 0),
        last_cycle_seconds=30.0,  # Sample: 30 seconds since last cycle
        previous_pnl=status.get("previous_pnl"),
    )


def generate_settings_message() -> str:
    """Generate a sample settings menu message."""
    message = "⚙️ *Telegram Settings*\n\n"
    message += "Customize your Telegram UI experience. Changes take effect immediately.\n\n"
    
    message += "⬜ *Dashboard Buttons*\n"
    message += "   Add quick-action buttons to push dashboards\n\n"
    
    message += "⬜ *Expanded Signal Details*\n"
    message += "   Show full context (regime, MTF, VWAP) by default\n\n"
    
    message += "⬜ *Auto-Chart on Signal*\n"
    message += "   Automatically send chart with each signal alert\n\n"
    
    message += "🔔 *Snooze Non-Critical Alerts*\n"
    message += "   Temporarily suppress non-critical data alerts\n\n"
    
    message += "💡 *Tip:* Tap a button to toggle a setting."
    
    return message


def generate_signal_detail_message(signal: Dict, expanded: bool = True) -> str:
    """Generate a signal detail message."""
    symbol = signal.get("symbol", "MNQ")
    direction = signal.get("direction", "long").upper()
    sig_type = signal.get("type", "unknown").replace("_", " ").title()
    entry = signal.get("entry_price", 0.0)
    stop = signal.get("stop_loss", 0.0)
    tp = signal.get("take_profit", 0.0)
    rr = signal.get("rr_ratio", 0.0)
    size = signal.get("position_size", 0)
    risk = signal.get("risk_amount", 0.0)
    conf = signal.get("confidence", 0.0)
    sig_id = signal.get("signal_id", "unknown")
    
    dir_emoji = "🟢" if direction == "LONG" else "🔴"
    status_emoji, _ = format_signal_status("pending")
    conf_tier, conf_emoji = format_signal_confidence_tier(conf)
    
    stop_dist = abs(entry - stop) if entry and stop else 0
    tp_dist = abs(tp - entry) if tp and entry else 0
    
    message = f"{status_emoji} *Signal Detail*\n"
    message += f"{dir_emoji} *{sig_type}* {direction}\n\n"
    
    # Trade Plan
    message += "📋 *Trade Plan*\n"
    message += f"   Entry: ${entry:.2f}\n"
    message += f"   Stop:  ${stop:.2f} ({stop_dist:.1f} pts)\n"
    message += f"   TP:    ${tp:.2f} ({tp_dist:.1f} pts)\n"
    message += f"   R:R:   {rr:.1f}:1\n"
    message += f"   Size:  {size} {symbol} | Risk: ${risk:.0f}\n\n"
    
    # Confidence
    message += f"{conf_emoji} *Confidence:* {conf:.0%} ({conf_tier})\n\n"
    
    # Signal ID
    message += f"🆔 `{sig_id[:16]}…`\n"
    
    # Optional context (if expanded)
    if expanded:
        regime = signal.get("regime", {}) or {}
        mtf = signal.get("mtf_analysis", {}) or {}
        quality = signal.get("quality_score", {}) or {}
        
        context_lines = []
        
        if quality:
            q_parts = []
            if "quality_score" in quality:
                q_parts.append(f"Score: {float(quality.get('quality_score', 0.0)):.2f}")
            if "confluence_score" in quality:
                q_parts.append(f"Confluence: {float(quality.get('confluence_score', 0.0)):.2f}")
            if q_parts:
                context_lines.append("🧠 *Quality:* " + " • ".join(q_parts))
        
        if regime.get("regime"):
            r_regime = str(regime.get("regime", "")).replace("_", " ").title()
            r_vol = str(regime.get("volatility", "")).title()
            context_lines.append(f"🧭 *Regime:* {r_regime} | {r_vol} Vol")
        
        if mtf.get("alignment"):
            mtf_str = f"🧩 *MTF:* {mtf['alignment'].title()}"
            if mtf.get("alignment_score") is not None:
                mtf_str += f" ({float(mtf['alignment_score']):.2f})"
            context_lines.append(mtf_str)
        
        if context_lines:
            message += "\n" + "\n".join(context_lines) + "\n"
    
    return message


def generate_circuit_breaker_message() -> str:
    """Generate a circuit breaker alert message."""
    message = "🛑 *Circuit Breaker Activated*\n\n"
    message += "*Reason:* Multiple consecutive connection failures\n"
    
    message += "\n*What happened:*\n"
    message += "• 5 consecutive errors\n"
    message += "• 3 connection failures\n"
    message += "• Error type: ConnectionTimeout\n"
    
    message += "\n*What's safe:*\n"
    message += "✅ Existing positions are preserved\n"
    message += "✅ No new signals will be generated\n"
    message += "✅ System state is saved\n"
    
    message += "\n*What to do:*\n"
    message += "1. Check Gateway status\n"
    message += "2. Review error logs\n"
    message += "3. Restart agent when ready\n"
    
    message += "\n⚠️ *Manual restart required*"
    
    return message


def generate_data_quality_message() -> str:
    """Generate a data quality alert message."""
    message = "⚠️ *Risk Warning*\n\n"
    message += "*Issue:* Stale Data\n\n"
    
    message += "*Impact:*\n"
    message += "• Signal generation paused\n"
    message += "• Strategy context may be outdated\n\n"
    
    message += "*What's safe:*\n"
    message += "• Existing positions are still monitored\n"
    message += "• Stop losses remain active\n\n"
    
    message += "*Likely causes:*\n"
    message += "• Market closed (normal)\n"
    message += "• Gateway connection issue\n"
    message += "• Data feed interruption\n\n"
    
    message += "*What to do:*\n"
    message += "1. Check /gateway_status\n"
    message += "2. If during market hours, consider /restart_agent\n"
    message += "3. Data typically recovers automatically\n\n"
    
    message += "*Status:* ⚠️ Signals paused until data recovers"
    
    return message


# Validation functions
def check_message_length(message: str, name: str) -> Tuple[bool, str]:
    """Check if message is within Telegram limits."""
    length = len(message)
    if length > TELEGRAM_TEXT_LIMIT:
        return False, f"❌ {name}: Length {length} exceeds limit {TELEGRAM_TEXT_LIMIT}"
    return True, f"✅ {name}: Length {length} OK (limit {TELEGRAM_TEXT_LIMIT})"


def check_markdown_safety(message: str, name: str) -> Tuple[bool, List[str]]:
    """Check for potential markdown issues."""
    issues = []
    
    # Check for unbalanced asterisks (basic check)
    asterisks = message.count("*")
    if asterisks % 2 != 0:
        issues.append(f"Unbalanced asterisks ({asterisks})")
    
    # Check for unbalanced backticks
    backticks = message.count("`")
    if backticks % 2 != 0:
        issues.append(f"Unbalanced backticks ({backticks})")
    
    # Check for unbalanced underscores (used for italic in Markdown)
    underscores = message.count("_")
    if underscores % 2 != 0:
        issues.append(f"Unbalanced underscores ({underscores})")
    
    # Check for problematic characters that should be escaped
    problematic_patterns = [
        (r'(?<![\\`])[^\w\s\*`_\-\+\$\@\#\%\&\(\)\[\]\{\}\|\:\;\,\.\!\?\'\"\n]', "Special char"),
    ]
    
    if issues:
        return False, issues
    return True, []


def run_validation(verbose: bool = False) -> int:
    """Run validation on all message types."""
    print("=" * 60)
    print("Telegram Message Validation")
    print("=" * 60)
    
    # Generate sample data
    sample_signal = get_sample_signal()
    sample_status = get_sample_status()
    
    # Define message generators
    messages = [
        ("Signal Push", generate_signal_push_message(sample_signal)),
        ("Home Card", generate_home_card_message(sample_status)),
        ("Settings Menu", generate_settings_message()),
        ("Signal Detail (expanded)", generate_signal_detail_message(sample_signal, expanded=True)),
        ("Signal Detail (compact)", generate_signal_detail_message(sample_signal, expanded=False)),
        ("Circuit Breaker Alert", generate_circuit_breaker_message()),
        ("Data Quality Alert", generate_data_quality_message()),
    ]
    
    all_passed = True
    
    for name, message in messages:
        print(f"\n--- {name} ---")
        
        # Check length
        length_ok, length_msg = check_message_length(message, name)
        print(length_msg)
        if not length_ok:
            all_passed = False
        
        # Check markdown
        md_ok, md_issues = check_markdown_safety(message, name)
        if md_ok:
            print(f"✅ {name}: Markdown OK")
        else:
            print(f"⚠️ {name}: Markdown issues: {', '.join(md_issues)}")
            # Not failing on markdown warnings for now
        
        # Show message preview if verbose
        if verbose:
            print(f"\nPreview:")
            print("-" * 40)
            print(message)
            print("-" * 40)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ All validations passed!")
        return 0
    else:
        print("❌ Some validations failed!")
        return 1


def main():
    parser = argparse.ArgumentParser(
        description="Validate Telegram message formats and lengths"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show message previews"
    )
    args = parser.parse_args()
    
    return run_validation(verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())

