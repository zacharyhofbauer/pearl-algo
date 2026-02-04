"""
Pearl Narrator - Converts trading events to natural language

Provides prompts and templates for narrating trading activity.
Enhanced with rich context injection for meaningful explanations.
"""

from typing import Dict, Any, Optional, List
from datetime import datetime


class PearlNarrator:
    """Converts trading events and states into natural language."""

    def __init__(self):
        self.personality_traits = [
            "concise but informative",
            "confident but not arrogant",
            "focused on actionable information",
            "uses trading terminology naturally",
        ]

        # Session name mappings for time-of-day context
        self.session_names = {
            "pre_market": "Pre-market session",
            "morning_open": "Morning open",
            "mid_morning": "Mid-morning",
            "lunch": "Lunch hour",
            "afternoon": "Afternoon session",
            "power_hour": "Power hour",
            "after_hours": "After-hours"
        }

    def _variant_seed(self, event_type: str, ctx: Dict[str, Any]) -> int:
        """Stable hash seed for deterministic template variation."""
        try:
            import hashlib
            import json

            seed_obj = {"event_type": str(event_type or "")}
            # Include only a few stable, low-entropy fields (avoid huge blobs).
            for k in (
                "direction",
                "entry_price",
                "pnl",
                "exit_reason",
                "reason",
                "cooldown_seconds",
                "blocked_direction",
                "signal_type",
                "total_today",
            ):
                if k in ctx:
                    seed_obj[k] = ctx.get(k)

            seed = json.dumps(seed_obj, sort_keys=True, default=str).encode("utf-8")
            return int(hashlib.sha256(seed).hexdigest()[:8], 16)
        except Exception:
            return 0

    def _get_session_name(self, state: Dict) -> str:
        """Get human-readable session name from state."""
        session_ctx = state.get("session_context", {})
        session_key = session_ctx.get("current_session", "")
        return self.session_names.get(session_key, session_key.replace("_", " ").title() if session_key else "market")

    def _get_pressure_description(self, state: Dict) -> str:
        """Get order flow pressure description."""
        pressure = state.get("buy_sell_pressure", {})
        bias = pressure.get("bias", "neutral")
        intensity = pressure.get("intensity", 0)

        if bias == "neutral" or intensity < 0.3:
            return "balanced flow"
        elif bias == "buyer":
            return "buyer pressure" if intensity < 0.6 else "strong buyer pressure"
        else:
            return "seller pressure" if intensity < 0.6 else "strong seller pressure"

    def _get_regime_context(self, state: Dict) -> str:
        """Get market regime context."""
        regime_info = state.get("market_regime", {})
        regime = regime_info.get("regime", "unknown")
        confidence = regime_info.get("confidence", 0)

        regime_map = {
            "trending_up": "uptrending",
            "trending_down": "downtrending",
            "ranging": "ranging",
            "volatile": "volatile",
            "unknown": "uncertain"
        }

        regime_str = regime_map.get(regime, regime.replace("_", " "))
        if confidence > 0.7:
            return f"{regime_str}"
        return f"likely {regime_str}"

    def build_narration_prompt(
        self,
        event_type: str,
        context: Dict[str, Any],
        current_state: Dict[str, Any],
    ) -> str:
        """Build a prompt for the LLM to generate a narration."""

        prompts = {
            "trade_entered": self._trade_entered_prompt,
            "trade_exited": self._trade_exited_prompt,
            "signal_generated": self._signal_generated_prompt,
            "signal_rejected": self._signal_rejected_prompt,
            "circuit_breaker_triggered": self._circuit_breaker_prompt,
            "direction_blocked": self._direction_blocked_prompt,
            "regime_changed": self._regime_changed_prompt,
            "session_started": self._session_started_prompt,
            "session_ended": self._session_ended_prompt,
        }

        builder = prompts.get(event_type, self._generic_prompt)
        return builder(context, current_state)

    def _trade_entered_prompt(self, ctx: Dict, state: Dict) -> str:
        direction = ctx.get("direction", "unknown")
        entry_price = ctx.get("entry_price", 0)
        ml_prob = state.get("last_signal_decision", {}).get("ml_probability", 0)
        regime = self._get_regime_context(state)
        pressure = self._get_pressure_description(state)
        session = self._get_session_name(state)

        # Get recent trade correlation context
        recent_exits = state.get("recent_exits", [])
        recent_same_dir = [t for t in recent_exits[:5] if t.get("direction") == direction]
        same_dir_wins = sum(1 for t in recent_same_dir if t.get("pnl", 0) > 0)
        correlation_note = ""
        if len(recent_same_dir) >= 2:
            win_rate = same_dir_wins / len(recent_same_dir)
            if win_rate > 0.6:
                correlation_note = f"Recent {direction.upper()} trades have been winning ({same_dir_wins}/{len(recent_same_dir)})."
            elif win_rate < 0.4:
                correlation_note = f"Recent {direction.upper()} trades have struggled ({same_dir_wins}/{len(recent_same_dir)} wins)."

        return f"""Narrate this trade entry in EXACTLY 1 sentence (max 25 words):
{direction.upper()} at {entry_price}, {regime} market, {pressure}, ML {ml_prob * 100:.0f}%.

Output format: "Entered [DIRECTION] at [PRICE] — [one key observation]."
Example: "Entered LONG at 25530 — trending market with 72% ML confidence."
DO NOT exceed 1 sentence."""

    def _trade_exited_prompt(self, ctx: Dict, state: Dict) -> str:
        pnl = ctx.get("pnl", 0)
        direction = ctx.get("direction", "unknown")
        reason = ctx.get("exit_reason", "unknown")
        daily_pnl = state.get("daily_pnl", 0)
        regime = self._get_regime_context(state)
        pressure = self._get_pressure_description(state)

        # Calculate consecutive streak context
        consecutive_wins = state.get("consecutive_wins", 0)
        consecutive_losses = state.get("consecutive_losses", 0)
        streak_note = ""
        if pnl > 0 and consecutive_wins >= 2:
            streak_note = f"That's {consecutive_wins} wins in a row!"
        elif pnl < 0 and consecutive_losses >= 2:
            streak_note = f"That's {consecutive_losses} losses in a row - might be worth a breather."

        # Win rate context
        daily_trades = state.get("daily_trades", 0)
        daily_wins = state.get("daily_wins", 0)
        win_rate_pct = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0

        return f"""Narrate this trade exit in EXACTLY 1 sentence (max 25 words):
{direction.upper()} closed: ${pnl:+.2f} ({reason}). Daily P&L: ${daily_pnl:+.2f}.
{f'{streak_note}' if streak_note else ''}

Output format: "Closed [DIRECTION]: $[P&L] ([reason]) — [brief context]."
Example: "Closed LONG: +$45.50 (take profit) — day now at +$150."
DO NOT exceed 1 sentence. Must mention the P&L amount."""

    def _signal_generated_prompt(self, ctx: Dict, state: Dict) -> str:
        signal_type = ctx.get("signal_type", "unknown")
        ml_prob = ctx.get("ml_probability", 0)
        regime = self._get_regime_context(state)
        pressure = self._get_pressure_description(state)
        session = self._get_session_name(state)

        return f"""Briefly note this signal generation (1 sentence):
- Signal Type: {signal_type}
- ML Probability: {ml_prob * 100:.0f}%
- Market: {regime} with {pressure}
- Session: {session}

One sentence noting the signal and its context.
Example: "Spotted a LONG signal with 68% ML confidence - buyer pressure building in this ranging market."
Keep it brief."""

    def _signal_rejected_prompt(self, ctx: Dict, state: Dict) -> str:
        reason = ctx.get("reason", "unknown")
        total = ctx.get("total_today", 0)
        regime = self._get_regime_context(state)

        # Get ML filter stats if ML rejection
        ml_stats = ""
        if "ml" in reason.lower():
            ml_filter = state.get("ai_status", {}).get("ml_filter", {})
            passed = ml_filter.get("passed", 0)
            skipped = ml_filter.get("skipped", 0)
            if passed + skipped > 0:
                ml_stats = f"ML has passed {passed} and blocked {skipped} signals today."

        # Get direction gating stats
        gating_stats = ""
        if "direction" in reason.lower() or "gating" in reason.lower():
            gating = state.get("ai_status", {}).get("direction_gating", {})
            blocked_dir = gating.get("blocked_direction", "")
            if blocked_dir:
                gating_stats = f"Currently blocking {blocked_dir.upper()} due to {regime} conditions."

        return f"""Explain this signal rejection in EXACTLY 1 sentence (max 20 words):
Reason: {reason.replace('_', ' ')}. Rejections today: {total}.

Output: "Skipped [signal] — [specific reason]."
Example: "Skipped LONG signal — ML confidence 28%, below threshold."
DO NOT exceed 1 sentence."""

    def _circuit_breaker_prompt(self, ctx: Dict, state: Dict) -> str:
        reason = ctx.get("reason", "protective stop")
        cooldown = ctx.get("cooldown_seconds", 0)

        return f"""Circuit breaker alert in EXACTLY 1 sentence (max 20 words):
Reason: {reason}. Cooldown: {cooldown // 60} minutes.

Output: "Circuit breaker triggered — [reason]. Pausing [X] minutes."
Example: "Circuit breaker triggered — daily loss limit. Pausing 30 minutes."
DO NOT exceed 1 sentence."""

    def _direction_blocked_prompt(self, ctx: Dict, state: Dict) -> str:
        blocked = ctx.get("blocked_direction", "unknown")
        regime = state.get("market_regime", {}).get("regime", "unknown")

        return f"""Note direction restriction:
- Blocked Direction: {blocked}
- Market Regime: {regime}

One sentence about why this direction is restricted."""

    def _regime_changed_prompt(self, ctx: Dict, state: Dict) -> str:
        old_regime = ctx.get("old_regime", "unknown")
        new_regime = ctx.get("new_regime", "unknown")
        confidence = ctx.get("confidence", 0)

        return f"""Note market regime change:
- Previous: {old_regime}
- Current: {new_regime}
- Confidence: {confidence * 100:.0f}%

One sentence about what this means for trading."""

    def _session_started_prompt(self, ctx: Dict, state: Dict) -> str:
        session = ctx.get("session", "trading")
        return f"Briefly announce the start of the {session} session."

    def _session_ended_prompt(self, ctx: Dict, state: Dict) -> str:
        pnl = state.get("daily_pnl", 0)
        trades = state.get("daily_trades", 0)
        wins = state.get("daily_wins", 0)

        return f"""Summarize session end:
- Session P&L: ${pnl:+.2f}
- Trades: {trades} ({wins} wins)

Two sentences summarizing the session."""

    def _generic_prompt(self, ctx: Dict, state: Dict) -> str:
        return f"Briefly describe this trading event: {ctx}"

    def template_narration(self, event_type: str, context: Dict[str, Any], state: Optional[Dict[str, Any]] = None) -> str:
        """
        Fallback template-based narration when LLM is unavailable.
        Returns human-readable text without AI generation.
        Enhanced with context when state is available.
        """
        state = state or {}

        templates = {
            "trade_entered": lambda ctx: self._template_trade_entered(ctx, state),
            "trade_exited": lambda ctx: self._template_trade_exited(ctx, state),
            "signal_rejected": lambda ctx: self._template_signal_rejected(ctx, state),
            "circuit_breaker_triggered": self._template_circuit_breaker,
            "direction_blocked": self._template_direction_blocked,
        }

        template_fn = templates.get(event_type, self._template_generic)
        return template_fn(context)

    def build_narration_details(
        self,
        event_type: str,
        context: Dict[str, Any],
        current_state: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build a richer, expandable details payload for UI (dropdown/expanded view).

        The narration headline is optimized for glanceability (often 1 sentence),
        while this details payload preserves additional context and key fields.

        Returns a JSON-serializable dict with:
        - lines: ordered list of human-readable lines
        - text: newline-joined lines for simple renderers
        - fields: stable key/value fields for structured UIs
        """
        ctx = context or {}
        state = current_state or {}

        title_map = {
            "trade_entered": "Trade entered",
            "trade_exited": "Trade exited",
            "signal_generated": "Signal generated",
            "signal_rejected": "Signal rejected",
            "circuit_breaker_triggered": "Circuit breaker",
            "direction_blocked": "Direction restricted",
        }
        title = title_map.get(event_type, str(event_type or "").replace("_", " ").title() or "Update")

        def _section(name: str) -> Dict[str, Any]:
            return {"title": name, "lines": [], "fields": {}, "kv": []}

        def _fmt_money(value: Any, *, signed: bool = False) -> str:
            try:
                v = float(value)
            except Exception:
                return str(value)
            if signed:
                sign = "+" if v > 0 else "-" if v < 0 else ""
                return f"{sign}${abs(v):,.2f}"
            return f"${v:,.2f}"

        def _fmt_pct(value: Any) -> str:
            try:
                v = float(value)
            except Exception:
                return str(value)
            # Accept either 0..1 or 0..100
            if v <= 1.0:
                return f"{v * 100:.0f}%"
            return f"{v:.0f}%"

        def _add(section: Dict[str, Any], label: str, raw_value: Any, *, formatted: Optional[str] = None, key: Optional[str] = None) -> None:
            if raw_value is None:
                return
            if isinstance(raw_value, str) and raw_value.strip() == "":
                return
            k = key or label.lower().replace(" ", "_")
            display = formatted if formatted is not None else str(raw_value)
            section["fields"][k] = raw_value
            section["kv"].append({"key": k, "label": label, "value": display, "raw": raw_value})
            section["lines"].append(f"{label}: {display}")

        sec_trade = _section("Trade")
        sec_today = _section("Today")
        sec_market = _section("Market")
        sec_model = _section("Model")
        sec_system = _section("System")

        # -------------------------------------------------------------
        # Market context (shared)
        # -------------------------------------------------------------
        regime_info = state.get("market_regime", {}) if isinstance(state, dict) else {}
        if isinstance(regime_info, dict):
            regime_raw = regime_info.get("regime")
            regime_conf = regime_info.get("confidence")
            allowed_direction = regime_info.get("allowed_direction")
            volatility = regime_info.get("volatility")

            if regime_raw:
                try:
                    regime_human = self._get_regime_context(state) if isinstance(state, dict) else str(regime_raw)
                except Exception:
                    regime_human = str(regime_raw)
                if regime_conf is not None:
                    _add(
                        sec_market,
                        "Regime",
                        str(regime_raw),
                        formatted=f"{regime_human} ({_fmt_pct(regime_conf)})",
                        key="market_regime",
                    )
                else:
                    _add(sec_market, "Regime", str(regime_raw), formatted=str(regime_human), key="market_regime")

            if allowed_direction:
                _add(
                    sec_market,
                    "Allowed direction",
                    str(allowed_direction),
                    formatted=str(allowed_direction).upper(),
                    key="allowed_direction",
                )

            if volatility:
                _add(sec_market, "Volatility", str(volatility), formatted=str(volatility).replace("_", " "), key="volatility")

        try:
            flow = self._get_pressure_description(state) if isinstance(state, dict) else ""
        except Exception:
            flow = ""
        if flow:
            _add(sec_market, "Flow", flow, key="order_flow")

        try:
            session = self._get_session_name(state) if isinstance(state, dict) else ""
        except Exception:
            session = ""
        if session:
            _add(sec_market, "Session", session, key="session")

        # -------------------------------------------------------------
        # Today / session context (shared)
        # -------------------------------------------------------------
        if isinstance(state, dict):
            daily_pnl = state.get("daily_pnl")
            daily_trades = state.get("daily_trades")
            daily_wins = state.get("daily_wins")
            daily_losses = state.get("daily_losses")
            active_positions = state.get("active_trades_count")

            if daily_pnl is not None:
                _add(sec_today, "Day P&L", daily_pnl, formatted=_fmt_money(daily_pnl, signed=True), key="daily_pnl")

            # Trades + W/L + win rate
            if daily_trades is not None:
                try:
                    t = int(daily_trades)
                except Exception:
                    t = None
                try:
                    w = int(daily_wins) if daily_wins is not None else None
                except Exception:
                    w = None
                try:
                    l = int(daily_losses) if daily_losses is not None else None
                except Exception:
                    l = None

                win_rate = None
                if t and w is not None:
                    try:
                        win_rate = (w / max(t, 1)) * 100
                    except Exception:
                        win_rate = None

                parts = []
                if w is not None:
                    parts.append(f"{w}W")
                if l is not None:
                    parts.append(f"{l}L")
                wl = f" ({' / '.join(parts)})" if parts else ""
                wr = f"; {_fmt_pct(win_rate / 100)}" if win_rate is not None else ""

                trades_display = f"{t}{wl}{wr}" if t is not None else str(daily_trades)
                _add(sec_today, "Trades", daily_trades, formatted=trades_display, key="daily_trades")
                if win_rate is not None:
                    _add(sec_today, "Win rate", win_rate, formatted=_fmt_pct(win_rate / 100), key="win_rate")

            if active_positions is not None:
                _add(sec_today, "Active positions", active_positions, formatted=str(active_positions), key="active_positions")

            cw = state.get("consecutive_wins")
            cl = state.get("consecutive_losses")
            try:
                cw_i = int(cw) if cw is not None else 0
            except Exception:
                cw_i = 0
            try:
                cl_i = int(cl) if cl is not None else 0
            except Exception:
                cl_i = 0
            if cw_i >= 2:
                _add(sec_today, "Streak", cw_i, formatted=f"{cw_i} wins", key="consecutive_wins")
            elif cl_i >= 2:
                _add(sec_today, "Streak", cl_i, formatted=f"{cl_i} losses", key="consecutive_losses")

        # -------------------------------------------------------------
        # Per-event details
        # -------------------------------------------------------------
        if event_type == "trade_entered":
            direction = ctx.get("direction")
            entry_price = ctx.get("entry_price")
            count = ctx.get("count")
            if direction:
                _add(sec_trade, "Direction", str(direction).upper(), key="direction")
            if entry_price is not None:
                _add(sec_trade, "Entry", entry_price, formatted=_fmt_money(entry_price, signed=False), key="entry_price")
            if count is not None:
                _add(sec_trade, "Size", count, formatted=str(count), key="count")

            symbol = ctx.get("symbol") or ctx.get("instrument")
            if symbol:
                _add(sec_trade, "Symbol", str(symbol), formatted=str(symbol).upper(), key="symbol")

            signal_id = ctx.get("signal_id") or ctx.get("id")
            if signal_id:
                _add(sec_trade, "Signal ID", str(signal_id), formatted=str(signal_id), key="signal_id")

            ml_prob = ctx.get("ml_probability")
            if ml_prob is None and isinstance(state, dict):
                ml_prob = (state.get("last_signal_decision") or {}).get("ml_probability")
            if ml_prob is not None and float(ml_prob or 0) > 0:
                _add(sec_model, "ML confidence", ml_prob, formatted=_fmt_pct(ml_prob), key="ml_probability")

            # Recent same-direction performance (compact, optional)
            if direction and isinstance(state, dict):
                recent_exits = state.get("recent_exits", [])
                if isinstance(recent_exits, list) and recent_exits:
                    dir_l = str(direction).lower()
                    sample = []
                    for t in recent_exits:
                        if not isinstance(t, dict):
                            continue
                        if str(t.get("direction", "")).lower() != dir_l:
                            continue
                        sample.append(t)
                        if len(sample) >= 5:
                            break
                    if len(sample) >= 2:
                        wins = 0
                        pnls: List[float] = []
                        for t in sample:
                            try:
                                p = float(t.get("pnl", 0) or 0)
                            except Exception:
                                p = 0.0
                            pnls.append(p)
                            if p > 0:
                                wins += 1
                        total = len(sample)
                        avg = sum(pnls) / max(total, 1)
                        payload = {"direction": dir_l, "wins": wins, "total": total, "avg_pnl": avg}
                        _add(
                            sec_trade,
                            f"Recent {str(direction).upper()} (last {total})",
                            payload,
                            formatted=f"{wins}/{total} wins; avg {_fmt_money(avg, signed=True)}",
                            key="recent_same_direction",
                        )

        elif event_type == "trade_exited":
            direction = ctx.get("direction")
            pnl = ctx.get("pnl")
            reason = ctx.get("exit_reason")
            if direction:
                _add(sec_trade, "Direction", str(direction).upper(), key="direction")
            if pnl is not None:
                _add(sec_trade, "Trade P&L", pnl, formatted=_fmt_money(pnl, signed=True), key="pnl")
            if reason:
                _add(sec_trade, "Exit reason", str(reason).replace("_", " "), key="exit_reason")

            # Outcome line (WIN/LOSS) can be nice in expanded view
            try:
                pnl_f = float(pnl) if pnl is not None else 0.0
            except Exception:
                pnl_f = 0.0
            outcome = "WIN" if pnl_f > 0 else "LOSS" if pnl_f < 0 else "FLAT"
            _add(sec_trade, "Outcome", outcome, formatted=outcome, key="outcome")

        elif event_type == "signal_rejected":
            reason = ctx.get("reason")
            total = ctx.get("total_today")
            if reason:
                _add(sec_system, "Reason", str(reason).replace("_", " "), key="reason")
            if total is not None:
                _add(sec_system, "Rejections today", total, formatted=str(total), key="total_today")

            ai_status = state.get("ai_status", {}) if isinstance(state, dict) else {}
            ml_filter = ai_status.get("ml_filter", {}) if isinstance(ai_status, dict) else {}
            if isinstance(ml_filter, dict) and (ml_filter.get("passed") is not None or ml_filter.get("skipped") is not None):
                passed = int(ml_filter.get("passed") or 0)
                skipped = int(ml_filter.get("skipped") or 0)
                _add(
                    sec_model,
                    "ML filter",
                    {"passed": passed, "blocked": skipped},
                    formatted=f"passed {passed}, blocked {skipped}",
                    key="ml_filter",
                )

            gating = ai_status.get("direction_gating", {}) if isinstance(ai_status, dict) else {}
            blocked_dir = gating.get("blocked_direction") if isinstance(gating, dict) else None
            if blocked_dir:
                _add(sec_system, "Direction gating", str(blocked_dir).upper(), key="blocked_direction")

        elif event_type == "circuit_breaker_triggered":
            reason = ctx.get("reason")
            cooldown = ctx.get("cooldown_seconds")
            if reason:
                _add(sec_system, "Reason", str(reason).replace("_", " "), key="reason")
            if cooldown is not None:
                try:
                    minutes = int(float(cooldown) // 60)
                except Exception:
                    minutes = None
                if minutes is not None:
                    _add(sec_system, "Cooldown", cooldown, formatted=f"{minutes} min", key="cooldown_seconds")
                else:
                    _add(sec_system, "Cooldown", cooldown, formatted=str(cooldown), key="cooldown_seconds")

            if isinstance(state, dict):
                cb = state.get("circuit_breaker", {})
                if isinstance(cb, dict):
                    blocks = cb.get("blocks")
                    if blocks is not None:
                        _add(sec_system, "Blocks", blocks, formatted=str(blocks), key="cb_blocks")
                    trip_reason = cb.get("trip_reason")
                    if trip_reason:
                        _add(sec_system, "Trip reason", str(trip_reason), formatted=str(trip_reason).replace("_", " "), key="trip_reason")

        elif event_type == "direction_blocked":
            blocked = ctx.get("blocked_direction") or ctx.get("direction")
            if blocked:
                _add(sec_system, "Blocked", str(blocked).upper(), key="blocked_direction")

        elif event_type == "signal_generated":
            signal_type = ctx.get("signal_type")
            ml_prob = ctx.get("ml_probability")
            if signal_type:
                _add(sec_trade, "Signal", str(signal_type).replace("_", " ").title(), key="signal_type")
            if ml_prob is not None and float(ml_prob or 0) > 0:
                _add(sec_model, "ML confidence", ml_prob, formatted=_fmt_pct(ml_prob), key="ml_probability")

        else:
            # Generic: include a few safe context keys (avoid dumping huge blobs).
            for k in sorted(ctx.keys()):
                if k in {"raw", "payload", "state", "details"}:
                    continue
                if len(sec_system["lines"]) >= 8:
                    break
                v = ctx.get(k)
                if v is None:
                    continue
                if isinstance(v, (dict, list)) and len(str(v)) > 200:
                    continue
                _add(sec_system, str(k).replace("_", " ").title(), v, formatted=str(v), key=f"ctx_{k}")

        # -------------------------------------------------------------
        # Assemble payload
        # -------------------------------------------------------------
        sections = [s for s in (sec_trade, sec_today, sec_market, sec_model, sec_system) if s["lines"]]
        lines: List[str] = []
        kv: List[Dict[str, Any]] = []
        fields: Dict[str, Any] = {}

        for s in sections:
            lines.extend(s["lines"])
            kv.extend(s["kv"])
            fields.update(s["fields"])

        max_lines = 12
        truncated = False
        if len(lines) > max_lines:
            truncated = True
            lines = lines[:max_lines] + ["…"]
            kv = kv[:max_lines]

        return {
            "title": title,
            "lines": lines,
            "text": "\n".join(lines),
            "fields": fields,
            "kv": kv,
            "sections": sections,
            "truncated": truncated,
        }

    def _template_trade_entered(self, ctx: Dict, state: Dict = None) -> str:
        state = state or {}
        direction = ctx.get("direction", "").upper()
        entry_price = ctx.get("entry_price", 0)
        count = ctx.get("count", 1)

        # Add context if available
        regime = self._get_regime_context(state) if state else "market"
        pressure = self._get_pressure_description(state) if state else ""
        ml_prob = state.get("last_signal_decision", {}).get("ml_probability", 0) if state else 0

        headline = f"Entered {direction} at {entry_price}"
        extras: List[str] = []
        if regime and regime != "uncertain":
            extras.append(f"{regime} market")
        if pressure and pressure != "balanced flow":
            extras.append(str(pressure))
        if ml_prob and ml_prob > 0:
            extras.append(f"ML {ml_prob * 100:.0f}%")
        # Keep headline one sentence; keep extras compact.
        if extras:
            variant = self._variant_seed("trade_entered", ctx) % 2
            picked = extras[:2]
            if variant == 0:
                return f"{headline} — {', '.join(picked)}."
            # Alternate punctuation/ordering for variety (still one sentence).
            picked = sorted(picked, key=lambda s: 0 if str(s).startswith("ML ") else 1)
            return f"{headline}; " + "; ".join(picked) + "."
        return f"{headline}."

    def _template_trade_exited(self, ctx: Dict, state: Dict = None) -> str:
        state = state or {}
        pnl = ctx.get("pnl", 0)
        direction = ctx.get("direction", "").upper()
        reason = ctx.get("exit_reason", "").replace("_", " ")
        try:
            pnl_f = float(pnl)
        except Exception:
            pnl_f = 0.0
        sign = "+" if pnl_f >= 0 else "-"

        daily_pnl = state.get("daily_pnl", 0) if state else 0
        variant = self._variant_seed("trade_exited", ctx) % 2
        verb = "Closed" if variant == 0 else "Exited"
        sep = "; " if variant == 0 else " — "
        result = f"{verb} {direction}: {sign}${abs(pnl_f):.2f}"
        if reason:
            result += f" ({reason})"
        if state:
            # One sentence headline; keep day context after semicolon.
            try:
                daily_f = float(daily_pnl)
            except Exception:
                daily_f = 0.0
            day_sign = "+" if daily_f > 0 else "-" if daily_f < 0 else ""
            result += f"{sep}day {day_sign}${abs(daily_f):.2f}."
        return result

    def _template_signal_rejected(self, ctx: Dict, state: Dict = None) -> str:
        state = state or {}
        reason = ctx.get("reason", "").replace("_", " ").title()
        total = ctx.get("total_today", 0)

        result = f"Signal blocked by {reason}"
        if total > 1:
            result += f" ({total} rejections today)"
        return result + "."

    def _template_circuit_breaker(self, ctx: Dict) -> str:
        cooldown = ctx.get("cooldown_seconds", 0)
        try:
            minutes = int(float(cooldown) // 60)
        except Exception:
            minutes = 0
        variant = self._variant_seed("circuit_breaker_triggered", ctx) % 2
        if variant == 0:
            return f"Circuit breaker activated — pausing {minutes} minutes."
        return f"Pausing {minutes} minutes — circuit breaker activated."

    def _template_direction_blocked(self, ctx: Dict) -> str:
        direction = ctx.get("blocked_direction", "").upper()
        return f"{direction} direction currently restricted by market regime."

    def _template_generic(self, ctx: Dict) -> str:
        return f"Trading event: {ctx.get('event_type', 'update')}"


class NarrationStyle:
    """Different narration styles for different contexts."""

    CONCISE = "concise"  # Short, to the point
    DETAILED = "detailed"  # More explanation
    COACHING = "coaching"  # Educational, teaching
    ALERT = "alert"  # Urgent, attention-grabbing

    @staticmethod
    def get_style_prompt(style: str) -> str:
        prompts = {
            "concise": "Be brief - one sentence max. Just the key facts.",
            "detailed": "Provide context and explanation in 2-3 sentences.",
            "coaching": "Explain the reasoning and teach the concept in 3-4 sentences.",
            "alert": "This is important - be clear and direct about the urgency.",
        }
        return prompts.get(style, prompts["concise"])
