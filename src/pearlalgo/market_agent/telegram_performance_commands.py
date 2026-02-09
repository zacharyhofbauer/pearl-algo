"""
Telegram Performance Commands Mixin

Contains performance-related command handlers for the Telegram interface.
Can be composed into TelegramCommandHandler via multiple inheritance.

Usage:
    class TelegramCommandHandler(TelegramPerformanceCommandsMixin, ...):
        ...
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Optional

from pearlalgo.utils.logger import logger
from pearlalgo.market_agent.stats_computation import get_trading_day_start
from pearlalgo.utils.paths import parse_utc_timestamp

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
except ImportError:  # pragma: no cover
    pass

if TYPE_CHECKING:
    from pearlalgo.market_agent.telegram_command_handler import TelegramCommandHandler


class TelegramPerformanceCommandsMixin:
    """
    Mixin providing performance-related command handlers.

    Methods:
    - _show_performance_menu: Display performance dashboard
    - _show_analytics_menu: Display analytics with session/hourly breakdown
    - _handle_performance_metrics: Display performance metrics
    - _handle_daily_summary: Display daily trading summary
    - _handle_weekly_summary: Display weekly trading summary
    - _handle_pnl_overview: Display P&L overview
    - _handle_export_performance: Export performance report
    """

    async def _show_analytics_menu(self: "TelegramCommandHandler", query: CallbackQuery) -> None:
        """Show performance analytics with session and hourly breakdown."""
        try:
            from datetime import datetime, timezone, timedelta
            from collections import defaultdict
            import json
            try:
                from zoneinfo import ZoneInfo
                et_tz = ZoneInfo("America/New_York")
            except Exception as e:
                logger.debug(f"Non-critical: {e}", exc_info=True)
                # Fallback (no DST) — still safer than crashing
                et_tz = timezone(timedelta(hours=-5))
            
            lines = ["🔬 *Performance Analytics*", ""]
            
            # Load all trades from performance.json
            perf_file = self.state_dir / "performance.json"
            if not perf_file.exists():
                lines.append("No performance data available yet.")
                lines.append("Start trading to see analytics.")
            else:
                with open(perf_file, 'r') as f:
                    all_trades = json.load(f)
                
                if not all_trades:
                    lines.append("No trades recorded yet.")
                else:
                    # Defensive: perf file should be a list; tolerate bad shapes.
                    if not isinstance(all_trades, list):
                        all_trades = []

                    def _parse_dt(val) -> datetime | None:
                        if not val:
                            return None
                        try:
                            s = str(val).strip().replace("Z", "+00:00")
                            # Strip fractional seconds when offset is present (fromisoformat can be finicky)
                            if "." in s and "+" in s:
                                parts = s.split("+", 1)
                                base = parts[0].split(".", 1)[0]
                                s = base + "+" + parts[1]
                            dt = datetime.fromisoformat(s)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=timezone.utc)
                            return dt
                        except Exception as e:
                            logger.debug(f"Non-critical: {e}", exc_info=True)
                            return None

                    # De-dupe by signal_id to prevent any double-counting in analytics
                    # if the performance log ever accumulates duplicate exits.
                    by_id: dict[str, dict] = {}
                    no_id: list[dict] = []
                    for t in all_trades:
                        if not isinstance(t, dict):
                            continue
                        sid = str(t.get("signal_id") or "").strip()
                        if not sid:
                            no_id.append(t)
                            continue
                        prev = by_id.get(sid)
                        if prev is None:
                            by_id[sid] = t
                            continue
                        dt_new = _parse_dt(t.get("exit_time") or t.get("entry_time"))
                        dt_old = _parse_dt(prev.get("exit_time") or prev.get("entry_time"))
                        if dt_old is None and dt_new is not None:
                            by_id[sid] = t
                        elif dt_old is not None and dt_new is not None and dt_new > dt_old:
                            by_id[sid] = t
                    all_trades = list(by_id.values()) + no_id

                    total_trades = len(all_trades)
                    total_wins = sum(1 for t in all_trades if isinstance(t, dict) and t.get("is_win"))
                    total_pnl = sum(float((t or {}).get("pnl", 0) or 0) for t in all_trades if isinstance(t, dict))
                    overall_wr = (total_wins / total_trades * 100) if total_trades > 0 else 0
                    
                    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                    lines.append(f"*Overall:* {total_trades} trades | {overall_wr:.0f}% WR | {pnl_emoji} ${total_pnl:,.2f}")
                    lines.append("")
                    
                    # Session breakdown
                    sessions = {
                        'overnight': (18, 4),      # 6PM - 4AM ET
                        'premarket': (4, 6),       # 4AM - 6AM ET
                        'morning': (6, 10),        # 6AM - 10AM ET
                        'midday': (10, 14),        # 10AM - 2PM ET
                        'afternoon': (14, 17),     # 2PM - 5PM ET
                        'close': (17, 18),         # 5PM - 6PM ET
                    }
                    
                    session_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0})
                    
                    for t in all_trades:
                        if not isinstance(t, dict):
                            continue
                        time_str = t.get("exit_time") or t.get("entry_time")
                        dt = _parse_dt(time_str)
                        if dt is None:
                            continue
                        try:
                            et_hour = int(dt.astimezone(et_tz).hour)
                            
                            session_name = 'other'
                            for sname, (start, end) in sessions.items():
                                if start > end:  # overnight wraps
                                    if et_hour >= start or et_hour < end:
                                        session_name = sname
                                        break
                                elif start <= et_hour < end:
                                    session_name = sname
                                    break
                            
                            if t.get("is_win"):
                                session_stats[session_name]['wins'] += 1
                            else:
                                session_stats[session_name]['losses'] += 1
                            session_stats[session_name]['pnl'] += float(t.get("pnl", 0) or 0)
                        except Exception as e:
                            logger.debug(f"Non-critical: {e}", exc_info=True)
                    
                    lines.append("*📅 Session Performance:*")
                    session_order = ['overnight', 'premarket', 'morning', 'midday', 'afternoon', 'close']
                    for sname in session_order:
                        data = session_stats[sname]
                        count = data['wins'] + data['losses']
                        if count > 0:
                            wr = (data['wins'] / count * 100)
                            pnl = data['pnl']
                            emoji = "🟢" if pnl >= 0 else "🔴"
                            # Highlight best/worst sessions
                            if wr >= 55:
                                indicator = "✅"
                            elif wr <= 30:
                                indicator = "⚠️"
                            else:
                                indicator = "•"
                            lines.append(f"{indicator} {sname.title()}: {wr:.0f}% WR | {emoji} ${pnl:,.0f}")
                    
                    lines.append("")
                    
                    # Top hours
                    hour_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0})
                    for t in all_trades:
                        if not isinstance(t, dict):
                            continue
                        time_str = t.get("exit_time") or t.get("entry_time")
                        dt = _parse_dt(time_str)
                        if dt is None:
                            continue
                        try:
                            et_hour = int(dt.astimezone(et_tz).hour)
                            
                            if t.get("is_win"):
                                hour_stats[et_hour]['wins'] += 1
                            else:
                                hour_stats[et_hour]['losses'] += 1
                            hour_stats[et_hour]['pnl'] += float(t.get("pnl", 0) or 0)
                        except Exception as e:
                            logger.debug(f"Non-critical: {e}", exc_info=True)
                    
                    # Find best and worst hours
                    hours_with_data = [(h, d) for h, d in hour_stats.items() if d['wins'] + d['losses'] >= 5]
                    if hours_with_data:
                        # Sort by P&L
                        sorted_hours = sorted(hours_with_data, key=lambda x: x[1]['pnl'], reverse=True)
                        
                        lines.append("*⏰ Best Hours (ET):*")
                        for h, data in sorted_hours[:3]:
                            count = data['wins'] + data['losses']
                            wr = (data['wins'] / count * 100) if count > 0 else 0
                            pnl = data['pnl']
                            if pnl > 0:
                                lines.append(f"🔥 {h:02d}:00: {wr:.0f}% WR | +${pnl:,.0f}")
                        
                        lines.append("")
                        lines.append("*⏰ Worst Hours (ET):*")
                        for h, data in sorted_hours[-3:]:
                            count = data['wins'] + data['losses']
                            wr = (data['wins'] / count * 100) if count > 0 else 0
                            pnl = data['pnl']
                            if pnl < 0:
                                lines.append(f"❄️ {h:02d}:00: {wr:.0f}% WR | -${abs(pnl):,.0f}")
                    
                    # Hold duration insight
                    lines.append("")
                    duration_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'pnl': 0.0})
                    for t in all_trades:
                        if not isinstance(t, dict):
                            continue
                        hold_mins = t.get("hold_duration_minutes", 0) or 0
                        if hold_mins < 30:
                            bucket = 'Quick (<30m)'
                        elif hold_mins < 60:
                            bucket = 'Medium (30-60m)'
                        else:
                            bucket = 'Long (60m+)'
                        
                        if t.get("is_win"):
                            duration_stats[bucket]['wins'] += 1
                        else:
                            duration_stats[bucket]['losses'] += 1
                        duration_stats[bucket]['pnl'] += float(t.get("pnl", 0) or 0)
                    
                    lines.append("*⏱️ Hold Duration:*")
                    for bucket in ['Quick (<30m)', 'Medium (30-60m)', 'Long (60m+)']:
                        data = duration_stats[bucket]
                        count = data['wins'] + data['losses']
                        if count > 0:
                            wr = (data['wins'] / count * 100)
                            pnl = data['pnl']
                            emoji = "🟢" if pnl >= 0 else "🔴"
                            lines.append(f"• {bucket}: {wr:.0f}% WR | {emoji} ${pnl:,.0f}")
            
            text = "\n".join(lines)
            
            keyboard = [
                [
                    InlineKeyboardButton("🔄 Refresh", callback_data="menu:analytics"),
                ],
                [
                    InlineKeyboardButton("📊 Back to Activity", callback_data="menu:activity"),
                    self._nav_back_row()[0],
                ],
            ]
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._safe_edit_or_send(query, text, reply_markup=reply_markup, parse_mode="Markdown")
            
        except Exception as e:
            logger.error(f"Error in _show_analytics_menu: {e}", exc_info=True)
            keyboard = [
                [InlineKeyboardButton("📊 Back to Activity", callback_data="menu:activity")],
                self._nav_back_row(),
            ]
            await self._safe_edit_or_send(
                query, 
                f"🔬 Analytics\n\n❌ Error loading analytics: {str(e)[:100]}", 
                reply_markup=InlineKeyboardMarkup(keyboard)
            )


    async def _show_performance_menu(self: "TelegramCommandHandler", query: CallbackQuery) -> None:
        """Show performance submenu with trends, comparisons, and insights."""
        try:
            # Get comprehensive performance data
            state = self._read_state()
            metrics = self._read_latest_metrics()
            
            # Build rich performance overview
            lines = ["💎 *Performance Dashboard*", ""]
            
            # Today's Performance
            if state:
                daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                daily_trades = state.get("daily_trades", 0) or 0
                daily_wins = state.get("daily_wins", 0) or 0
                daily_losses = state.get("daily_losses", 0) or 0
                
                lines.append("*Today:*")
                if daily_pnl != 0:
                    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                    pnl_sign = "+" if daily_pnl >= 0 else ""
                    # Add trend indicator
                    trend = "↗️" if daily_pnl > 0 else "↘️" if daily_pnl < 0 else "→"
                    lines.append(f"{pnl_emoji} P&L: {trend} {pnl_sign}${abs(daily_pnl):.2f}")
                else:
                    lines.append("• P&L: $0.00")
                
                if daily_trades > 0:
                    win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0
                    wr_emoji = "🟢" if win_rate >= 50 else "🟡" if win_rate >= 40 else "🔴"
                    lines.append(f"• Trades: {daily_trades} ({daily_wins}W/{daily_losses}L)")
                    lines.append(f"• Win Rate: {wr_emoji} {win_rate:.0f}%")
                lines.append("")
            
            # Overall Performance (if metrics available)
            if metrics:
                total_trades = metrics.get("exited_signals", 0)
                total_pnl = float(metrics.get("total_pnl", 0.0) or 0.0)
                win_rate = float(metrics.get("win_rate", 0.0) or 0.0) * 100
                
                lines.append("*Overall:*")
                lines.append(f"• Total Trades: {total_trades}")
                if total_pnl != 0:
                    pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                    pnl_sign = "+" if total_pnl >= 0 else ""
                    lines.append(f"• Total P&L: {pnl_emoji} {pnl_sign}${abs(total_pnl):.2f}")
                if total_trades > 0:
                    wr_emoji = "🟢" if win_rate >= 50 else "🟡" if win_rate >= 40 else "🔴"
                    lines.append(f"• Win Rate: {wr_emoji} {win_rate:.1f}%")
                lines.append("")
            
            # Smart insights
            insights = []
            if state:
                daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                if daily_pnl < 0 and abs(daily_pnl) > 100:
                    insights.append("⚠️ *Alert:* Significant daily loss - consider reviewing strategy")
                elif daily_pnl > 200:
                    insights.append("✨ *Great:* Strong daily performance!")
            
            if metrics:
                win_rate = float(metrics.get("win_rate", 0.0) or 0.0) * 100
                if win_rate < 40:
                    insights.append("💡 *Tip:* Win rate below 40% - review signal quality")
                elif win_rate > 60:
                    insights.append("🎯 *Excellent:* Win rate above 60%!")
            
            if insights:
                lines.extend(insights)
                lines.append("")
            
            lines.append("*Select a report:*")
            
            # Build dynamic button labels
            daily_pnl_label = "📊 Daily Summary"
            pnl_overview_label = "💰 P&L Overview"
            metrics_label = "📈 Performance Metrics"
            
            if state:
                daily_pnl = float(state.get("daily_pnl", 0.0) or 0.0)
                if daily_pnl != 0:
                    pnl_emoji = "🟢" if daily_pnl >= 0 else "🔴"
                    pnl_sign = "+" if daily_pnl >= 0 else ""
                    daily_pnl_label = f"📊 Daily {pnl_emoji}{pnl_sign}${abs(daily_pnl):.0f}"
                    pnl_overview_label = f"💰 P&L {pnl_emoji}{pnl_sign}${abs(daily_pnl):.0f}"
            
            if metrics:
                total_trades = metrics.get("exited_signals", 0)
                metrics_label = f"📈 Metrics • {total_trades} Trades"
            
            keyboard = [
                # Row 1: Core Metrics
                [
                    InlineKeyboardButton(metrics_label, callback_data="action:performance_metrics"),
                    InlineKeyboardButton(pnl_overview_label, callback_data="action:pnl_overview"),
                ],
                # Row 2: Time-based Reports
                [
                    InlineKeyboardButton(daily_pnl_label, callback_data="action:daily_summary"),
                    InlineKeyboardButton("📉 Weekly Summary", callback_data="action:weekly_summary"),
                ],
                # Row 3: Actions
                [
                    InlineKeyboardButton("🔄 Reset Stats", callback_data="action:reset_performance"),
                    InlineKeyboardButton("📋 Export Report", callback_data="action:export_performance"),
                ],
                # Row 4: Navigation
                self._nav_back_row(),
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await self._safe_edit_or_send(query, "\n".join(lines), reply_markup=reply_markup, parse_mode="Markdown")
        except Exception as e:
            logger.error(f"Error in _show_performance_menu: {e}", exc_info=True)
            # Fallback to simple menu
            keyboard = [
                [
                    InlineKeyboardButton("📈 Performance Metrics", callback_data="action:performance_metrics"),
                    InlineKeyboardButton("💰 P&L Overview", callback_data="action:pnl_overview"),
                ],
                self._nav_back_row(),
            ]
            await self._safe_edit_or_send(
                query,
                "💎 Performance\n\nSelect an option:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )


    async def _handle_performance_metrics(self: "TelegramCommandHandler", query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display performance metrics from performance.json."""
        text = "📈 *Performance Metrics*\n\n"
        
        # Load performance.json for comprehensive metrics
        try:
            perf_file = self.state_dir / "performance.json"
            if perf_file.exists():
                with open(perf_file, 'r') as f:
                    all_trades = json.load(f)
                
                if all_trades:
                    now = datetime.now(timezone.utc)
                    
                    # 7-day metrics
                    cutoff_7d = now - timedelta(days=7)
                    trades_7d = []
                    for t in all_trades:
                        try:
                            ts = t.get("exit_time") or t.get("entry_time")
                            if ts:
                                ts_str = str(ts).replace('Z', '+00:00')
                                dt = datetime.fromisoformat(ts_str.split('.')[0] + '+00:00' if '.' in ts_str and '+' not in ts_str else ts_str)
                                if dt.tzinfo is None:
                                    dt = dt.replace(tzinfo=timezone.utc)
                                if dt >= cutoff_7d:
                                    trades_7d.append(t)
                        except Exception as e:
                            logger.debug(f"Non-critical: {e}", exc_info=True)
                    
                    if trades_7d:
                        total_trades = len(trades_7d)
                        wins = sum(1 for t in trades_7d if t.get('is_win'))
                        losses = total_trades - wins
                        total_pnl = sum(float(t.get('pnl', 0) or 0) for t in trades_7d)
                        win_rate = (wins / total_trades * 100) if total_trades > 0 else 0
                        
                        # Calculate profit factor correctly
                        winning_trades = [t for t in trades_7d if t.get('is_win')]
                        losing_trades = [t for t in trades_7d if not t.get('is_win')]
                        gross_profit = sum(float(t.get('pnl', 0) or 0) for t in winning_trades)
                        gross_loss = abs(sum(float(t.get('pnl', 0) or 0) for t in losing_trades))
                        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
                        
                        avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0
                        avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0
                        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
                        
                        # Calculate avg hold time
                        hold_times = []
                        for t in trades_7d:
                            hold_mins = t.get('hold_duration_minutes', 0) or 0
                            if hold_mins > 0:
                                hold_times.append(hold_mins)
                        avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0
                        
                        pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                        wr_emoji = "🟢" if win_rate >= 50 else "🟡" if win_rate >= 40 else "🔴"
                        pf_emoji = "✨" if profit_factor >= 1.5 else ("📊" if profit_factor >= 1.0 else "⚠️")
                        
                        text += "*7-Day Summary:*\n"
                        text += f"  Trades: {total_trades} ({wins}W / {losses}L)\n"
                        text += f"  Win Rate: {wr_emoji} {win_rate:.1f}%\n"
                        text += f"  Total P&L: {pnl_emoji} ${total_pnl:,.2f}\n"
                        text += f"  Avg P&L: ${avg_pnl:,.2f}\n"
                        if profit_factor > 0:
                            text += f"  Profit Factor: {pf_emoji} {profit_factor:.2f}\n"
                        text += f"  Avg Win: 🟢 ${avg_win:,.2f}\n"
                        text += f"  Avg Loss: 🔴 ${avg_loss:,.2f}\n"
                        if avg_hold > 0:
                            text += f"  Avg Hold: {avg_hold:.1f} min\n"
                    else:
                        text += "*7-Day Summary:*\n  No completed trades in the last 7 days.\n"
                    
                    # All-time summary
                    text += "\n*All-Time Summary:*\n"
                    total_all = len(all_trades)
                    wins_all = sum(1 for t in all_trades if t.get('is_win'))
                    losses_all = total_all - wins_all
                    pnl_all = sum(float(t.get('pnl', 0) or 0) for t in all_trades)
                    wr_all = (wins_all / total_all * 100) if total_all > 0 else 0
                    
                    pnl_emoji_all = "🟢" if pnl_all >= 0 else "🔴"
                    text += f"  Trades: {total_all} ({wins_all}W / {losses_all}L)\n"
                    text += f"  Win Rate: {wr_all:.1f}%\n"
                    text += f"  Total P&L: {pnl_emoji_all} ${pnl_all:,.2f}\n"
                else:
                    text += "No performance data available yet.\n"
            else:
                text += "No performance data available yet.\n"
        except Exception as e:
            logger.debug(f"Error loading performance metrics: {e}", exc_info=True)
            text += f"Error loading metrics: {str(e)[:50]}\n"
        
        # Navigation
        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="action:performance_metrics"),
                InlineKeyboardButton("📊 Activity", callback_data="menu:activity"),
                InlineKeyboardButton("🏠 Menu", callback_data="back"),
            ],
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


    async def _handle_daily_summary(self: "TelegramCommandHandler", query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display daily trading summary."""
        state = self._read_state()
        signals = self._read_recent_signals(limit=50)
        
        text = "📊 *Daily Summary*\n\n"

        # Filter signals since 6pm ET (trading day boundary)
        today_signals = []
        if signals:
            trading_day_start = get_trading_day_start()
            for s in signals:
                ts = s.get("timestamp", "")
                if ts:
                    try:
                        signal_time = parse_utc_timestamp(ts) if isinstance(ts, str) else ts
                        if signal_time >= trading_day_start:
                            today_signals.append(s)
                    except Exception as e:
                        logger.debug(f"Non-critical: {e}", exc_info=True)
        
        if today_signals:
            # Count stats
            generated = len([s for s in today_signals if s.get("status") == "generated"])
            entered = len([s for s in today_signals if s.get("status") == "entered"])
            exited = len([s for s in today_signals if s.get("status") == "exited"])
            
            # Calculate P&L from exited signals
            total_pnl = sum(float(s.get("pnl", 0) or 0) for s in today_signals if s.get("status") == "exited")
            wins = len([s for s in today_signals if s.get("status") == "exited" and (s.get("pnl") or 0) > 0])
            losses = exited - wins
            
            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            
            text += "*Today's Activity:*\n"
            text += f"  Alerts: {len(today_signals)} total\n"
            text += f"  • Generated: {generated}\n"
            text += f"  • Active: {entered}\n"
            text += f"  • Exited: {exited}\n"
            
            if exited > 0:
                text += "\n*Today's P&L:*\n"
                text += f"  {pnl_emoji} ${total_pnl:,.2f}\n"
                text += f"  Trades: {wins}W / {losses}L\n"
        else:
            text += "No alerts generated today.\n"
        
        # Add state info
        if state:
            scans = state.get("cycle_count_session", 0) or 0
            errors = state.get("error_count", 0) or 0
            text += "\n*Session Activity:*\n"
            text += f"  Scans: {scans:,}\n"
            text += f"  Errors: {errors}\n"
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


    async def _handle_weekly_summary(self: "TelegramCommandHandler", query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display weekly trading summary."""
        state = self._read_state()
        performance = state.get("performance", {}) if state else {}
        
        text = "📉 *Weekly Summary*\n\n"
        
        if performance:
            total_signals = performance.get("total_signals", 0)
            exited_signals = performance.get("exited_signals", 0)
            wins = performance.get("wins", 0)
            losses = performance.get("losses", 0)
            win_rate = performance.get("win_rate", 0) * 100
            total_pnl = performance.get("total_pnl", 0)
            avg_pnl = performance.get("avg_pnl", 0)
            avg_hold = performance.get("avg_hold_minutes", 0)
            
            pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
            
            text += "*Alert Statistics:*\n"
            text += f"  Total Generated: {total_signals}\n"
            text += f"  Completed: {exited_signals}\n"
            
            if exited_signals > 0:
                text += "\n*Trade Performance:*\n"
                text += f"  Wins: {wins}\n"
                text += f"  Losses: {losses}\n"
                text += f"  Win Rate: {win_rate:.1f}%\n"
                text += "\n*P&L:*\n"
                text += f"  Total: {pnl_emoji} ${total_pnl:,.2f}\n"
                text += f"  Average: ${avg_pnl:,.2f}\n"
                if avg_hold > 0:
                    text += "\n*Timing:*\n"
                    text += f"  Avg Hold: {avg_hold:.1f} min\n"
            else:
                text += "\nNo completed trades this week.\n"
        else:
            text += "No performance data available.\n"
            text += "\n💡 Performance data is calculated from the last 7 days of trading activity."
        
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode="Markdown")


    async def _handle_pnl_overview(self: "TelegramCommandHandler", query: CallbackQuery, reply_markup: InlineKeyboardMarkup) -> None:
        """Display P&L overview with correct profit factor calculation."""
        text = "💰 *P&L Overview*\n\n"
        
        # Load from performance.json for accurate data
        try:
            perf_file = self.state_dir / "performance.json"
            all_trades = []
            if perf_file.exists():
                with open(perf_file, 'r') as f:
                    all_trades = json.load(f)
            
            if all_trades:
                total_pnl = sum(float(t.get('pnl', 0) or 0) for t in all_trades)
                winning_trades = [t for t in all_trades if t.get('is_win')]
                losing_trades = [t for t in all_trades if not t.get('is_win')]
                
                # Correct profit factor: gross profit / gross loss
                gross_profit = sum(float(t.get('pnl', 0) or 0) for t in winning_trades)
                gross_loss = abs(sum(float(t.get('pnl', 0) or 0) for t in losing_trades))
                profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0
                
                avg_win = (gross_profit / len(winning_trades)) if winning_trades else 0
                avg_loss = (gross_loss / len(losing_trades)) if losing_trades else 0
                
                largest_win = max((float(t.get('pnl', 0) or 0) for t in all_trades), default=0)
                largest_loss = min((float(t.get('pnl', 0) or 0) for t in all_trades), default=0)
                
                win_rate = (len(winning_trades) / len(all_trades) * 100) if all_trades else 0
                
                pnl_emoji = "🟢" if total_pnl >= 0 else "🔴"
                wr_emoji = "🟢" if win_rate >= 50 else "🟡" if win_rate >= 40 else "🔴"
                pf_emoji = "✨" if profit_factor >= 1.5 else ("📊" if profit_factor >= 1.0 else "⚠️")
                
                text += f"*Total P&L:* {pnl_emoji} ${total_pnl:,.2f}\n"
                text += f"*Trades:* {len(all_trades)} ({len(winning_trades)}W / {len(losing_trades)}L)\n"
                text += f"*Win Rate:* {wr_emoji} {win_rate:.1f}%\n\n"
                
                text += "*Averages:*\n"
                text += f"  Avg Win: 🟢 ${avg_win:,.2f}\n"
                text += f"  Avg Loss: 🔴 ${avg_loss:,.2f}\n\n"
                
                text += "*Extremes:*\n"
                text += f"  Best Trade: 🟢 ${largest_win:,.2f}\n"
                text += f"  Worst Trade: 🔴 ${abs(largest_loss):,.2f}\n\n"
                
                text += "*Risk Metrics:*\n"
                text += f"  Profit Factor: {pf_emoji} {profit_factor:.2f}\n"
                text += f"  Gross Profit: 🟢 ${gross_profit:,.2f}\n"
                text += f"  Gross Loss: 🔴 ${gross_loss:,.2f}\n"
                
                # Calculate max drawdown
                running_pnl = 0.0
                peak_pnl = 0.0
                max_drawdown = 0.0
                for t in all_trades:
                    running_pnl += float(t.get('pnl', 0) or 0)
                    if running_pnl > peak_pnl:
                        peak_pnl = running_pnl
                    drawdown = peak_pnl - running_pnl
                    if drawdown > max_drawdown:
                        max_drawdown = drawdown
                
                if max_drawdown > 0:
                    dd_emoji = "⚠️" if max_drawdown > 500 else "📉"
                    text += f"  Max Drawdown: {dd_emoji} ${max_drawdown:,.2f}\n"
            else:
                text += "No completed trades to analyze.\n"
            text += "\n💡 P&L data is calculated from your trading history."
        except Exception as e:
            logger.debug(f"Error loading P&L overview: {e}", exc_info=True)
            text += f"Error loading data: {str(e)[:50]}\n"
        
        # Navigation
        keyboard = [
            [
                InlineKeyboardButton("🔄 Refresh", callback_data="action:pnl_overview"),
                InlineKeyboardButton("📊 Activity", callback_data="menu:activity"),
                InlineKeyboardButton("🏠 Menu", callback_data="back"),
            ],
        ]
        
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")


    async def _handle_export_performance(self: "TelegramCommandHandler", query: CallbackQuery) -> None:
        """Export performance report."""
        try:
            metrics = self._read_latest_metrics()
            state = self._read_state()
            
            if not metrics and not state:
                keyboard = [self._nav_back_row()]
                await query.edit_message_text(
                    "❌ No performance data available to export.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
                return
            
            # Build a text summary report
            lines = [
                "📋 *Performance Report*",
                f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
                "",
            ]
            
            if metrics:
                lines.extend([
                    "*Trading Metrics:*",
                    f"• Total Trades: {metrics.get('exited_signals', 0)}",
                    f"• Win Rate: {metrics.get('win_rate', 0.0):.1%}",
                    f"• Total P&L: ${metrics.get('total_pnl', 0.0):,.2f}",
                    f"• Average P&L: ${metrics.get('avg_pnl', 0.0):,.2f}",
                    f"• Max Drawdown: ${metrics.get('max_drawdown', 0.0):,.2f}",
                    "",
                ])
            
            if state:
                lines.extend([
                    "*Current Session:*",
                    f"• Daily P&L: ${state.get('daily_pnl', 0.0):,.2f}",
                    f"• Daily Trades: {state.get('daily_trades', 0)}",
                    f"• Open Positions: {state.get('execution', {}).get('positions', 0)}",
                    "",
                ])
            
            keyboard = [
                [InlineKeyboardButton("💎 Performance", callback_data="menu:performance")],
                self._nav_back_row(),
            ]
            await query.edit_message_text(
                "\n".join(lines),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
        except Exception as e:
            logger.error(f"Export performance error: {e}", exc_info=True)
            keyboard = [self._nav_back_row()]
            await query.edit_message_text(
                f"❌ Error exporting performance: {e}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )



    # Note: The following methods should be defined in the main class or other mixins:
    # - _read_state() -> Optional[dict]
    # - _read_latest_metrics() -> Optional[dict]
    # - _read_recent_signals(limit: int) -> list
    # - _safe_edit_or_send(query, text, reply_markup, parse_mode)
    # - _nav_back_row() -> list
    # - state_dir: Path
