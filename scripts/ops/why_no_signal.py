#!/usr/bin/env python3
# ============================================================================
# Category: Operations/Diagnostics
# Purpose: Answer "why didn't this signal fire?" from the audit trail
# Usage: python3 scripts/ops/why_no_signal.py <subcommand> [options]
# ============================================================================
"""why_no_signal — Phase 1 observability CLI.

Reads ``data/agent_state/<SYMBOL>/signal_audit.jsonl`` and answers:

  * What happened over the last N minutes? (summary)
  * What was the verdict on this specific signal? (signal)
  * What are the most recent decisions? (tail)

Defaults assume the standard layout (``./data/agent_state/MNQ/``) when
run from the repo root; override with ``--state-dir`` to point at a
different location. Remote operation is fine too — ``ssh pearlalgo
'cat ~/projects/pearl-algo/data/agent_state/MNQ/signal_audit.jsonl'``
piped to stdin via ``--stdin`` works identically.

The tool is pure stdlib. No config loading, no import of pearlalgo —
so it runs anywhere Python 3.9+ does.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, TextIO


DEFAULT_STATE_SUBPATH = Path("data") / "agent_state" / "MNQ"
DEFAULT_AUDIT_FILENAME = "signal_audit.jsonl"

# ANSI colors (opt-out with NO_COLOR=1)
_NO_COLOR = False


def _c(code: str, s: str) -> str:
    if _NO_COLOR:
        return s
    return f"\033[{code}m{s}\033[0m"


def green(s: str) -> str:
    return _c("32", s)


def yellow(s: str) -> str:
    return _c("33", s)


def red(s: str) -> str:
    return _c("31", s)


def dim(s: str) -> str:
    return _c("2", s)


def bold(s: str) -> str:
    return _c("1", s)


# ---------------------------------------------------------------------------
# I/O
# ---------------------------------------------------------------------------


def resolve_audit_path(state_dir: Optional[Path], filename: str) -> Path:
    if state_dir is not None:
        return state_dir / filename
    # Best-effort default: repo-relative path
    repo_guess = Path(__file__).resolve().parents[2]
    return repo_guess / DEFAULT_STATE_SUBPATH / filename


def read_records(
    path: Optional[Path] = None,
    fh: Optional[TextIO] = None,
) -> Iterator[Dict[str, Any]]:
    """Yield parsed records from the audit jsonl.

    Pass ``fh`` to read from an already-open stream (e.g. stdin).
    Skips malformed lines silently — the audit log is append-only and
    a partial final line during rotation is normal.
    """
    if fh is not None:
        source: Iterable[str] = fh
    elif path is not None:
        if not path.exists():
            return
        source = open(path, encoding="utf-8")
    else:
        return
    try:
        for line in source:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
    finally:
        if path is not None and hasattr(source, "close"):
            source.close()


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


def _parse_relative_time(spec: str) -> Optional[datetime]:
    """Accept absolute ISO ('2026-04-23T04:30:00Z') or relative ('1h', '30m', '2d')."""
    spec = spec.strip()
    if not spec:
        return None
    # Relative form: <N><unit>
    if spec[-1] in "smhd" and spec[:-1].isdigit():
        n = int(spec[:-1])
        unit = spec[-1]
        delta = {
            "s": timedelta(seconds=n),
            "m": timedelta(minutes=n),
            "h": timedelta(hours=n),
            "d": timedelta(days=n),
        }[unit]
        return datetime.now(timezone.utc) - delta
    # Absolute ISO
    try:
        dt = datetime.fromisoformat(spec.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _record_ts(r: Dict[str, Any]) -> Optional[datetime]:
    raw = r.get("ts")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def filter_records(
    records: Iterable[Dict[str, Any]],
    *,
    since: Optional[datetime] = None,
    gate: Optional[str] = None,
    layer: Optional[str] = None,
    outcome: Optional[str] = None,
    signal_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in records:
        if since is not None:
            ts = _record_ts(r)
            if ts is None or ts < since:
                continue
        if gate is not None and r.get("gate") != gate:
            continue
        if layer is not None and r.get("layer") != layer:
            continue
        if outcome is not None and r.get("outcome") != outcome:
            continue
        if signal_id is not None and r.get("signal_id") != signal_id:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------


def cmd_summary(records: List[Dict[str, Any]], *, window_label: str) -> str:
    if not records:
        return f"{dim(window_label)}: no audit records\n"

    by_outcome: Counter[str] = Counter()
    by_gate: Dict[str, Counter[str]] = defaultdict(Counter)
    by_direction: Counter[str] = Counter()
    by_layer: Counter[str] = Counter()

    for r in records:
        outcome = str(r.get("outcome") or "unknown")
        by_outcome[outcome] += 1
        gate = str(r.get("gate") or "—")
        by_gate[outcome][gate] += 1
        d = r.get("direction")
        if d:
            by_direction[str(d)] += 1
        layer = str(r.get("layer") or "")
        if layer:
            by_layer[layer] += 1

    lines: List[str] = []
    total = len(records)
    lines.append(f"{bold(window_label)}: {total} audit records")

    # Outcome breakdown
    accepted = by_outcome.get("accepted", 0)
    scaled = by_outcome.get("risk_scaled", 0)
    rejected = by_outcome.get("rejected", 0)
    lines.append(f"  {green('✅ accepted')}:   {accepted}")
    lines.append(f"  {yellow('🔻 risk_scaled')}:{scaled}")
    lines.append(f"  {red('❌ rejected')}:   {rejected}")

    if by_direction:
        dir_pairs = ", ".join(f"{k}={v}" for k, v in by_direction.most_common())
        lines.append(f"  {dim('direction:')} {dir_pairs}")

    if by_layer:
        layer_pairs = ", ".join(f"{k}={v}" for k, v in by_layer.most_common())
        lines.append(f"  {dim('layer:')}     {layer_pairs}")

    # Top rejection reasons
    rej_gates = by_gate.get("rejected")
    if rej_gates:
        lines.append("")
        lines.append(f"  {bold('Top rejections:')}")
        for gate, n in rej_gates.most_common(10):
            bar = "█" * min(40, n)
            lines.append(f"    {red(gate.ljust(32))} {str(n).rjust(4)}  {dim(bar)}")

    # Risk-scaled gates
    scale_gates = by_gate.get("risk_scaled")
    if scale_gates:
        lines.append("")
        lines.append(f"  {bold('Risk-scaled by:')}")
        for gate, n in scale_gates.most_common(10):
            lines.append(f"    {yellow(gate.ljust(32))} {str(n).rjust(4)}")

    return "\n".join(lines) + "\n"


def cmd_signal(records: List[Dict[str, Any]], signal_id: str) -> str:
    matches = [r for r in records if r.get("signal_id") == signal_id]
    if not matches:
        return f"{red('no audit records for signal_id={!r}'.format(signal_id))}\n"
    matches.sort(key=lambda r: str(r.get("ts") or ""))
    lines = [bold(f"Signal {signal_id} — {len(matches)} decision(s)")]
    for r in matches:
        ts = str(r.get("ts", "")).replace("+00:00", "Z")
        outcome = str(r.get("outcome", ""))
        layer = str(r.get("layer", ""))
        gate = r.get("gate") or "—"
        if outcome == "accepted":
            tag = green("✅ accepted")
        elif outcome == "risk_scaled":
            tag = yellow(f"🔻 risk_scaled={r.get('risk_scale_applied')}")
        elif outcome == "rejected":
            tag = red("❌ rejected")
        else:
            tag = dim(outcome)
        lines.append(f"  {dim(ts)}  {layer:20s}  gate={gate:28s}  {tag}")
        if r.get("message"):
            lines.append(f"    {dim('message:')} {r.get('message')}")
        if r.get("threshold"):
            lines.append(f"    {dim('threshold:')} {json.dumps(r['threshold'], default=str)}")
        if r.get("actual"):
            lines.append(f"    {dim('actual:')}    {json.dumps(r['actual'], default=str)}")
    return "\n".join(lines) + "\n"


def cmd_tail(records: List[Dict[str, Any]], n: int) -> str:
    if not records:
        return f"{dim('(no records)')}\n"
    tail = records[-n:]
    lines = [bold(f"Last {len(tail)} decision(s)")]
    for r in tail:
        ts = str(r.get("ts", "")).replace("+00:00", "Z")
        direction = r.get("direction") or ""
        conf = r.get("confidence")
        conf_s = f"{conf:.2f}" if isinstance(conf, (int, float)) else "—"
        outcome = str(r.get("outcome", ""))
        layer = str(r.get("layer", ""))
        gate = r.get("gate") or "—"
        sid = str(r.get("signal_id") or "")[:24]
        if outcome == "accepted":
            tag = green("✅")
        elif outcome == "risk_scaled":
            tag = yellow("🔻")
        elif outcome == "rejected":
            tag = red("❌")
        else:
            tag = dim("?")
        lines.append(
            f"  {dim(ts)} {tag} {layer:20s} {gate:28s} "
            f"{direction:5s} conf={conf_s} {dim(sid)}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: Optional[List[str]] = None) -> int:
    global _NO_COLOR
    p = argparse.ArgumentParser(
        description="Query the Phase 1 signal audit trail.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  why_no_signal summary --since 1h
  why_no_signal signal pearlbot_pinescript_1776915732.612687
  why_no_signal tail -n 20 --gate regime_avoidance
  ssh pearlalgo 'cat ~/projects/pearl-algo/data/agent_state/MNQ/signal_audit.jsonl' \\
      | why_no_signal summary --stdin --since 1h
""",
    )
    p.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Path to the agent state dir (default: ./data/agent_state/MNQ)",
    )
    p.add_argument(
        "--file",
        default=DEFAULT_AUDIT_FILENAME,
        help=f"Audit filename inside state-dir (default: {DEFAULT_AUDIT_FILENAME})",
    )
    p.add_argument("--stdin", action="store_true", help="Read records from stdin")
    p.add_argument("--since", help="Only consider records since TIME (ISO or '1h'/'30m'/'2d')")
    p.add_argument("--gate", help="Filter to a specific gate name")
    p.add_argument("--layer", help="Filter to a specific layer")
    p.add_argument(
        "--outcome",
        choices=("accepted", "rejected", "risk_scaled"),
        help="Filter to a specific outcome",
    )
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colors")

    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("summary", help="Counts by outcome and top rejection/scaling gates")

    psig = sub.add_parser("signal", help="Full decision history for one signal_id")
    psig.add_argument("signal_id", help="The signal_id to look up")

    pt = sub.add_parser("tail", help="Print the most recent N decisions")
    pt.add_argument("-n", type=int, default=20, help="How many records to show (default 20)")

    args = p.parse_args(argv)
    if args.no_color or not sys.stdout.isatty():
        _NO_COLOR = True

    since = _parse_relative_time(args.since) if args.since else None
    if args.since and since is None:
        print(f"error: could not parse --since {args.since!r}", file=sys.stderr)
        return 2

    # Load records
    if args.stdin:
        recs_iter = read_records(fh=sys.stdin)
    else:
        path = resolve_audit_path(args.state_dir, args.file)
        if not path.exists():
            print(
                f"{red('error:')} audit file not found: {path}\n"
                f"  (pass --state-dir or --stdin to read from another source)",
                file=sys.stderr,
            )
            return 2
        recs_iter = read_records(path=path)

    records = filter_records(
        recs_iter,
        since=since,
        gate=args.gate,
        layer=args.layer,
        outcome=args.outcome,
        signal_id=getattr(args, "signal_id", None),
    )

    window_label = "last " + args.since if args.since else "all records"

    if args.cmd == "summary":
        sys.stdout.write(cmd_summary(records, window_label=window_label))
    elif args.cmd == "signal":
        sys.stdout.write(cmd_signal(records, args.signal_id))
    elif args.cmd == "tail":
        sys.stdout.write(cmd_tail(records, n=args.n))
    else:
        p.print_help()
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
