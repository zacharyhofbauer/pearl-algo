#!/usr/bin/env python3
"""
Train ML Signal Filter from historical signals.jsonl outcomes.

This is intended for paper-mode gating to reduce drawdown.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pearlalgo.config.config_loader import load_service_config
from pearlalgo.learning.ml_signal_filter import MLFilterConfig, MLSignalFilter


def _parse_iso(dt: Optional[str]) -> Optional[datetime]:
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt.replace("Z", "+00:00"))
    except Exception:
        return None


def _compute_rr(entry: float, stop: float, target: float, direction: str) -> float:
    if entry <= 0 or stop <= 0 or target <= 0:
        return 0.0
    if direction == "short":
        risk = stop - entry
        reward = entry - target
    else:
        risk = entry - stop
        reward = target - entry
    if risk <= 0:
        return 0.0
    return reward / risk


def _build_trade_record(rec: Dict) -> Optional[Dict]:
    if rec.get("status") != "exited":
        return None
    signal = rec.get("signal", {}) or {}
    if not isinstance(signal, dict):
        return None
    signal_type = rec.get("signal_type") or signal.get("type") or signal.get("signal_type")
    if not signal_type:
        return None

    direction = str(signal.get("direction") or rec.get("direction") or "unknown").lower()
    entry = float(signal.get("entry_price") or 0.0)
    stop = float(signal.get("stop_loss") or 0.0)
    target = float(signal.get("take_profit") or 0.0)
    risk_reward = float(signal.get("risk_reward") or _compute_rr(entry, stop, target, direction))

    indicators = signal.get("indicators", {}) or {}
    quality_score = signal.get("quality_score")
    if isinstance(quality_score, dict):
        quality_score_val = float(quality_score.get("quality_score", 0.0) or 0.0)
    else:
        try:
            quality_score_val = float(quality_score or 0.0)
        except Exception:
            quality_score_val = 0.0

    mtf = signal.get("mtf_analysis", {}) or {}
    mtf_alignment_score = 0.0
    try:
        mtf_alignment_score = float(mtf.get("alignment_score", 0.0) or 0.0)
    except Exception:
        mtf_alignment_score = 0.0

    regime = signal.get("regime", {}) if isinstance(signal.get("regime"), dict) else {}
    trade = {
        "signal_type": str(signal_type),
        "is_win": bool(rec.get("is_win", False)),
        "exit_time": rec.get("exit_time"),
        "regime": regime,
        # Core signal features (used by MLSignalFilter)
        "confidence": float(signal.get("confidence") or 0.0),
        "risk_reward": risk_reward,
        "volume_ratio": float(indicators.get("volume_ratio") or 0.0),
        "rsi": float(indicators.get("rsi") or 0.0),
        "atr": float(indicators.get("atr") or 0.0),
        "macd_histogram": float(indicators.get("macd_histogram") or 0.0),
        "mtf_alignment_score": mtf_alignment_score,
        "quality_score": quality_score_val,
        "stop_loss_points": abs(entry - stop) if entry > 0 and stop > 0 else 0.0,
        "target_points": abs(entry - target) if entry > 0 and target > 0 else 0.0,
    }
    return trade


def load_trades(signals_path: Path, signal_type_filter: Optional[str]) -> List[Dict]:
    trades: List[Dict] = []
    with signals_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            trade = _build_trade_record(rec)
            if not trade:
                continue
            if signal_type_filter and trade["signal_type"] != signal_type_filter:
                continue
            trades.append(trade)
    return trades


def main() -> int:
    parser = argparse.ArgumentParser(description="Train ML filter from signals.jsonl")
    parser.add_argument(
        "--signals-path",
        type=Path,
        default=Path("data/nq_agent_state/signals.jsonl"),
        help="Path to signals.jsonl",
    )
    parser.add_argument(
        "--signal-type",
        type=str,
        default="momentum_short",
        help="Signal type to train on (default: momentum_short)",
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        default=Path("models/signal_filter_single.pkl"),
        help="Where to save the trained model",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("reports/ml_filter_training_report.json"),
        help="Where to save training metrics JSON",
    )
    args = parser.parse_args()

    if not args.signals_path.exists():
        raise FileNotFoundError(f"signals.jsonl not found: {args.signals_path}")

    service_cfg = load_service_config(validate=False) or {}
    ml_cfg = MLFilterConfig.from_dict(service_cfg)
    ml_filter = MLSignalFilter(config=ml_cfg)

    trades = load_trades(args.signals_path, args.signal_type)
    metrics = ml_filter.train(trades)

    if metrics.get("status", "").startswith("trained"):
        args.model_path.parent.mkdir(parents=True, exist_ok=True)
        ml_filter.save_model(str(args.model_path))

    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signal_type": args.signal_type,
        "trade_count": len(trades),
        "metrics": metrics,
        "model_path": str(args.model_path),
    }
    args.report_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote training report: {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
