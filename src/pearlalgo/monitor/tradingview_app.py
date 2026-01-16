from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def run_tradingview_app() -> None:
    # Preflight: pick a sane Qt platform and fail fast if no GUI session exists.
    if "QT_QPA_PLATFORM" not in os.environ:
        if os.environ.get("WAYLAND_DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "wayland"
        elif os.environ.get("DISPLAY"):
            os.environ["QT_QPA_PLATFORM"] = "xcb"

    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("No GUI session detected (DISPLAY/WAYLAND_DISPLAY not set).")
        print("Run from the desktop session (local/VNC), not a headless shell.")
        raise SystemExit(1)

    try:
        from PyQt6.QtCore import QUrl, Qt
        from PyQt6.QtGui import QGuiApplication, QIcon
        from PyQt6.QtWidgets import QApplication, QMainWindow, QMessageBox
        from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except Exception:
        print("PyQt6-WebEngine is not installed.")
        print('Install with: pip install -e ".[monitor_tv]"')
        raise

    def load_icon() -> Optional[QIcon]:
        candidates = [
            Path(__file__).resolve().parent / "assets" / "pearl.png",
            Path("/home/pearlalgo/pearlLogo.png"),
        ]
        for p in candidates:
            try:
                if p.exists():
                    icon = QIcon(str(p))
                    if not icon.isNull():
                        return icon
            except Exception:
                continue
        return None

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    icon = load_icon()
    if icon is not None:
        app.setWindowIcon(icon)

    # Persistent profile dir so TradingView login/session survives restarts.
    profile_dir = Path(os.path.expanduser("~/.config/pearlalgo-monitor/tradingview_profile"))
    profile_dir.mkdir(parents=True, exist_ok=True)

    profile = QWebEngineProfile("pearlalgo_tradingview", app)
    profile.setPersistentStoragePath(str(profile_dir))
    profile.setCachePath(str(profile_dir / "cache"))
    profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)

    view = QWebEngineView()
    page = QWebEnginePage(profile, view)
    view.setPage(page)

    # Chart-only target (loads your last chart after login).
    view.setUrl(QUrl("https://www.tradingview.com/chart/"))

    win = QMainWindow()
    win.setWindowTitle("TradingView (Pearl Algo)")
    if icon is not None:
        win.setWindowIcon(icon)
    win.setCentralWidget(view)

    def toggle_fullscreen() -> None:
        if win.isFullScreen():
            win.showMaximized()
        else:
            win.showFullScreen()

    def on_esc() -> None:
        if win.isFullScreen():
            win.showMaximized()
        else:
            win.close()

    # Shortcuts (no menus/toolbars).
    from PyQt6.QtGui import QKeySequence, QShortcut  # local import to keep header minimal

    QShortcut(QKeySequence("F11"), win, activated=toggle_fullscreen)
    QShortcut(QKeySequence("Ctrl+R"), win, activated=view.reload)
    QShortcut(QKeySequence("Esc"), win, activated=on_esc)

    def on_load_finished(ok: bool) -> None:
        if ok:
            return
        QMessageBox.warning(
            win,
            "TradingView load failed",
            "TradingView failed to load. Check internet connectivity and try Ctrl+R.",
        )

    view.loadFinished.connect(on_load_finished)  # type: ignore[arg-type]

    # Prefer the 2560×720 touchscreen if present.
    try:
        target = None
        for s in QGuiApplication.screens():
            g = s.geometry()
            if int(g.width()) == 2560 and int(g.height()) == 720:
                target = s
                break
        win.show()  # create window handle
        if target is not None:
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


if __name__ == "__main__":
    run_tradingview_app()

