"""
Composite Bot - multi-scenario, multi-timeframe signal engine.

Goal
- One bot per ticker (via config.symbol).
- Generate candidate signals from multiple sub-strategies (trend, breakout, reversal, BOS).
- Attach explicit, structured reasoning per signal (no decorative output).

Inputs
- market_data["df"]: base timeframe OHLCV (timestamp column or DateTimeIndex)
- Optional: market_data["df_5m"], market_data["df_15m"] for higher timeframe context
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from pearlalgo.strategies.nq_intraday.indicators import get_enabled_indicators
from pearlalgo.strategies.nq_intraday.indicators.base import IndicatorSignal
from pearlalgo.strategies.nq_intraday.mtf_analyzer import MTFAnalyzer
from pearlalgo.utils.logger import logger

from .bot_template import BotConfig, IndicatorSuite, PearlBot, TradeSignal, register_bot


@dataclass
class CompositeIndicatorSuite(IndicatorSuite):
    """
    Minimal suite for backtests.

    CompositeBot does not rely on a single indicator suite; it runs multiple modules.
    For backtesting adapters that expect a suite to return a computed dataframe, return df.
    """

    def calculate_signals(self, df: pd.DataFrame) -> Dict[str, Any]:
        return {"df": df}

    def get_features(self, df: pd.DataFrame) -> Dict[str, float]:
        return {}


class CompositeBot(PearlBot):
    """
    Composite bot that combines multiple scenario engines.

    Scenario sources (Python indicator ports)
    - power_channel: trend + breakouts/pullbacks
    - tbt_chartprime: trendline breakout
    - supply_demand_zones: S/R zone bounces
    - smart_money_divergence: divergence reversals

    Additional scenario
    - BOS: basic swing break on 5m structure
    """

    def __init__(self, config: BotConfig):
        super().__init__(config)
        self._suite = CompositeIndicatorSuite()
        self._mtf = MTFAnalyzer()

        # Indicator modules (configurable)
        indicators_cfg = self.config.parameters.get("indicators", {}) if isinstance(self.config.parameters, dict) else {}
        cfg_for_loader = {"indicators": indicators_cfg} if indicators_cfg else None
        self._indicators = get_enabled_indicators(cfg_for_loader)

        # Timeframes
        tfs = []
        if isinstance(self.config.parameters, dict):
            tfs = list(self.config.parameters.get("timeframes") or [])
        self._timeframes = self._normalize_timeframes([self.config.timeframe] + tfs)

        # Controls
        self._max_candidates = int(self.config.parameters.get("max_candidates", 3) or 3)
        self._require_alignment = bool(self.config.parameters.get("require_mtf_alignment", True))

    @property
    def name(self) -> str:
        return "CompositeBot"

    @property
    def description(self) -> str:
        return "Composite multi-scenario bot: trend, breakout, reversal, BOS across timeframes"

    @property
    def strategy_type(self) -> str:
        return "composite"

    def get_indicator_suite(self) -> IndicatorSuite:
        return self._suite

    def generate_signal_logic(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> Optional[TradeSignal]:
        # CompositeBot uses full market_data (multi-timeframe). This method is not used for live.
        return None

    def analyze(self, market_data: Dict) -> List[TradeSignal]:
        if not self.is_active:
            return []

        df_raw = market_data.get("df")
        if not isinstance(df_raw, pd.DataFrame) or df_raw.empty:
            return []

        backtest_mode = bool(market_data.get("_backtest", False))

        # Market filters + regime filters (reuse base behaviors)
        if not self._passes_market_filters(df_raw):
            return []

        regime_info = None
        if self.config.enable_regime_filtering:
            regime_info = self._detect_market_regime(df_raw)
            if regime_info and regime_info[0].value not in self.config.allowed_regimes:
                return []

        # Timeframe context (best-effort; resampling requires a datetime index)
        df_base = self._ensure_datetime_index(df_raw)
        if df_base is None or df_base.empty:
            # Fallback: run only on raw df without resampling
            return self._analyze_single_df(df_raw, mtf=None, regime_info=regime_info, backtest_mode=backtest_mode)

        df_5m = market_data.get("df_5m") if isinstance(market_data.get("df_5m"), pd.DataFrame) else None
        df_15m = market_data.get("df_15m") if isinstance(market_data.get("df_15m"), pd.DataFrame) else None

        df_5m_idx = self._ensure_datetime_index(df_5m) if df_5m is not None and not df_5m.empty else self._resample(df_base, "5m")
        df_15m_idx = self._ensure_datetime_index(df_15m) if df_15m is not None and not df_15m.empty else self._resample(df_base, "15m")

        mtf = None
        try:
            if df_5m_idx is not None and df_15m_idx is not None and (not df_5m_idx.empty) and (not df_15m_idx.empty):
                mtf = self._mtf.analyze(df_5m_idx, df_15m_idx)
        except Exception as e:
            logger.debug(f"CompositeBot MTF analyze failed: {e}")
            mtf = None

        # Evaluate candidate signals on selected entry timeframes (smallest N timeframes)
        entry_timeframes = self._timeframes[: max(1, min(len(self._timeframes), 3))]
        candidates: List[TradeSignal] = []

        for tf in entry_timeframes:
            df_tf = df_base if tf == self.config.timeframe else self._resample(df_base, tf)
            if df_tf is None or df_tf.empty:
                continue
            candidates.extend(self._analyze_df_for_signals(df_tf, entry_tf=tf, mtf=mtf, regime_info=regime_info))

        # BOS on 5m structure (single candidate)
        if df_5m_idx is not None and not df_5m_idx.empty:
            bos_sig = self._bos_candidate(df_5m_idx, mtf=mtf)
            if bos_sig is not None:
                candidates.append(bos_sig)

        if not candidates:
            return []

        # Rank by confidence and return top-N (default 1)
        candidates = sorted(candidates, key=lambda s: float(s.confidence), reverse=True)
        chosen = candidates[: max(1, self._max_candidates)]

        # Apply risk management + validation + state tracking (skip state tracking in backtests)
        out: List[TradeSignal] = []
        for sig in chosen:
            sig = self._apply_risk_management(sig, df_base, regime_info)
            if not self._validate_signal(sig, regime_info):
                continue

            # Attach regime fields expected by telemetry / downstream formatting.
            if regime_info:
                try:
                    sig.market_regime = str(getattr(regime_info[0], "value", "") or "")
                except Exception:
                    sig.market_regime = None
                try:
                    sig.regime_confidence = float(regime_info[2] or 0.0)
                except Exception:
                    sig.regime_confidence = 0.0
                # Keep default regime_adjusted_confidence = 0 unless you add explicit boosts.

            if not backtest_mode:
                self.active_signals.append(sig)
                self.signal_history.append(sig)
                if self.config.enable_alerts:
                    self._send_alert(sig)
                self.last_analysis_time = datetime.now(timezone.utc)

            out.append(sig)

        return out

    def _analyze_single_df(
        self,
        df: pd.DataFrame,
        *,
        mtf: Optional[Dict[str, Any]],
        regime_info: Optional[tuple],
        backtest_mode: bool,
    ) -> List[TradeSignal]:
        # No resampling possible; run indicators on the provided dataframe only.
        candidates = self._analyze_df_for_signals(df, entry_tf=self.config.timeframe, mtf=mtf, regime_info=regime_info)
        if not candidates:
            return []
        candidates = sorted(candidates, key=lambda s: float(s.confidence), reverse=True)
        chosen = candidates[: max(1, self._max_candidates)]
        out: List[TradeSignal] = []
        for sig in chosen:
            sig = self._apply_risk_management(sig, df, regime_info)
            if not self._validate_signal(sig, regime_info):
                continue
            if not backtest_mode:
                self.active_signals.append(sig)
                self.signal_history.append(sig)
                if self.config.enable_alerts:
                    self._send_alert(sig)
                self.last_analysis_time = datetime.now(timezone.utc)
            out.append(sig)
        return out

    def _analyze_df_for_signals(
        self,
        df: pd.DataFrame,
        *,
        entry_tf: str,
        mtf: Optional[Dict[str, Any]],
        regime_info: Optional[tuple],
    ) -> List[TradeSignal]:
        df_work = df.copy()
        df_work.columns = [c.lower() for c in df_work.columns]

        atr = self._atr(df_work, period=14)
        latest = df_work.iloc[-1]

        features: Dict[str, float] = {}
        indicator_signals: List[tuple[str, IndicatorSignal]] = []

        for ind in self._indicators:
            try:
                df_work = ind.calculate(df_work)
                latest = df_work.iloc[-1]
                ind_feats = ind.as_features(latest, df_work)
                for k, v in (ind_feats or {}).items():
                    try:
                        features[k] = float(v)
                    except Exception:
                        continue

                sig = ind.generate_signal(latest, df_work, atr=atr)
                if sig is not None:
                    indicator_signals.append((ind.name, sig))
            except Exception as e:
                logger.debug(f"CompositeBot indicator failed: {getattr(ind, 'name', type(ind).__name__)}: {e}")
                continue

        out: List[TradeSignal] = []
        for ind_name, ind_sig in indicator_signals:
            out.append(
                self._to_trade_signal(
                    ind_name=ind_name,
                    ind_sig=ind_sig,
                    entry_tf=entry_tf,
                    mtf=mtf,
                    features=features,
                )
            )

        return self._apply_alignment_rules(out, mtf=mtf)

    def _apply_alignment_rules(self, signals: List[TradeSignal], *, mtf: Optional[Dict[str, Any]]) -> List[TradeSignal]:
        if not signals:
            return []
        if not mtf:
            return signals

        align = str(mtf.get("alignment", "") or "")
        score = float(mtf.get("alignment_score", 0.0) or 0.0)
        tf5 = (mtf.get("5m") or {}) if isinstance(mtf.get("5m"), dict) else {}
        tf15 = (mtf.get("15m") or {}) if isinstance(mtf.get("15m"), dict) else {}

        trend5 = str(tf5.get("trend", "") or "")
        trend15 = str(tf15.get("trend", "") or "")

        def _trend_dir(trend: str) -> int:
            t = trend.lower()
            if t == "bullish":
                return 1
            if t == "bearish":
                return -1
            return 0

        d5 = _trend_dir(trend5)
        d15 = _trend_dir(trend15)

        out: List[TradeSignal] = []
        for s in signals:
            d = 1 if s.direction == "long" else -1

            # Alignment gating
            if self._require_alignment and align == "conflicting" and (d5 * d < 0 or d15 * d < 0):
                continue

            # Soft scaling by alignment score
            scale = 0.5 + 0.5 * max(0.0, min(score, 1.0))
            s.confidence = float(max(0.0, min(1.0, float(s.confidence) * scale)))

            # Add alignment context into reason (append, deterministic)
            s.reason = (
                f"{s.reason}\n"
                f"MTF alignment: {align} score={score:.2f}\n"
                f"5m trend: {trend5} 15m trend: {trend15}"
            )
            out.append(s)

        return out

    def _bos_candidate(self, df_5m: pd.DataFrame, *, mtf: Optional[Dict[str, Any]]) -> Optional[TradeSignal]:
        df = df_5m.copy()
        df.columns = [c.lower() for c in df.columns]
        if len(df) < 15:
            return None

        close = float(df["close"].iloc[-1])
        prev_high = float(df["high"].iloc[-11:-1].max())
        prev_low = float(df["low"].iloc[-11:-1].min())

        atr = self._atr(df, period=14)
        if atr <= 0:
            atr = close * 0.005

        if close > prev_high:
            direction = "long"
            entry = close
            stop = prev_high - atr
            take = entry + atr * 2.5
            conf = 0.55
            reason = f"SCENARIO: bos_breakout\nENTRY_TF: 5m\nBreak above prior swing high {prev_high:.2f}"
        elif close < prev_low:
            direction = "short"
            entry = close
            stop = prev_low + atr
            take = entry - atr * 2.5
            conf = 0.55
            reason = f"SCENARIO: bos_breakout\nENTRY_TF: 5m\nBreak below prior swing low {prev_low:.2f}"
        else:
            return None

        sig = TradeSignal(
            direction=direction,
            confidence=conf,
            entry_price=entry,
            stop_loss=stop,
            take_profit=take,
            bot_name=self.name,
            bot_version=self.config.version,
            reason=reason,
            indicators_used=["bos_breakout"],
            features={"bos_prev_high": prev_high, "bos_prev_low": prev_low},
        )
        return sig

    def _to_trade_signal(
        self,
        *,
        ind_name: str,
        ind_sig: IndicatorSignal,
        entry_tf: str,
        mtf: Optional[Dict[str, Any]],
        features: Dict[str, float],
    ) -> TradeSignal:
        # Compose deterministic reasoning text (no decorative output)
        reason_lines = [
            f"SCENARIO: {ind_sig.type}",
            f"ENTRY_TF: {entry_tf}",
            f"MODULE: {ind_name}",
            f"TRIGGER: {ind_sig.reason}",
        ]

        # Attach minimal MTF summary if present
        if mtf and isinstance(mtf.get("alignment"), str):
            reason_lines.append(f"MTF alignment: {mtf.get('alignment')} score={float(mtf.get('alignment_score', 0.0) or 0.0):.2f}")

        md = ind_sig.metadata or {}
        md_flat: Dict[str, Any] = {}
        if isinstance(md, dict):
            md_flat = md

        feat_out: Dict[str, Any] = dict(features)
        entry_tf_min = self._tf_to_minutes(entry_tf)
        if entry_tf_min is not None:
            feat_out["entry_tf_min"] = float(entry_tf_min)
        if mtf and isinstance(mtf.get("alignment_score"), (int, float)):
            feat_out["mtf_alignment_score"] = float(mtf.get("alignment_score") or 0.0)
        for k, v in md_flat.items():
            try:
                feat_out[f"{ind_name}.{k}"] = float(v)
            except Exception:
                continue

        return TradeSignal(
            direction=str(ind_sig.direction),
            confidence=float(ind_sig.confidence),
            entry_price=float(ind_sig.entry_price),
            stop_loss=float(ind_sig.stop_loss),
            take_profit=float(ind_sig.take_profit),
            bot_name=self.name,
            bot_version=self.config.version,
            reason="\n".join(reason_lines),
            indicators_used=[ind_name, ind_sig.type],
            features=feat_out,
        )

    def _ensure_datetime_index(self, df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
        if df is None or df.empty:
            return None
        out = df.copy()
        out.columns = [c.lower() for c in out.columns]

        if isinstance(out.index, pd.DatetimeIndex):
            return out.sort_index()

        if "timestamp" in out.columns:
            ts = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
            out = out.assign(timestamp=ts).dropna(subset=["timestamp"]).set_index("timestamp")
            return out.sort_index()

        return None

    def _resample(self, df: pd.DataFrame, timeframe: str) -> Optional[pd.DataFrame]:
        if df is None or df.empty:
            return None
        if not isinstance(df.index, pd.DatetimeIndex):
            return None

        rule = self._normalize_resample_rule(timeframe)
        if rule == "1min":
            return df

        agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
        if "volume" in df.columns:
            agg["volume"] = "sum"

        try:
            return df.resample(rule).agg(agg).dropna()
        except Exception:
            return None

    def _normalize_resample_rule(self, timeframe: str) -> str:
        tf = (timeframe or "").strip().lower()
        if tf in {"1m", "1min", "1minute"}:
            return "1min"
        if tf.endswith("m") and tf[:-1].isdigit():
            return f"{int(tf[:-1])}min"
        if tf.endswith("h") and tf[:-1].isdigit():
            return f"{int(tf[:-1])}H"
        if tf in {"1d", "1day", "d"}:
            return "1D"
        return tf

    def _tf_to_minutes(self, timeframe: str) -> Optional[int]:
        tf = (timeframe or "").strip().lower()
        if tf.endswith("m") and tf[:-1].isdigit():
            return int(tf[:-1])
        if tf.endswith("h") and tf[:-1].isdigit():
            return int(tf[:-1]) * 60
        if tf.endswith("d") and tf[:-1].isdigit():
            return int(tf[:-1]) * 24 * 60
        if tf in {"1d", "d"}:
            return 24 * 60
        return None

    def _normalize_timeframes(self, tfs: List[str]) -> List[str]:
        seen: set[str] = set()
        out: List[tuple[int, str]] = []
        for tf in tfs:
            t = str(tf or "").strip()
            if not t:
                continue
            key = t.lower()
            if key in seen:
                continue
            seen.add(key)
            minutes = self._tf_to_minutes(key) or 10_000_000
            out.append((minutes, key))
        out.sort(key=lambda x: x[0])
        return [t for _, t in out]

    def _atr(self, df: pd.DataFrame, period: int = 14) -> float:
        try:
            high = pd.to_numeric(df["high"], errors="coerce")
            low = pd.to_numeric(df["low"], errors="coerce")
            close = pd.to_numeric(df["close"], errors="coerce")
            tr1 = high - low
            tr2 = (high - close.shift(1)).abs()
            tr3 = (low - close.shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(window=period).mean().iloc[-1]
            if pd.isna(atr):
                return 0.0
            return float(atr)
        except Exception:
            return 0.0


class PearlAutoBot(CompositeBot):
    """
    PearlAutoBot - canonical all-in-one AutoBot.

    This preserves CompositeBot behavior while standardizing naming.
    """

    @property
    def name(self) -> str:
        return "PearlAutoBot"

    @property
    def description(self) -> str:
        return "PearlAutoBot: all-in-one composite bot with multi-scenario logic"


register_bot(CompositeBot)
register_bot(PearlAutoBot)

