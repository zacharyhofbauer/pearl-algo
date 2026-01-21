#!/usr/bin/env python3
"""
Doctor CLI - 24h rollup for local/ops use.

Mirrors the Telegram `/doctor` view:
- signal event counts (generated/entered/exited/expired)
- trade exit summary (WR, P&L, avg hold)
- cycle diagnostics aggregates (rejections, stop caps, etc.)
- stop distance + position size distributions (from generated signals)

Usage:
  python scripts/monitoring/doctor_cli.py
  python scripts/monitoring/doctor_cli.py --hours 6
  python scripts/monitoring/doctor_cli.py --json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
import math


def _fmt_pct(x: float) -> str:
    try:
        return f"{(float(x) * 100):.0f}%"
    except Exception:
        return "0%"


def build_doctor_rollup(db, *, hours: float = 24.0) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=float(hours))).isoformat()

    event_counts = db.get_signal_event_counts(from_time=cutoff)
    diag = db.get_cycle_diagnostics_aggregate(from_time=cutoff)
    quiet_top = db.get_quiet_reason_counts(from_time=cutoff, limit=5)
    trade_summary = db.get_trade_summary(from_exit_time=cutoff)

    gen_events = db.get_signal_events(status="generated", from_time=cutoff, limit=5000)

    stop_bins = [
        ("<5", 0.0, 5.0),
        ("5-10", 5.0, 10.0),
        ("10-15", 10.0, 15.0),
        ("15-20", 15.0, 20.0),
        ("20-25", 20.0, 25.0),
        (">25", 25.0, 10_000.0),
    ]
    size_bins = [
        ("1", 1.0, 1.0),
        ("2-3", 2.0, 3.0),
        ("4-5", 4.0, 5.0),
        ("6-8", 6.0, 8.0),
        ("9-12", 9.0, 12.0),
        ("13-15", 13.0, 15.0),
        (">15", 15.0, 10_000.0),
    ]

    stop_counts = {k: 0 for (k, _, _) in stop_bins}
    size_counts = {k: 0 for (k, _, _) in size_bins}
    stop_samples: List[float] = []
    size_samples: List[float] = []
    ml_probs: List[float] = []
    ml_fallbacks = 0

    for ev in gen_events:
        payload = ev.get("payload", {}) or {}
        sig = payload.get("signal", {}) if isinstance(payload, dict) else {}
        if not isinstance(sig, dict):
            continue

        # stop distance
        try:
            entry = float(sig.get("entry_price", 0.0) or 0.0)
            stop = float(sig.get("stop_loss", 0.0) or 0.0)
        except Exception:
            entry, stop = 0.0, 0.0

        if entry > 0 and stop > 0:
            dist = abs(entry - stop)
            stop_samples.append(dist)
            for label, lo, hi in stop_bins:
                if lo <= dist < hi:
                    stop_counts[label] += 1
                    break

        # size
        try:
            size = float(sig.get("position_size", 0.0) or 0.0)
        except Exception:
            size = 0.0
        if size > 0:
            size_samples.append(size)
            for label, lo, hi in size_bins:
                if label == "1":
                    if abs(size - 1.0) < 1e-9:
                        size_counts[label] += 1
                        break
                else:
                    if lo <= size <= hi:
                        size_counts[label] += 1
                        break

        # ML prediction (if attached to signal)
        ml_pred = sig.get("_ml_prediction")
        if isinstance(ml_pred, dict):
            try:
                ml_probs.append(float(ml_pred.get("win_probability", 0.0)))
            except Exception:
                pass
            if bool(ml_pred.get("fallback_used", False)):
                ml_fallbacks += 1

    stop_avg = None
    stop_med = None
    size_avg = None
    size_med = None
    try:
        import numpy as np

        if stop_samples:
            stop_avg = float(np.mean(stop_samples))
            stop_med = float(np.median(stop_samples))
        if size_samples:
            size_avg = float(np.mean(size_samples))
            size_med = float(np.median(size_samples))
    except Exception:
        pass

    # -----------------------------------------------------------------------------
    # Brain / learning rollup (best-effort)
    # -----------------------------------------------------------------------------
    brain: Dict[str, Any] = {}
    try:
        # Derive state_dir from DB path (production default: data/agent_state/<MARKET>/)
        state_dir = getattr(db, "db_path", None)
        state_dir = Path(state_dir).parent if state_dir else Path("data/agent_state/NQ")

        from pearlalgo.config.config_loader import load_service_config

        cfg = load_service_config(validate=False) or {}
        learning_cfg = cfg.get("learning", {}) or {}
        ml_cfg = cfg.get("ml_filter", {}) or {}

        # Bandit policy (global)
        try:
            from pearlalgo.learning.bandit_policy import BanditPolicy, BanditConfig

            bandit_config = BanditConfig.from_dict(learning_cfg if isinstance(learning_cfg, dict) else {})
            bandit = BanditPolicy(config=bandit_config, state_dir=state_dir)
            st = bandit.get_status() or {}

            stats_list = list(getattr(bandit.state, "signal_types", {}).values())
            total_outcomes = sum(int(getattr(s, "sample_count", 0) or 0) for s in stats_list)

            weighted_sum = 0.0
            weighted_denom = 0
            stdevs: List[float] = []
            for s in stats_list:
                n = int(getattr(s, "sample_count", 0) or 0)
                w = max(1, n)
                weighted_denom += w
                try:
                    weighted_sum += float(getattr(s, "expected_win_rate", 0.5) or 0.5) * w
                except Exception:
                    weighted_sum += 0.5 * w

                try:
                    a = float(getattr(s, "alpha", 0.0) or 0.0)
                    b = float(getattr(s, "beta", 0.0) or 0.0)
                    if a > 0 and b > 0:
                        var = (a * b) / (((a + b) ** 2) * (a + b + 1))
                        if var >= 0:
                            stdevs.append(math.sqrt(var))
                except Exception:
                    pass

            avg_expected = (weighted_sum / max(1, weighted_denom)) if weighted_denom else 0.5
            avg_unc = (sum(stdevs) / len(stdevs)) if stdevs else None

            brain["bandit"] = {
                "enabled": bool(st.get("enabled", True)),
                "mode": str(st.get("mode", "")),
                "decision_threshold": float(st.get("decision_threshold", bandit_config.decision_threshold) or bandit_config.decision_threshold),
                "explore_rate": float(st.get("explore_rate", bandit_config.explore_rate) or bandit_config.explore_rate),
                "total_decisions": int(st.get("total_decisions", 0) or 0),
                "execute_rate": float(st.get("execute_rate", 0.0) or 0.0),
                "total_outcomes": int(total_outcomes),
                "avg_expected_win_rate": float(avg_expected),
                "avg_uncertainty": float(avg_unc) if avg_unc is not None else None,
            }
        except Exception:
            pass

        # Contextual policy (optional)
        try:
            contextual_cfg = learning_cfg.get("contextual", {}) if isinstance(learning_cfg, dict) else {}
            if isinstance(contextual_cfg, dict) and bool(contextual_cfg.get("enabled", False)):
                from pearlalgo.learning.contextual_bandit import ContextualBanditPolicy, ContextualBanditConfig

                ctx_config = ContextualBanditConfig.from_dict(contextual_cfg)
                ctx_policy = ContextualBanditPolicy(config=ctx_config, state_dir=state_dir)
                ctx_status = ctx_policy.get_status() or {}
                brain["contextual"] = {
                    "enabled": bool(ctx_status.get("enabled", True)),
                    "mode": str(ctx_status.get("mode", "")),
                    "decision_threshold": float(ctx_config.decision_threshold),
                    "explore_rate": float(ctx_config.explore_rate),
                    "total_decisions": int(ctx_status.get("total_decisions", 0) or 0),
                    "execute_rate": float(ctx_status.get("execute_rate", 0.0) or 0.0),
                    "unique_contexts": int(ctx_status.get("unique_contexts", 0) or 0),
                }
        except Exception:
            pass

        # ML stats (from logged predictions in generated signals)
        try:
            if isinstance(ml_cfg, dict) and bool(ml_cfg.get("enabled", False)):
                min_prob = float(ml_cfg.get("min_probability", 0.55))
                passed = sum(1 for p in ml_probs if p >= min_prob)
                brain["ml"] = {
                    "enabled": True,
                    "min_probability": float(min_prob),
                    "predictions": int(len(ml_probs)),
                    "passed": int(passed),
                    "pass_rate": float(passed / max(1, len(ml_probs))) if ml_probs else 0.0,
                    "avg_prob": float(sum(ml_probs) / len(ml_probs)) if ml_probs else None,
                    "fallbacks": int(ml_fallbacks),
                    "fallback_rate": float(ml_fallbacks / max(1, len(ml_probs))) if ml_probs else 0.0,
                }
        except Exception:
            pass

        # Drift guard state (persisted by service in state_dir)
        try:
            dg_path = state_dir / "drift_guard_state.json"
            if dg_path.exists():
                raw = json.loads(dg_path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    brain["drift_guard"] = {
                        "active": bool(raw.get("active", False)),
                        "until": raw.get("until"),
                        "reason": raw.get("reason"),
                        "adjustments": raw.get("adjustments") if isinstance(raw.get("adjustments", {}), dict) else {},
                    }
        except Exception:
            pass

        # ML lift (shadow A/B) from graded exits (trades table)
        try:
            if isinstance(ml_cfg, dict) and bool(ml_cfg.get("enabled", False)):
                lookback = int(ml_cfg.get("lift_lookback_trades", 200) or 200)
                min_trades = int(ml_cfg.get("lift_min_trades", 50) or 50)
                min_lift = float(ml_cfg.get("lift_min_winrate_delta", 0.05) or 0.05)
                mode = str(ml_cfg.get("mode", "shadow") or "shadow").lower()
                require_lift = bool(ml_cfg.get("require_lift_to_block", True))

                try:
                    recent_trades = db.get_recent_trades_by_exit(limit=lookback, from_exit_time=cutoff)
                except Exception:
                    recent_trades = []

                scored = []
                for t in recent_trades:
                    feats = t.get("features", {}) if isinstance(t, dict) else {}
                    if not isinstance(feats, dict):
                        continue
                    if "ml_pass_filter" not in feats:
                        continue
                    try:
                        if float(feats.get("ml_fallback_used", 0.0) or 0.0) >= 0.5:
                            continue
                    except Exception:
                        pass
                    scored.append(t)

                if len(scored) >= min_trades:
                    p_group = []
                    f_group = []
                    for t in scored:
                        feats = t.get("features", {}) or {}
                        try:
                            pass_flag = float(feats.get("ml_pass_filter", 1.0) or 0.0) >= 0.5
                        except Exception:
                            pass_flag = True
                        (p_group if pass_flag else f_group).append(t)

                    def _wr(xs: List[Dict[str, Any]]) -> float:
                        wins = 0
                        for tt in xs:
                            try:
                                if bool(tt.get("is_win", False)):
                                    wins += 1
                            except Exception:
                                continue
                        return wins / max(1, len(xs))

                    if p_group and f_group:
                        wr_pass = _wr(p_group)
                        wr_fail = _wr(f_group)
                        lift_wr = wr_pass - wr_fail
                        lift_ok = bool(lift_wr >= min_lift)
                        blocking_allowed = (mode == "live") and (lift_ok if require_lift else True)
                        brain["ml_lift"] = {
                            "scored_trades": int(len(scored)),
                            "pass_trades": int(len(p_group)),
                            "fail_trades": int(len(f_group)),
                            "win_rate_pass": float(wr_pass),
                            "win_rate_fail": float(wr_fail),
                            "lift_win_rate": float(lift_wr),
                            "lift_min_winrate_delta": float(min_lift),
                            "lift_ok": bool(lift_ok),
                            "mode": mode,
                            "require_lift_to_block": bool(require_lift),
                            "blocking_allowed": bool(blocking_allowed),
                        }
                    else:
                        brain["ml_lift"] = {
                            "scored_trades": int(len(scored)),
                            "pass_trades": int(len(p_group)),
                            "fail_trades": int(len(f_group)),
                            "status": "no_split",
                        }
                else:
                    brain["ml_lift"] = {
                        "scored_trades": int(len(scored)),
                        "min_trades": int(min_trades),
                        "status": "insufficient_data",
                    }
        except Exception:
            pass

    except Exception:
        brain = {}

    return {
        "window_hours": float(hours),
        "cutoff": cutoff,
        "events": event_counts,
        "trade_summary": trade_summary,
        "cycle_diagnostics": diag,
        "quiet_reasons_top": quiet_top,
        "stop_bins": stop_counts,
        "size_bins": size_counts,
        "stop_avg": stop_avg,
        "stop_median": stop_med,
        "size_avg": size_avg,
        "size_median": size_med,
        "brain": brain,
    }


def format_doctor_rollup_text(r: Dict[str, Any]) -> str:
    lines: List[str] = []
    try:
        hours_val = float(r.get("window_hours", 24.0) or 24.0)
    except Exception:
        hours_val = 24.0
    hours_label = str(int(hours_val)) if hours_val.is_integer() else f"{hours_val:.2f}".rstrip("0").rstrip(".")
    lines.append(f"Doctor (last {hours_label}h)")
    lines.append("")

    # Signals
    lines.append("Signals (events):")
    events = r.get("events") or {}
    if events:
        for k in ("generated", "entered", "exited", "expired"):
            if k in events:
                lines.append(f"- {k}: {int(events.get(k, 0) or 0)}")
    else:
        lines.append("- (no events)")
    lines.append("")

    # Trades
    ts = r.get("trade_summary") or {}
    total = int(ts.get("total", 0) or 0)
    lines.append("Trades (exited):")
    lines.append(f"- total: {total}")
    if total > 0:
        lines.append(f"- WR: {_fmt_pct(ts.get('win_rate', 0.0) or 0.0)}")
        try:
            pnl = float(ts.get("total_pnl", 0.0) or 0.0)
            pnl_str = f"+${pnl:,.0f}" if pnl >= 0 else f"-${abs(pnl):,.0f}"
        except Exception:
            pnl_str = "$0"
        lines.append(f"- P&L: {pnl_str}")
        try:
            avg_hold = ts.get("avg_hold_minutes")
            if avg_hold is not None:
                lines.append(f"- avg hold: {float(avg_hold):.1f}m")
        except Exception:
            pass
    lines.append("")

    # Rejections
    diag = r.get("cycle_diagnostics") or {}
    lines.append("Rejections (cycle totals):")
    any_rej = False
    for key, label in [
        ("rejected_market_hours", "market hours"),
        ("rejected_confidence", "confidence"),
        ("rejected_risk_reward", "R:R"),
        ("rejected_regime_filter", "regime/session"),
        ("rejected_quality_scorer", "quality"),
        ("rejected_order_book", "order book"),
        ("rejected_invalid_prices", "invalid prices"),
        ("rejected_ml_filter", "ML"),
    ]:
        try:
            v = int(diag.get(key, 0) or 0)
        except Exception:
            v = 0
        if v > 0:
            any_rej = True
            lines.append(f"- {label}: {v}")
    if not any_rej:
        lines.append("- (no rejection data)")
    lines.append("")

    # Stops + Size
    stop_avg = r.get("stop_avg")
    stop_med = r.get("stop_median")
    stop_bins = r.get("stop_bins") or {}
    if stop_avg is not None and stop_med is not None:
        lines.append(f"Stops (pts): avg {float(stop_avg):.1f} | med {float(stop_med):.1f}")
    else:
        lines.append("Stops (pts):")
    lines.append("  " + " | ".join([f"{k}:{int(stop_bins.get(k, 0) or 0)}" for k in ["<5","5-10","10-15","15-20","20-25",">25"]]))

    size_avg = r.get("size_avg")
    size_med = r.get("size_median")
    size_bins = r.get("size_bins") or {}
    if size_avg is not None and size_med is not None:
        lines.append(f"Size (cts): avg {float(size_avg):.1f} | med {float(size_med):.1f}")
    else:
        lines.append("Size (cts):")
    lines.append("  " + " | ".join([f"{k}:{int(size_bins.get(k, 0) or 0)}" for k in ["1","2-3","4-5","6-8","9-12","13-15",">15"]]))
    lines.append("")

    # Quiet reasons
    quiet = r.get("quiet_reasons_top") or {}
    if quiet:
        lines.append("Quiet reasons (top):")
        for k, v in quiet.items():
            lines.append(f"- {k}: {int(v)}")

    # Brain / learning
    brain = r.get("brain") or {}
    if brain:
        lines.append("")
        lines.append("Brain (learning):")

        b = brain.get("bandit") or {}
        if b:
            try:
                unc = b.get("avg_uncertainty")
                unc_txt = f" | unc ±{float(unc):.0%}" if unc is not None else ""
                lines.append(
                    f"- Bandit: mode={b.get('mode')} | decisions={int(b.get('total_decisions', 0) or 0)} | "
                    f"outcomes={int(b.get('total_outcomes', 0) or 0)} | expWR={float(b.get('avg_expected_win_rate', 0.5) or 0.5):.0%}"
                    f"{unc_txt}"
                )
            except Exception:
                pass

        c = brain.get("contextual") or {}
        if c:
            try:
                lines.append(
                    f"- Contextual: mode={c.get('mode')} | decisions={int(c.get('total_decisions', 0) or 0)} | "
                    f"contexts={int(c.get('unique_contexts', 0) or 0)}"
                )
            except Exception:
                pass

        m = brain.get("ml") or {}
        if m:
            try:
                lines.append(
                    f"- ML: preds={int(m.get('predictions', 0) or 0)} | pass@{float(m.get('min_probability', 0.55) or 0.55):.2f}="
                    f"{int(m.get('passed', 0) or 0)} | fallback={int(m.get('fallbacks', 0) or 0)}"
                )
            except Exception:
                pass

        dg = brain.get("drift_guard") or {}
        if dg:
            try:
                if bool(dg.get("active", False)):
                    reason = str(dg.get("reason") or "")[:80]
                    until = str(dg.get("until") or "")
                    lines.append(f"- DriftGuard: ON until {until} ({reason})")
                else:
                    lines.append("- DriftGuard: OFF")
            except Exception:
                pass

        ml_lift = brain.get("ml_lift") or {}
        if ml_lift:
            try:
                if "lift_win_rate" in ml_lift:
                    lines.append(
                        f"- ML lift: passWR={float(ml_lift.get('win_rate_pass', 0.0) or 0.0):.0%} "
                        f"blockWR={float(ml_lift.get('win_rate_fail', 0.0) or 0.0):.0%} "
                        f"lift={float(ml_lift.get('lift_win_rate', 0.0) or 0.0):+.0%} "
                        f"(ok={bool(ml_lift.get('lift_ok', False))})"
                    )
                else:
                    lines.append(
                        f"- ML lift: {str(ml_lift.get('status', 'unknown'))} "
                        f"(scored={int(ml_lift.get('scored_trades', 0) or 0)})"
                    )
            except Exception:
                pass

    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Doctor rollup (local/ops)")
    parser.add_argument("--hours", type=float, default=24.0, help="Lookback window in hours (default: 24)")
    parser.add_argument("--db-path", type=str, default="", help="Override SQLite db path")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    args = parser.parse_args()

    # Load config to locate DB + ensure sqlite is enabled
    from pearlalgo.config.config_loader import load_service_config
    from pearlalgo.learning.trade_database import TradeDatabase

    cfg = load_service_config(validate=False) or {}
    storage_cfg = cfg.get("storage", {}) or {}
    sqlite_enabled = bool(storage_cfg.get("sqlite_enabled", False))
    if not sqlite_enabled and not args.db_path:
        print("SQLite storage disabled. Enable `storage.sqlite_enabled: true` in config/config.yaml.")
        return 2

    db_path = args.db_path or str(storage_cfg.get("db_path") or "data/agent_state/NQ/trades.db")
    db = TradeDatabase(Path(db_path))

    rollup = build_doctor_rollup(db, hours=args.hours)
    if args.json:
        print(json.dumps(rollup, indent=2, ensure_ascii=False))
    else:
        print(format_doctor_rollup_text(rollup))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
