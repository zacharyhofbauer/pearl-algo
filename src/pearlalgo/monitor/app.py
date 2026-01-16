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


def run_monitor() -> None:
    try:
        from PyQt6.QtCore import Qt, QTimer
        from PyQt6.QtGui import QFont, QPixmap
        from PyQt6.QtWidgets import (
            QApplication,
            QFrame,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QPlainTextEdit,
            QSizePolicy,
            QTabWidget,
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
            self.meta_label.setStyleSheet("color: #d1d4dc; font-size: 14px;")

            self.image_label = QLabel()
            self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.image_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            self.image_label.setStyleSheet("background-color: #0e1013;")

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
                self.image_label.setStyleSheet("background-color: #0e1013; color: #787b86;")
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
            self.setStyleSheet("background-color: #0e1013; color: #d1d4dc;")

            # Left panel
            self.left_text = QPlainTextEdit()
            self.left_text.setReadOnly(True)
            self.left_text.setStyleSheet("background-color: #0e1013; color: #d1d4dc;")

            left_frame = QFrame()
            left_layout = QVBoxLayout()
            left_layout.setContentsMargins(8, 8, 8, 8)
            left_layout.addWidget(QLabel("Bots / Status"))
            left_layout.addWidget(self.left_text, 1)
            left_frame.setLayout(left_layout)
            left_frame.setFixedWidth(320)

            # Center chart
            self.chart = ChartWidget()

            # Right panel tabs
            self.tabs = QTabWidget()
            self.tabs.setStyleSheet("background-color: #0e1013; color: #d1d4dc;")

            self.signals_text = QPlainTextEdit()
            self.signals_text.setReadOnly(True)
            self.signals_text.setStyleSheet("background-color: #0e1013; color: #d1d4dc;")

            self.exec_text = QPlainTextEdit()
            self.exec_text.setReadOnly(True)
            self.exec_text.setStyleSheet("background-color: #0e1013; color: #d1d4dc;")

            self.ops_text = QPlainTextEdit()
            self.ops_text.setReadOnly(True)
            self.ops_text.setStyleSheet("background-color: #0e1013; color: #d1d4dc;")

            self.logs_text = QPlainTextEdit()
            self.logs_text.setReadOnly(True)
            self.logs_text.setStyleSheet("background-color: #0e1013; color: #d1d4dc;")

            self.tabs.addTab(self.signals_text, "Signals")
            self.tabs.addTab(self.exec_text, "Execution")
            self.tabs.addTab(self.ops_text, "Ops")
            self.tabs.addTab(self.logs_text, "Logs")
            self.tabs.setFixedWidth(520)

            root = QWidget()
            layout = QHBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            layout.addWidget(left_frame)
            layout.addWidget(self.chart, 1)
            layout.addWidget(self.tabs)
            root.setLayout(layout)
            self.setCentralWidget(root)

            # Font (touch-friendly)
            font = QFont("DejaVu Sans")
            font.setPointSize(11)
            self.setFont(font)

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
            # State
            state = _read_json(paths.state_json)
            self.left_text.setPlainText(_format_state_summary(state))

            # Signals
            signals = _read_jsonl_tail(paths.signals_jsonl, limit=200)
            self.signals_text.setPlainText(_format_signals(signals))

            # Events / execution / ops
            events = _read_jsonl_tail(paths.events_jsonl, limit=400)
            self.exec_text.setPlainText(_format_events(events))
            self.ops_text.setPlainText(_format_events(events, filter_levels={"error", "warn", "warning"}))

            # Logs
            self.logs_text.setPlainText(_tail_text_file(paths.agent_log, max_lines=250))

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
    win.showFullScreen()
    sys.exit(app.exec())

