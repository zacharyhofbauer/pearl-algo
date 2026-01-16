from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


@dataclass(frozen=True)
class MonitorPaths:
    project_root: Path
    state_dir: Path
    state_json: Path
    signals_jsonl: Path
    events_jsonl: Path
    exports_dir: Path
    chart_png: Path
    chart_meta: Path
    logs_dir: Path
    agent_log: Path


def _guess_paths() -> MonitorPaths:
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    state_dir = project_root / "data" / "nq_agent_state"
    exports_dir = state_dir / "exports"
    logs_dir = project_root / "logs"
    return MonitorPaths(
        project_root=project_root,
        state_dir=state_dir,
        state_json=state_dir / "state.json",
        signals_jsonl=state_dir / "signals.jsonl",
        events_jsonl=state_dir / "events.jsonl",
        exports_dir=exports_dir,
        chart_png=exports_dir / "dashboard_latest.png",
        chart_meta=exports_dir / "dashboard_latest.meta.json",
        logs_dir=logs_dir,
        agent_log=logs_dir / "nq_agent.log",
    )


def _read_json(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except Exception:
        return None


def _read_jsonl_tail(path: Path, *, limit: int = 200) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text().splitlines()
        out: list[dict] = []
        for line in lines[-max(1, int(limit)) :]:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _tail_text_file(path: Path, *, max_lines: int = 200, max_bytes: int = 250_000) -> str:
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        start = max(0, size - max_bytes)
        with open(path, "rb") as f:
            f.seek(start)
            data = f.read()
        text = data.decode(errors="ignore")
        lines = text.splitlines()
        return "\n".join(lines[-max(1, int(max_lines)) :])
    except Exception:
        return ""


def _format_state_summary(state: Optional[dict]) -> str:
    if not state:
        return "No state yet (agent offline?)"

    running = state.get("running")
    paused = state.get("paused")
    cycle = state.get("cycle_count")
    data_fresh = state.get("data_fresh")
    age_min = state.get("latest_bar_age_minutes")
    quiet_reason = state.get("quiet_reason")
    diag = state.get("signal_diagnostics")
    updated = state.get("last_updated")

    lines = [
        f"Agent: {'RUNNING' if running else 'OFFLINE'}",
        f"Paused: {bool(paused)}",
        f"Cycle: {cycle}",
        f"Data fresh: {data_fresh} (age_min={age_min})",
        f"Quiet reason: {quiet_reason or ''}",
        f"Diagnostics: {diag or ''}",
        f"Updated: {updated or ''}",
    ]
    return "\n".join(lines)


def _format_signals(signals: list[dict]) -> str:
    if not signals:
        return "No signals yet."
    out: list[str] = []
    for rec in signals[-50:]:
        sig = rec.get("signal") or {}
        out.append(
            " | ".join(
                [
                    str(rec.get("timestamp", "")),
                    str(sig.get("symbol", "")),
                    f"{sig.get('type', '')} {sig.get('direction', '')}".strip(),
                    f"conf={float(sig.get('confidence') or 0.0):.2f}",
                    f"entry={float(sig.get('entry_price') or 0.0):.2f}",
                    f"sl={float(sig.get('stop_loss') or 0.0):.2f}",
                    f"tp={float(sig.get('take_profit') or 0.0):.2f}",
                ]
            )
        )
    return "\n".join(out)


def _format_events(events: list[dict], *, filter_levels: Optional[set[str]] = None) -> str:
    if not events:
        return "No events yet."
    out: list[str] = []
    for ev in events[-200:]:
        lvl = str(ev.get("level") or "").lower()
        if filter_levels is not None and lvl not in filter_levels:
            continue
        ts = str(ev.get("timestamp") or "")
        et = str(ev.get("type") or "")
        payload = ev.get("payload") or {}
        # Keep payload compact
        payload_str = ""
        try:
            payload_str = json.dumps(payload, ensure_ascii=False)
        except Exception:
            payload_str = str(payload)
        out.append(f"{ts} [{lvl or 'info'}] {et} {payload_str}")
    return "\n".join(out) if out else "No matching events."


def _format_chart_meta(meta: Optional[dict]) -> str:
    if not meta:
        return "Chart: (no meta)"
    gen = meta.get("generated_at")
    tf = meta.get("timeframe", "")
    label = meta.get("range_label", "")
    age_s = None
    try:
        if gen:
            dt = datetime.fromisoformat(str(gen))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            age_s = int((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except Exception:
        age_s = None
    age_str = f"{age_s}s ago" if age_s is not None and age_s >= 0 else "unknown age"
    return f"Chart: Updated {age_str} • {label} • {tf}"


def _abbr_number(value: Optional[float]) -> str:
    if value is None:
        return "-"
    try:
        num = float(value)
    except Exception:
        return "-"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}m"
    if num >= 1_000:
        return f"{num / 1_000:.1f}k"
    if num.is_integer():
        return f"{int(num)}"
    return f"{num:.2f}"


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.0f}%"
    except Exception:
        return "-"


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _format_time_short(ts: Optional[str]) -> str:
    dt = _parse_iso(ts)
    if dt is None:
        return "--:--"
    return dt.astimezone(timezone.utc).strftime("%H:%M")


def _format_signal_html(signals: list[dict]) -> str:
    if not signals:
        return "<span style='color:#7d8590'>No signals yet.</span>"
    rows: list[str] = []
    for rec in signals[-12:]:
        sig = rec.get("signal") or {}
        direction = str(sig.get("direction") or "").upper()
        color = "#3fb950" if direction == "LONG" else "#f85149" if direction == "SHORT" else "#58a6ff"
        ts = _format_time_short(rec.get("timestamp"))
        conf = sig.get("confidence")
        entry = sig.get("entry_price")
        symbol = str(sig.get("symbol") or "")
        rows.append(
            " ".join(
                [
                    f"<span style='color:#7d8590'>{ts}</span>",
                    f"<span style='color:{color}; font-weight:600'>{direction or 'SIGNAL'}</span>",
                    f"<span style='color:#e6edf3'>{symbol}</span>" if symbol else "",
                    f"<span style='color:#7d8590'>conf {float(conf or 0.0):.2f}</span>",
                    f"<span style='color:#7d8590'>@ {float(entry or 0.0):.2f}</span>",
                ]
            ).strip()
        )
    return "<br/>".join(rows)


def _format_activity_html(events: list[dict]) -> str:
    if not events:
        return "<span style='color:#7d8590'>No activity yet.</span>"
    keep_types = {"signal_generated", "error", "scan_finished", "scan_started", "circuit_breaker"}
    rows: list[str] = []
    for ev in events[-50:]:
        et = str(ev.get("type") or "")
        if et and et not in keep_types:
            continue
        lvl = str(ev.get("level") or "").lower()
        color = "#f85149" if lvl in {"error", "critical"} else "#d29922" if lvl in {"warn", "warning"} else "#58a6ff"
        ts = _format_time_short(ev.get("timestamp"))
        rows.append(
            f"<span style='color:#7d8590'>{ts}</span> "
            f"<span style='color:{color}; font-weight:600'>{et}</span>"
        )
    return "<br/>".join(rows[-15:]) if rows else "<span style='color:#7d8590'>No activity yet.</span>"


def run_monitor() -> None:
    try:
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtGui import QFont, QPixmap, QGuiApplication
        from PyQt6.QtWidgets import (
            QApplication,
            QFrame,
            QGridLayout,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QSizePolicy,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
        from PyQt6.QtCore import QFileSystemWatcher
    except Exception:
        print("PyQt6 is not installed.")
        print("Install with: pip install -e \".[monitor]\"")
        raise

    paths = _guess_paths()

    class ChartWidget(QFrame):
        def __init__(self) -> None:
            super().__init__()
            self.setFrameShape(QFrame.Shape.NoFrame)
            self._orig: Optional[QPixmap] = None

            self.meta_label = QLabel("Chart: (no meta)")
            self.meta_label.setStyleSheet("color: #e6edf3; font-size: 13px; font-weight: 600;")

            self.image_label = QLabel()
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.image_label.setStyleSheet("background-color: #0d1117;")

            layout = QVBoxLayout()
            layout.setContentsMargins(8, 8, 8, 8)
            layout.setSpacing(8)
            layout.addWidget(self.meta_label)
            layout.addWidget(self.image_label, 1)
            self.setLayout(layout)

        def set_chart(self, pix: Optional[QPixmap], meta: Optional[dict]) -> None:
            self._orig = pix
            self.meta_label.setText(_format_chart_meta(meta))
            self._rescale()

        def resizeEvent(self, event) -> None:  # type: ignore[override]
            super().resizeEvent(event)
            self._rescale()

        def _rescale(self) -> None:
            if self._orig is None or self._orig.isNull():
                self.image_label.setText("No chart yet.")
                self.image_label.setStyleSheet("background-color: #0d1117; color: #7d8590;")
                return
            target = self.image_label.size()
            scaled = self._orig.scaled(
                target,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.image_label.setPixmap(scaled)

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Pearl Algo Monitor")
            self.setStyleSheet("background-color: #0d1117; color: #e6edf3;")

            base_font = QFont("DejaVu Sans")
            base_font.setPointSize(11)
            self.setFont(base_font)

            header_font = QFont("DejaVu Sans")
            header_font.setPointSize(13)
            header_font.setBold(True)

            label_font = QFont("DejaVu Sans")
            label_font.setPointSize(11)

            value_font = QFont("DejaVu Sans")
            value_font.setPointSize(12)

            mono_font = QFont("DejaVu Sans Mono")
            mono_font.setPointSize(12)

            def make_section(title: str) -> QFrame:
                frame = QFrame()
                frame.setStyleSheet(
                    "background-color: #161b22; border: 1px solid #30363d; border-radius: 4px;"
                )
                layout = QVBoxLayout()
                layout.setContentsMargins(8, 8, 8, 8)
                layout.setSpacing(6)
                title_label = QLabel(title)
                title_label.setFont(header_font)
                title_label.setStyleSheet("color: #e6edf3;")
                layout.addWidget(title_label)
                frame.setLayout(layout)
                return frame

            # Status bar
            self.status_bar = QFrame()
            self.status_bar.setFixedHeight(40)
            self.status_bar.setStyleSheet(
                "background-color: #161b22; border-bottom: 1px solid #30363d;"
            )
            status_layout = QHBoxLayout()
            status_layout.setContentsMargins(12, 6, 12, 6)
            status_layout.setSpacing(10)
            self.status_label = QLabel("Loading status...")
            self.status_label.setTextFormat(Qt.TextFormat.RichText)
            self.status_label.setFont(value_font)
            self.status_label.setStyleSheet("color: #e6edf3;")
            status_layout.addWidget(self.status_label, 1)
            self.status_bar.setLayout(status_layout)

            # Left panel
            left_frame = QFrame()
            left_frame.setFixedWidth(220)
            left_frame.setStyleSheet("background-color: #0d1117;")
            left_layout = QVBoxLayout()
            left_layout.setContentsMargins(8, 8, 8, 8)
            left_layout.setSpacing(8)

            stats_section = make_section("STATS")
            stats_grid = QGridLayout()
            stats_grid.setContentsMargins(0, 0, 0, 0)
            stats_grid.setHorizontalSpacing(6)
            stats_grid.setVerticalSpacing(4)
            stats_section.layout().addLayout(stats_grid)

            def add_stat_row(row: int, label: str) -> QLabel:
                label_widget = QLabel(label)
                label_widget.setFont(label_font)
                label_widget.setStyleSheet("color: #7d8590;")
                value_widget = QLabel("-")
                value_widget.setFont(mono_font)
                value_widget.setStyleSheet("color: #e6edf3;")
                stats_grid.addWidget(label_widget, row, 0)
                stats_grid.addWidget(value_widget, row, 1)
                return value_widget

            self.stats_signals = add_stat_row(0, "Signals")
            self.stats_session = add_stat_row(1, "Session")
            self.stats_scans = add_stat_row(2, "Scans")
            self.stats_errors = add_stat_row(3, "Errors")

            gate_section = make_section("GATE")
            gate_layout = gate_section.layout()
            self.gate_reason = QLabel("-")
            self.gate_reason.setFont(value_font)
            self.gate_reason.setStyleSheet("color: #e6edf3;")
            self.gate_diag = QLabel("-")
            self.gate_diag.setFont(label_font)
            self.gate_diag.setStyleSheet("color: #7d8590;")
            self.gate_diag.setWordWrap(True)
            self.gate_regime = QLabel("-")
            self.gate_regime.setFont(label_font)
            self.gate_regime.setStyleSheet("color: #7d8590;")
            gate_layout.addWidget(self.gate_reason)
            gate_layout.addWidget(self.gate_diag)
            gate_layout.addWidget(self.gate_regime)

            learning_section = make_section("LEARNING")
            learning_layout = learning_section.layout()
            self.learning_mode = QLabel("-")
            self.learning_mode.setFont(value_font)
            self.learning_mode.setStyleSheet("color: #e6edf3;")
            self.learning_rate = QLabel("-")
            self.learning_rate.setFont(label_font)
            self.learning_rate.setStyleSheet("color: #7d8590;")
            self.learning_total = QLabel("-")
            self.learning_total.setFont(label_font)
            self.learning_total.setStyleSheet("color: #7d8590;")
            learning_layout.addWidget(self.learning_mode)
            learning_layout.addWidget(self.learning_rate)
            learning_layout.addWidget(self.learning_total)

            left_layout.addWidget(stats_section)
            left_layout.addWidget(gate_section)
            left_layout.addWidget(learning_section)
            left_layout.addStretch(1)
            left_frame.setLayout(left_layout)

            # Center chart
            self.chart = ChartWidget()

            # Right panel
            right_frame = QFrame()
            right_frame.setFixedWidth(360)
            right_frame.setStyleSheet("background-color: #0d1117;")
            right_layout = QVBoxLayout()
            right_layout.setContentsMargins(8, 8, 8, 8)
            right_layout.setSpacing(8)

            signals_section = make_section("SIGNALS")
            self.signals_view = QTextEdit()
            self.signals_view.setReadOnly(True)
            self.signals_view.setFont(label_font)
            self.signals_view.setStyleSheet(
                "background-color: #0d1117; color: #e6edf3; border: 1px solid #30363d;"
            )
            self.signals_view.setMinimumHeight(260)
            signals_section.layout().addWidget(self.signals_view)

            activity_section = make_section("ACTIVITY")
            self.activity_view = QTextEdit()
            self.activity_view.setReadOnly(True)
            self.activity_view.setFont(label_font)
            self.activity_view.setStyleSheet(
                "background-color: #0d1117; color: #e6edf3; border: 1px solid #30363d;"
            )
            activity_section.layout().addWidget(self.activity_view)

            right_layout.addWidget(signals_section, 3)
            right_layout.addWidget(activity_section, 2)
            right_frame.setLayout(right_layout)

            content = QWidget()
            content_layout = QHBoxLayout()
            content_layout.setContentsMargins(0, 0, 0, 0)
            content_layout.setSpacing(0)
            content_layout.addWidget(left_frame)
            content_layout.addWidget(self.chart, 1)
            content_layout.addWidget(right_frame)
            content.setLayout(content_layout)

            root = QWidget()
            root_layout = QVBoxLayout()
            root_layout.setContentsMargins(0, 0, 0, 0)
            root_layout.setSpacing(0)
            root_layout.addWidget(self.status_bar)
            root_layout.addWidget(content, 1)
            root.setLayout(root_layout)
            self.setCentralWidget(root)

            # Watcher + heartbeat
            self.watcher = QFileSystemWatcher()
            self.watcher.directoryChanged.connect(lambda _p: self.refresh())  # type: ignore[arg-type]
            self.watcher.fileChanged.connect(lambda _p: self.refresh())  # type: ignore[arg-type]

            # Watch directories so files can appear later
            for d in [paths.state_dir, paths.exports_dir, paths.logs_dir]:
                try:
                    d.mkdir(parents=True, exist_ok=True)
                    self.watcher.addPath(str(d))
                except Exception:
                    pass

            for f in [paths.state_json, paths.signals_jsonl, paths.events_jsonl, paths.chart_png, paths.chart_meta, paths.agent_log]:
                if f.exists():
                    try:
                        self.watcher.addPath(str(f))
                    except Exception:
                        pass

            self.timer = QTimer()
            self.timer.setInterval(5_000)
            self.timer.timeout.connect(self.refresh)  # type: ignore[arg-type]
            self.timer.start()

            self.refresh()

        def refresh(self) -> None:
            state = _read_json(paths.state_json) or {}
            running = bool(state.get("running"))
            paused = bool(state.get("paused"))
            status_color = "#3fb950" if running and not paused else "#d29922" if paused else "#f85149"
            status_text = "RUNNING" if running and not paused else "PAUSED" if paused else "OFFLINE"

            latest_bar = state.get("latest_bar") or {}
            symbol = str(state.get("config", {}).get("symbol") or latest_bar.get("symbol") or "MNQ")
            price = latest_bar.get("close")
            regime = state.get("regime") or {}
            regime_name = str(regime.get("regime") or "unknown").upper()
            regime_conf = regime.get("confidence")

            pressure = state.get("buy_sell_pressure_raw") or {}
            pressure_bias = str(pressure.get("bias") or "").upper()
            pressure_score = pressure.get("score_pct")

            cycle = state.get("cycle_count")
            last_updated = state.get("last_updated")
            age_s = None
            dt = _parse_iso(last_updated)
            if dt is not None:
                age_s = int((datetime.now(timezone.utc) - dt).total_seconds())
            age_str = f"{age_s}s ago" if age_s is not None and age_s >= 0 else "unknown"
            now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")

            self.status_label.setText(
                " ".join(
                    [
                        f"<span style='color:{status_color}; font-weight:700'>●</span>",
                        f"<span style='color:#e6edf3; font-weight:700'>{status_text}</span>",
                        f"<span style='color:#7d8590'>|</span>",
                        f"<span style='color:#e6edf3'>{symbol} {float(price or 0.0):.2f}</span>",
                        f"<span style='color:#7d8590'>|</span>",
                        f"<span style='color:#58a6ff'>{regime_name} {_format_pct(regime_conf)}</span>",
                        f"<span style='color:#7d8590'>|</span>",
                        f"<span style='color:#e6edf3'>{pressure_bias} {_format_pct((pressure_score or 0) / 100)}</span>",
                        f"<span style='color:#7d8590'>|</span>",
                        f"<span style='color:#e6edf3'>Cycle {_abbr_number(cycle)}</span>",
                        f"<span style='color:#7d8590'>|</span>",
                        f"<span style='color:#7d8590'>Updated {age_str}</span>",
                        f"<span style='color:#7d8590'>|</span>",
                        f"<span style='color:#7d8590'>{now_str}</span>",
                    ]
                )
            )

            self.stats_signals.setText(
                f"{_abbr_number(state.get('signal_count'))} / {_abbr_number(state.get('signal_count_session'))}"
            )
            self.stats_session.setText(_abbr_number(state.get("cycle_count_session")))
            self.stats_scans.setText(_abbr_number(cycle))
            self.stats_errors.setText(
                f"{_abbr_number(state.get('error_count'))} / {_abbr_number(state.get('consecutive_errors'))}"
            )

            quiet_reason = str(state.get("quiet_reason") or "-")
            diag = str(state.get("signal_diagnostics") or "-")
            self.gate_reason.setText(f"Reason: {quiet_reason}")
            self.gate_diag.setText(diag[:120])
            self.gate_regime.setText(f"Regime: {regime.get('regime', 'unknown')}")

            learning = state.get("learning") or {}
            self.learning_mode.setText(f"Mode: {learning.get('mode') or '-'}")
            self.learning_rate.setText(f"Execute: {_format_pct(learning.get('execute_rate'))}")
            self.learning_total.setText(f"Decisions: {_abbr_number(learning.get('total_decisions'))}")

            signals = _read_jsonl_tail(paths.signals_jsonl, limit=200)
            self.signals_view.setHtml(_format_signal_html(signals))

            events = _read_jsonl_tail(paths.events_jsonl, limit=400)
            self.activity_view.setHtml(_format_activity_html(events))

            # Chart
            meta = _read_json(paths.chart_meta)
            pix = None
            if paths.chart_png.exists():
                try:
                    pix = QPixmap(str(paths.chart_png))
                except Exception:
                    pix = None
            self.chart.set_chart(pix, meta)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    # Show as normal maximized window (not fullscreen) so user can resize/close
    try:
        target = None
        for s in QGuiApplication.screens():
            g = s.geometry()
            if int(g.width()) == 2560 and int(g.height()) == 720:
                target = s
                break
        if target is not None:
            win.show()  # ensure window handle exists
            try:
                handle = win.windowHandle()
                if handle is not None:
                    handle.setScreen(target)
            except Exception:
                pass
            try:
                win.setGeometry(target.geometry())
            except Exception:
                pass
        win.showMaximized()
    except Exception:
        win.showMaximized()
    sys.exit(app.exec())

