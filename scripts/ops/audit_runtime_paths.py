#!/usr/bin/env python3
"""
Audit PEARL Algo runtime paths without changing any live services.

This script helps answer three operational questions:
1. Which PEARL processes are running right now?
2. Which state directory does each process believe it is using?
3. Which state directories on disk look active, stale, or archived?

It is intentionally read-only so it is safe to run while the trading agent is live.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = PROJECT_ROOT / "data"
NOW_UTC = datetime.now(timezone.utc)


def _extract_option(argv: list[str], flag: str) -> str | None:
    for index, value in enumerate(argv):
        if value == flag and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _read_process_env(pid: int, key: str) -> str | None:
    try:
        payload = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None

    prefix = f"{key}=".encode()
    for item in payload.split(b"\0"):
        if item.startswith(prefix):
            return item[len(prefix):].decode(errors="replace")
    return None


def _detect_process_kind(argv: list[str]) -> str | None:
    joined = " ".join(argv)
    if "pearlalgo.market_agent.main" in joined:
        return "agent"
    if "scripts/pearlalgo_web_app/api_server.py" in joined or "api_server.py" in joined:
        return "api"
    if "next-server" in joined or "server.js" in joined:
        return "web"
    return None


def _resolve_data_dir(data_dir: str | None, cwd: str | None) -> str | None:
    if not data_dir:
        return None
    path = Path(data_dir)
    if path.is_absolute():
        return str(path.resolve())
    if cwd:
        return str((Path(cwd) / path).resolve())
    return str(path)


def collect_processes() -> list[dict[str, Any]]:
    processes: list[dict[str, Any]] = []
    for proc_dir in Path("/proc").iterdir():
        if not proc_dir.name.isdigit():
            continue

        pid = int(proc_dir.name)
        try:
            raw = (proc_dir / "cmdline").read_bytes()
        except OSError:
            continue
        if not raw:
            continue

        argv = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
        kind = _detect_process_kind(argv)
        if kind is None:
            continue

        data_dir = _extract_option(argv, "--data-dir")
        env_state_dir = _read_process_env(pid, "PEARLALGO_STATE_DIR")
        cwd = None
        try:
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cwd = None

        resolved_data_dir = _resolve_data_dir(data_dir, cwd)

        processes.append(
            {
                "pid": pid,
                "kind": kind,
                "cwd": cwd,
                "data_dir": data_dir,
                "resolved_data_dir": resolved_data_dir,
                "env_state_dir": env_state_dir,
                "argv": argv,
            }
        )

    processes.sort(key=lambda item: (item["kind"], item["pid"]))
    return processes


def _load_json_list_count(path: Path) -> int | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, list):
        return len(payload)
    return None


def _inspect_sqlite(path: Path) -> dict[str, Any]:
    summary: dict[str, Any] = {"tables": [], "table_counts": {}}
    if not path.exists():
        return summary

    try:
        conn = sqlite3.connect(path)
    except Exception as exc:
        summary["error"] = str(exc)
        return summary

    try:
        cursor = conn.cursor()
        tables = [
            row[0]
            for row in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        summary["tables"] = tables
        for table in tables:
            try:
                count = cursor.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                summary["table_counts"][table] = count
            except Exception as exc:
                summary["table_counts"][table] = f"error: {exc}"
    finally:
        conn.close()

    return summary


def _file_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    stat = path.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    age_hours = round((NOW_UTC - modified).total_seconds() / 3600, 2)
    return {
        "size_bytes": stat.st_size,
        "modified_utc": modified.isoformat(),
        "age_hours": age_hours,
    }


def _iter_known_state_dirs() -> list[Path]:
    state_dirs: list[Path] = []

    agent_state_root = DATA_ROOT / "agent_state"
    if agent_state_root.exists():
        state_dirs.extend(path for path in agent_state_root.iterdir() if path.is_dir())

    tradovate_paper = DATA_ROOT / "tradovate" / "paper"
    if tradovate_paper.exists():
        state_dirs.append(tradovate_paper)

    archive_root = DATA_ROOT / "archive"
    if archive_root.exists():
        state_dirs.extend(path for path in archive_root.iterdir() if path.is_dir())

    unique_dirs = sorted({path.resolve() for path in state_dirs}, key=lambda path: str(path))
    return unique_dirs


def _classify_state_dir(path: Path) -> str:
    resolved = path.resolve()
    try:
        rel_str = str(resolved.relative_to(DATA_ROOT.resolve()))
    except ValueError:
        try:
            rel_str = str(resolved.relative_to(PROJECT_ROOT))
        except ValueError:
            rel_str = str(resolved)
    name = path.name.lower()
    if rel_str.startswith("archive/"):
        return "archive"
    if "archived" in name:
        return "archived"
    if rel_str == "tradovate/paper":
        return "tradovate-paper"
    if rel_str.startswith("agent_state/"):
        return "agent-state"
    return "other"


def summarize_state_dir(path: Path) -> dict[str, Any]:
    files = {
        name: _file_summary(path / name)
        for name in [
            "state.json",
            "performance.json",
            "trades.db",
            "tradovate_fills.json",
            "signals.jsonl",
            "agent.log",
        ]
    }
    existing_files = {name: info for name, info in files.items() if info is not None}

    last_modified = None
    if existing_files:
        last_modified = max(info["modified_utc"] for info in existing_files.values())

    resolved_path = path.resolve()
    try:
        relative_path = str(resolved_path.relative_to(PROJECT_ROOT))
    except ValueError:
        relative_path = str(resolved_path)

    return {
        "path": str(path),
        "relative_path": relative_path,
        "category": _classify_state_dir(path),
        "files": existing_files,
        "performance_count": _load_json_list_count(path / "performance.json"),
        "fills_count": _load_json_list_count(path / "tradovate_fills.json"),
        "sqlite": _inspect_sqlite(path / "trades.db"),
        "last_modified_utc": last_modified,
    }


def build_report() -> dict[str, Any]:
    processes = collect_processes()
    state_dirs = [summarize_state_dir(path) for path in _iter_known_state_dirs()]

    agent_dirs = {
        proc["resolved_data_dir"]
        for proc in processes
        if proc["kind"] == "agent" and proc["resolved_data_dir"]
    }
    api_dirs = {
        proc["resolved_data_dir"]
        for proc in processes
        if proc["kind"] == "api" and proc["resolved_data_dir"]
    }

    warnings: list[str] = []
    if agent_dirs and api_dirs and agent_dirs != api_dirs:
        warnings.append(
            "Agent and API are using different --data-dir paths."
        )

    for proc in processes:
        if proc["kind"] == "agent" and proc["resolved_data_dir"]:
            live_dir = Path(proc["resolved_data_dir"]).resolve()
            match = next((item for item in state_dirs if Path(item["path"]).resolve() == live_dir), None)
            if match is None:
                warnings.append(f"Live agent data dir is not part of the known state inventory: {live_dir}")
                continue
            tables = set(match["sqlite"].get("tables", []))
            if "trades" not in tables and "trades.db" in match["files"]:
                warnings.append(
                    f"Live agent data dir has trades.db but no trades table: {live_dir}"
                )

    return {
        "generated_at_utc": NOW_UTC.isoformat(),
        "project_root": str(PROJECT_ROOT),
        "processes": processes,
        "state_dirs": state_dirs,
        "warnings": warnings,
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"PEARL Algo Runtime Audit")
    print(f"Generated: {report['generated_at_utc']}")
    print(f"Project root: {report['project_root']}")
    print("")

    print("Processes:")
    if not report["processes"]:
        print("  (none found)")
    for proc in report["processes"]:
        print(
            f"  - {proc['kind']} pid={proc['pid']} data_dir={proc['data_dir'] or '-'} "
            f"resolved_data_dir={proc['resolved_data_dir'] or '-'} "
            f"env_state_dir={proc['env_state_dir'] or '-'}"
        )

    print("")
    print("State directories:")
    for state_dir in report["state_dirs"]:
        sqlite_tables = ",".join(state_dir["sqlite"].get("tables", [])) or "-"
        trades_count = state_dir["sqlite"].get("table_counts", {}).get("trades", "-")
        audit_count = state_dir["sqlite"].get("table_counts", {}).get("audit_events", "-")
        print(
            f"  - {state_dir['relative_path']} [{state_dir['category']}] "
            f"perf={state_dir['performance_count'] if state_dir['performance_count'] is not None else '-'} "
            f"fills={state_dir['fills_count'] if state_dir['fills_count'] is not None else '-'} "
            f"trades={trades_count} audit_events={audit_count} tables={sqlite_tables}"
        )

    print("")
    print("Warnings:")
    if not report["warnings"]:
        print("  (none)")
    for warning in report["warnings"]:
        print(f"  - {warning}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit PEARL Algo runtime paths")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text")
    args = parser.parse_args()

    report = build_report()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
