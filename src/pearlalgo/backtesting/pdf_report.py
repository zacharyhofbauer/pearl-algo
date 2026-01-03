from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from pearlalgo.utils.logger import logger


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return float(default)
        return float(x)
    except Exception:
        return float(default)


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        if x is None:
            return int(default)
        return int(float(x))
    except Exception:
        return int(default)


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        if path.exists():
            with open(path, "r") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else None
    except Exception as e:
        logger.warning(f"Could not read JSON {path}: {e}")
    return None


def _read_csv(path: Path) -> Optional[pd.DataFrame]:
    try:
        if path.exists():
            df = pd.read_csv(path)
            return df
    except Exception as e:
        logger.warning(f"Could not read CSV {path}: {e}")
    return None


def write_backtest_pdf_report(report_dir: Path, *, output_name: str = "report.pdf") -> Path:
    """
    Generate a detailed multi-page PDF backtest report inside `report_dir`.

    Uses matplotlib (already a project dependency) to avoid heavy external tooling.
    """
    # Import matplotlib lazily (keeps import time low for bots)
    import matplotlib

    matplotlib.use("Agg")  # Headless-safe
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    import matplotlib.image as mpimg

    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / output_name

    summary = _read_json(report_dir / "summary.json") or {}
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    date_range = summary.get("date_range") if isinstance(summary.get("date_range"), dict) else {}
    verification = summary.get("verification") if isinstance(summary.get("verification"), dict) else {}

    symbol = str(summary.get("symbol") or "?")
    decision_tf = str(summary.get("decision_timeframe") or "?")
    run_ts = str(summary.get("run_timestamp") or "")
    start = str(date_range.get("actual_start") or "")[:10] if date_range else ""
    end = str(date_range.get("actual_end") or "")[:10] if date_range else ""

    # Load optional datasets
    trades_df = _read_csv(report_dir / "trades.csv")
    signals_df = _read_csv(report_dir / "signals.csv")

    # Detect charts
    chart_paths: List[Tuple[str, Path]] = []
    if (report_dir / "chart_overview.png").exists():
        chart_paths.append(("Price Overview", report_dir / "chart_overview.png"))
    if (report_dir / "equity_curve.png").exists():
        chart_paths.append(("Equity Curve", report_dir / "equity_curve.png"))

    def _add_page_title(fig, title: str, subtitle: str = "") -> None:
        fig.text(0.06, 0.96, title, fontsize=16, fontweight="bold", va="top")
        if subtitle:
            fig.text(0.06, 0.935, subtitle, fontsize=10, color="#444", va="top")

    def _fmt_money(v: float) -> str:
        sign = "+" if v >= 0 else "-"
        return f"{sign}${abs(v):,.2f}"

    # Pre-compute trade breakdowns (best-effort)
    trade_type_rows = []
    best_trades = None
    worst_trades = None
    pnl_series = None
    if trades_df is not None and not trades_df.empty and "pnl" in trades_df.columns:
        try:
            tmp = trades_df.copy()
            tmp["pnl"] = pd.to_numeric(tmp["pnl"], errors="coerce").fillna(0.0)
            pnl_series = tmp["pnl"].to_numpy()
            if "signal_type" in tmp.columns:
                grp = tmp.groupby(tmp["signal_type"].fillna("unknown"))
                for st, g in grp:
                    n = len(g)
                    pnl_total = float(g["pnl"].sum())
                    wins = int((g["pnl"] > 0).sum())
                    win_rate = wins / n if n else 0.0
                    trade_type_rows.append(
                        (str(st), n, win_rate, pnl_total, pnl_total / n if n else 0.0)
                    )
                trade_type_rows.sort(key=lambda r: r[3], reverse=True)
            best_trades = tmp.sort_values("pnl", ascending=False).head(12)
            worst_trades = tmp.sort_values("pnl", ascending=True).head(12)
        except Exception:
            pass

    with PdfPages(out_path) as pdf:
        # ---------------------------------------------------------------------
        # Page 1: Overview
        # ---------------------------------------------------------------------
        fig = plt.figure(figsize=(8.5, 11))
        _add_page_title(
            fig,
            f"Backtest Report — {symbol}",
            f"{decision_tf} decision • {start} → {end} • run {run_ts}",
        )

        ax = fig.add_axes([0.06, 0.08, 0.88, 0.82])
        ax.axis("off")

        rows = [
            ("Total P&L", _fmt_money(_safe_float(metrics.get("total_pnl")))),
            ("Max Drawdown", f"${_safe_float(metrics.get('max_drawdown')):,.2f}"),
            ("Profit Factor", f"{_safe_float(metrics.get('profit_factor')):.2f}"),
            ("Sharpe", f"{_safe_float(metrics.get('sharpe_ratio')):.2f}"),
            ("Trades", f"{_safe_int(metrics.get('total_trades')):,}"),
            ("Win Rate", f"{_safe_float(metrics.get('win_rate'))*100:.1f}%"),
            ("Signals", f"{_safe_int(metrics.get('total_signals')):,}"),
            ("Avg Confidence", f"{_safe_float(metrics.get('avg_confidence')):.2f}"),
            ("Avg R:R", f"{_safe_float(metrics.get('avg_risk_reward')):.2f}:1"),
        ]

        # Build a simple table
        table = ax.table(
            cellText=[[k, v] for k, v in rows],
            colLabels=["Metric", "Value"],
            loc="upper left",
            cellLoc="left",
            colLoc="left",
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.0, 1.4)

        # Verification highlight (compact)
        v = verification or {}
        try:
            signals_per_day = _safe_float(v.get("signals_per_day"))
            trading_days = _safe_int(v.get("trading_days"))
            bottlenecks = v.get("bottleneck_summary") if isinstance(v.get("bottleneck_summary"), dict) else {}
            top_bn = ", ".join(list(bottlenecks.keys())[:5]) if bottlenecks else "n/a"
            ax.text(0.0, 0.45, "Strategy Health (verification)", fontsize=12, fontweight="bold", transform=ax.transAxes)
            ax.text(
                0.0,
                0.41,
                f"Signals/day: {signals_per_day:.2f}  •  Trading days: {trading_days}  •  Top bottlenecks: {top_bn}",
                fontsize=10,
                color="#333",
                transform=ax.transAxes,
            )
        except Exception:
            pass

        pdf.savefig(fig)
        plt.close(fig)

        # ---------------------------------------------------------------------
        # Page 2: Charts
        # ---------------------------------------------------------------------
        if chart_paths:
            fig = plt.figure(figsize=(8.5, 11))
            _add_page_title(fig, "Charts", "Price + equity views")

            n = len(chart_paths)
            for i, (label, p) in enumerate(chart_paths[:2]):
                ax = fig.add_axes([0.06, 0.52 - i * 0.44, 0.88, 0.40])
                ax.axis("off")
                ax.text(0.0, 1.02, label, fontsize=12, fontweight="bold", transform=ax.transAxes)
                try:
                    img = mpimg.imread(p)
                    ax.imshow(img)
                except Exception as e:
                    ax.text(0.0, 0.5, f"Could not load chart: {p.name}\n{e}", fontsize=10, color="#aa0000")

            pdf.savefig(fig)
            plt.close(fig)

        # ---------------------------------------------------------------------
        # Page 3: Trades analysis
        # ---------------------------------------------------------------------
        if trades_df is not None and not trades_df.empty and pnl_series is not None:
            fig = plt.figure(figsize=(8.5, 11))
            _add_page_title(fig, "Trades Analysis", "Distribution, type breakdown, best/worst")

            # Histogram
            ax1 = fig.add_axes([0.08, 0.62, 0.84, 0.28])
            ax1.hist(pnl_series, bins=30, color="#2962ff", alpha=0.85)
            ax1.set_title("Trade P&L Distribution")
            ax1.set_xlabel("P&L")
            ax1.set_ylabel("Count")
            ax1.grid(True, alpha=0.2)

            # Type breakdown table (top 12)
            ax2 = fig.add_axes([0.08, 0.34, 0.84, 0.22])
            ax2.axis("off")
            if trade_type_rows:
                ax2.text(0.0, 1.05, "Trade Types (top 12 by total P&L)", fontsize=12, fontweight="bold", transform=ax2.transAxes)
                trows = trade_type_rows[:12]
                tt = ax2.table(
                    cellText=[
                        [st, f"{n}", f"{wr*100:.1f}%", _fmt_money(pnl), _fmt_money(avg)]
                        for st, n, wr, pnl, avg in trows
                    ],
                    colLabels=["Type", "n", "WR", "Total P&L", "Avg P&L"],
                    loc="upper left",
                    cellLoc="left",
                    colLoc="left",
                )
                tt.auto_set_font_size(False)
                tt.set_fontsize(9)
                tt.scale(1.0, 1.2)
            else:
                ax2.text(0.0, 0.7, "No trade type breakdown available.", fontsize=10, color="#555")

            # Best/Worst tables
            ax3 = fig.add_axes([0.08, 0.06, 0.84, 0.24])
            ax3.axis("off")

            def _table_from(df_in: pd.DataFrame, title: str, y: float) -> None:
                ax3.text(0.0, y, title, fontsize=11, fontweight="bold", transform=ax3.transAxes)
                cols = [c for c in ["exit_time", "direction", "signal_type", "pnl"] if c in df_in.columns]
                view = df_in[cols].copy()
                if "exit_time" in view.columns:
                    view["exit_time"] = view["exit_time"].astype(str).str.slice(0, 16)
                if "pnl" in view.columns:
                    view["pnl"] = view["pnl"].map(lambda x: f"{_safe_float(x):+.2f}")
                tt = ax3.table(
                    cellText=view.values.tolist(),
                    colLabels=view.columns.tolist(),
                    loc="upper left",
                    cellLoc="left",
                    colLoc="left",
                )
                tt.auto_set_font_size(False)
                tt.set_fontsize(8)
                tt.scale(1.0, 1.0)

            if best_trades is not None and worst_trades is not None:
                # Split area into two half-height tables by saving separate pages (cleaner)
                # Page 3 already dense; keep a second trade list page if needed.
                pdf.savefig(fig)
                plt.close(fig)

                fig2 = plt.figure(figsize=(8.5, 11))
                _add_page_title(fig2, "Top / Bottom Trades", "Quick sanity check for outliers")
                ax = fig2.add_axes([0.06, 0.08, 0.88, 0.84])
                ax.axis("off")

                ax.text(0.0, 0.98, "Best trades (top 12)", fontsize=12, fontweight="bold", transform=ax.transAxes)
                cols = [c for c in ["exit_time", "direction", "signal_type", "pnl"] if c in best_trades.columns]
                b = best_trades[cols].copy()
                if "exit_time" in b.columns:
                    b["exit_time"] = b["exit_time"].astype(str).str.slice(0, 16)
                if "pnl" in b.columns:
                    b["pnl"] = b["pnl"].map(lambda x: f"{_safe_float(x):+.2f}")
                t1 = ax.table(
                    cellText=b.values.tolist(),
                    colLabels=b.columns.tolist(),
                    loc="upper left",
                    cellLoc="left",
                    colLoc="left",
                )
                t1.auto_set_font_size(False)
                t1.set_fontsize(8)
                t1.scale(1.0, 1.1)

                ax.text(0.0, 0.46, "Worst trades (bottom 12)", fontsize=12, fontweight="bold", transform=ax.transAxes)
                wcols = [c for c in ["exit_time", "direction", "signal_type", "pnl"] if c in worst_trades.columns]
                w = worst_trades[wcols].copy()
                if "exit_time" in w.columns:
                    w["exit_time"] = w["exit_time"].astype(str).str.slice(0, 16)
                if "pnl" in w.columns:
                    w["pnl"] = w["pnl"].map(lambda x: f"{_safe_float(x):+.2f}")
                t2 = ax.table(
                    cellText=w.values.tolist(),
                    colLabels=w.columns.tolist(),
                    loc="lower left",
                    cellLoc="left",
                    colLoc="left",
                )
                t2.auto_set_font_size(False)
                t2.set_fontsize(8)
                t2.scale(1.0, 1.1)

                pdf.savefig(fig2)
                plt.close(fig2)
            else:
                pdf.savefig(fig)
                plt.close(fig)

        # ---------------------------------------------------------------------
        # Page 4: Verification / explainability
        # ---------------------------------------------------------------------
        if verification:
            fig = plt.figure(figsize=(8.5, 11))
            _add_page_title(fig, "Verification & Explainability", "Why signals/trades happened (or not)")
            ax = fig.add_axes([0.06, 0.08, 0.88, 0.84])
            ax.axis("off")

            v = verification
            lines = []
            for k in ("signals_per_day", "signals_per_hour", "trading_days", "trading_hours"):
                if k in v:
                    lines.append(f"{k}: {v.get(k)}")

            ax.text(0.0, 0.96, "Key stats", fontsize=12, fontweight="bold", transform=ax.transAxes)
            ax.text(0.0, 0.92, "\n".join(lines) if lines else "n/a", fontsize=10, color="#333", transform=ax.transAxes)

            # Bottlenecks
            bottlenecks = v.get("bottleneck_summary") if isinstance(v.get("bottleneck_summary"), dict) else {}
            if bottlenecks:
                top = sorted(bottlenecks.items(), key=lambda kv: -_safe_int(kv[1]))[:12]
                ax.text(0.0, 0.82, "Top bottlenecks", fontsize=12, fontweight="bold", transform=ax.transAxes)
                ax.text(
                    0.0,
                    0.78,
                    "\n".join([f"- {k}: {int(v)}" for k, v in top]),
                    fontsize=10,
                    color="#333",
                    transform=ax.transAxes,
                )

            # Gate reasons
            gate_reasons = v.get("top_gate_reasons") if isinstance(v.get("top_gate_reasons"), list) else []
            if gate_reasons:
                ax.text(0.0, 0.52, "Top gate reasons", fontsize=12, fontweight="bold", transform=ax.transAxes)
                ax.text(
                    0.0,
                    0.48,
                    "\n".join([f"- {str(r)[:120]}" for r in gate_reasons[:12]]),
                    fontsize=10,
                    color="#333",
                    transform=ax.transAxes,
                )

            # Execution summary
            exec_summary = v.get("execution_summary") if isinstance(v.get("execution_summary"), dict) else {}
            if exec_summary:
                ax.text(0.0, 0.22, "Execution summary", fontsize=12, fontweight="bold", transform=ax.transAxes)
                top = list(exec_summary.items())[:18]
                ax.text(
                    0.0,
                    0.18,
                    "\n".join([f"- {k}: {int(_safe_int(v))}" for k, v in top]),
                    fontsize=10,
                    color="#333",
                    transform=ax.transAxes,
                )

            pdf.savefig(fig)
            plt.close(fig)

    return out_path


