from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from pearlalgo.utils.logger import logger


def write_interactive_backtest_html(
    report_dir: Path,
    *,
    symbol: str,
    decision_timeframe: str,
    ohlcv_data: pd.DataFrame,
    trades: Optional[List[Dict[str, Any]]] = None,
    signals: Optional[List[Dict[str, Any]]] = None,
    metrics: Optional[Dict[str, Any]] = None,
    output_name: str = "interactive.html",
) -> Path:
    """
    Write a TradingView-like interactive HTML artifact (Lightweight Charts).

    The output is a single HTML file that can be opened on desktop (or any browser)
    and shared over Telegram as a document.
    """
    report_dir.mkdir(parents=True, exist_ok=True)
    out_path = report_dir / output_name

    df = ohlcv_data.copy()

    # Ensure DateTimeIndex
    if not isinstance(df.index, pd.DatetimeIndex):
        for col in ("timestamp", "time", "datetime", "date"):
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], utc=True, errors="coerce")
                df = df.dropna(subset=[col]).set_index(col)
                break

    if not isinstance(df.index, pd.DatetimeIndex) or df.empty:
        raise ValueError("ohlcv_data must have a DatetimeIndex (or a timestamp column) and be non-empty")

    df = df.sort_index()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")

    def _col(name: str) -> str:
        if name in df.columns:
            return name
        alt = name.capitalize()
        if alt in df.columns:
            return alt
        raise KeyError(name)

    open_c = _col("open")
    high_c = _col("high")
    low_c = _col("low")
    close_c = _col("close")
    vol_c = "volume" if "volume" in df.columns else ("Volume" if "Volume" in df.columns else None)

    # Hard cap for HTML size. If caller passed massive data, downsample defensively.
    effective_tf = "native"
    try:
        if len(df) > 250_000:
            agg = {open_c: "first", high_c: "max", low_c: "min", close_c: "last"}
            if vol_c:
                agg[vol_c] = "sum"
            df = df.resample("5min").agg(agg).dropna()
            effective_tf = "5m"
        if len(df) > 350_000:
            agg = {open_c: "first", high_c: "max", low_c: "min", close_c: "last"}
            if vol_c:
                agg[vol_c] = "sum"
            df = df.resample("15min").agg(agg).dropna()
            effective_tf = "15m"
    except Exception:
        # If resample fails for any reason, proceed with original df (best-effort).
        effective_tf = "native"

    idx = df.index
    times = (idx.view("int64") // 1_000_000_000).astype("int64")
    opens = df[open_c].astype("float64").to_numpy()
    highs = df[high_c].astype("float64").to_numpy()
    lows = df[low_c].astype("float64").to_numpy()
    closes = df[close_c].astype("float64").to_numpy()
    if vol_c:
        vols = df[vol_c].fillna(0).astype("float64").to_numpy()
    else:
        vols = np.zeros(len(df), dtype="float64")

    bars = [
        {
            "time": int(t),
            "open": float(o),
            "high": float(h),
            "low": float(l),
            "close": float(c),
            "volume": float(v),
        }
        for t, o, h, l, c, v in zip(times, opens, highs, lows, closes, vols)
    ]

    def _nearest_bar_epoch(ts_raw: Any) -> Optional[int]:
        if not ts_raw:
            return None
        try:
            ts = pd.to_datetime(ts_raw, utc=True, errors="coerce")
        except Exception:
            ts = pd.NaT
        if ts is pd.NaT or ts is None:
            return None
        try:
            loc = idx.get_indexer([ts], method="nearest")[0]
            if loc < 0:
                return None
            return int(idx[loc].timestamp())
        except Exception:
            return None

    markers: List[Dict[str, Any]] = []
    trades = trades or []
    signals = signals or []

    if trades:
        for t in trades:
            direction = (t.get("direction") or "long").lower()
            pnl = t.get("pnl")
            entry_epoch = _nearest_bar_epoch(t.get("entry_time") or t.get("timestamp"))
            exit_epoch = _nearest_bar_epoch(t.get("exit_time"))

            if entry_epoch:
                is_long = direction == "long"
                markers.append(
                    {
                        "time": entry_epoch,
                        "position": "belowBar" if is_long else "aboveBar",
                        "color": "#26a69a" if is_long else "#ef5350",
                        "shape": "arrowUp" if is_long else "arrowDown",
                        "text": "E",
                    }
                )
            if exit_epoch:
                try:
                    pnl_f = float(pnl) if pnl is not None else None
                except Exception:
                    pnl_f = None
                is_win = (pnl_f or 0.0) >= 0.0
                markers.append(
                    {
                        "time": exit_epoch,
                        "position": "aboveBar" if direction == "long" else "belowBar",
                        "color": "#26a69a" if is_win else "#ef5350",
                        "shape": "circle",
                        "text": f"X {pnl_f:+.0f}" if pnl_f is not None else "X",
                    }
                )
    else:
        for s in signals:
            direction = (s.get("direction") or "long").lower()
            ts_epoch = _nearest_bar_epoch(s.get("timestamp"))
            if not ts_epoch:
                continue
            is_long = direction == "long"
            markers.append(
                {
                    "time": ts_epoch,
                    "position": "belowBar" if is_long else "aboveBar",
                    "color": "#26a69a" if is_long else "#ef5350",
                    "shape": "arrowUp" if is_long else "arrowDown",
                    "text": "S",
                }
            )

    try:
        markers = sorted(markers, key=lambda m: int(m.get("time") or 0))
    except Exception:
        pass

    # Compact trade payload for UI (filters + click-to-jump + equity/drawdown)
    trades_compact: List[Dict[str, Any]] = []
    if trades:
        for i, t in enumerate(trades):
            try:
                direction = (t.get("direction") or "long").lower()
                signal_type = str(t.get("signal_type") or t.get("type") or "unknown")
                entry_epoch = _nearest_bar_epoch(t.get("entry_time") or t.get("timestamp"))
                exit_epoch = _nearest_bar_epoch(t.get("exit_time"))
                try:
                    pnl_f = float(t.get("pnl") or 0.0)
                except Exception:
                    pnl_f = 0.0
                try:
                    entry_px = float(t.get("entry_price") or 0.0)
                except Exception:
                    entry_px = 0.0
                try:
                    exit_px = float(t.get("exit_price") or 0.0)
                except Exception:
                    exit_px = 0.0
                trades_compact.append(
                    {
                        "i": int(i),
                        "signal_type": signal_type,
                        "direction": direction,
                        "pnl": float(pnl_f),
                        "entry_time": entry_epoch,
                        "exit_time": exit_epoch,
                        "entry_price": float(entry_px),
                        "exit_price": float(exit_px),
                    }
                )
            except Exception:
                continue

    # Header metrics
    m = metrics or {}
    def _f(key: str, default: float = 0.0) -> float:
        try:
            v = m.get(key, default)
            return float(v) if v is not None else float(default)
        except Exception:
            return float(default)

    summary = {
        "symbol": symbol,
        "decision_timeframe": decision_timeframe,
        "data_timeframe": effective_tf,
        "period_start": idx[0].strftime("%Y-%m-%d"),
        "period_end": idx[-1].strftime("%Y-%m-%d"),
        "total_trades": int(m.get("total_trades", m.get("trades", 0)) or 0),
        "win_rate": _f("win_rate", 0.0),
        "profit_factor": _f("profit_factor", 0.0),
        "total_pnl": _f("total_pnl", 0.0),
        "max_drawdown": _f("max_drawdown", 0.0),
        "sharpe": _f("sharpe_ratio", _f("sharpe", 0.0)),
    }

    # Compact JSON to keep file size down
    try:
        bars_json = json.dumps(bars, separators=(",", ":"))
        markers_json = json.dumps(markers, separators=(",", ":"))
        trades_json = json.dumps(trades_compact, separators=(",", ":"))
        summary_json = json.dumps(summary, separators=(",", ":"))
    except Exception as e:
        logger.warning(f"Could not serialize interactive report data: {e}")
        bars_json = "[]"
        markers_json = "[]"
        trades_json = "[]"
        summary_json = json.dumps(summary, separators=(",", ":"))

    html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Interactive Backtest - __PEARL_SYMBOL__</title>
  <script src="https://unpkg.com/lightweight-charts/dist/lightweight-charts.standalone.production.js"></script>
  <style>
    :root {
      --bg: #0e1013;
      --panel: #111318;
      --grid: #1e2127;
      --text: #d1d4dc;
      --muted: #787b86;
      --blue: #2962ff;
      --green: #26a69a;
      --red: #ef5350;
    }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, system-ui, sans-serif;
      background: var(--bg);
      color: var(--text);
    }
    header {
      padding: 14px 16px;
      border-bottom: 1px solid var(--grid);
      background: linear-gradient(180deg, rgba(17,19,24,0.95), rgba(17,19,24,0.75));
      position: sticky;
      top: 0;
      z-index: 10;
      backdrop-filter: blur(10px);
    }
    .title {
      display: flex;
      align-items: baseline;
      gap: 10px;
      flex-wrap: wrap;
    }
    .title h1 {
      font-size: 16px;
      margin: 0;
      letter-spacing: 0.2px;
    }
    .pill {
      font-size: 12px;
      color: var(--muted);
      border: 1px solid var(--grid);
      padding: 2px 8px;
      border-radius: 999px;
    }
    .stats {
      margin-top: 10px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 10px;
    }
    .stat {
      background: var(--panel);
      border: 1px solid var(--grid);
      border-radius: 10px;
      padding: 10px 12px;
    }
    .stat .k {
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .stat .v {
      font-size: 14px;
      font-weight: 600;
    }
    .v.pos { color: var(--green); }
    .v.neg { color: var(--red); }
    main {
      padding: 0 12px 16px 12px;
    }
    .layout {
      display: grid;
      grid-template-columns: 1fr 360px;
      gap: 12px;
      align-items: start;
      margin-top: 12px;
    }
    .charts {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    #chart, #equity, #drawdown {
      border: 1px solid var(--grid);
      border-radius: 12px;
      overflow: hidden;
      background: transparent;
    }
    #chart { height: 520px; }
    #equity { height: 200px; }
    #drawdown { height: 160px; }
    .sidebar {
      border: 1px solid var(--grid);
      border-radius: 12px;
      background: rgba(17,19,24,0.7);
      padding: 12px;
    }
    .filters {
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
      margin-bottom: 10px;
    }
    .seg {
      border: 1px solid var(--grid);
      background: transparent;
      color: var(--text);
      padding: 6px 10px;
      border-radius: 10px;
      cursor: pointer;
      font-size: 12px;
    }
    .seg.active {
      background: rgba(41,98,255,0.22);
      border-color: var(--blue);
    }
    select {
      border: 1px solid var(--grid);
      background: transparent;
      color: var(--text);
      padding: 6px 10px;
      border-radius: 10px;
      font-size: 12px;
    }
    .selected {
      border: 1px dashed var(--grid);
      border-radius: 10px;
      padding: 10px;
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 12px;
    }
    .trade-list {
      max-height: 620px;
      overflow: auto;
    }
    .trade-row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 8px;
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid transparent;
      cursor: pointer;
    }
    .trade-row:hover {
      background: rgba(255,255,255,0.04);
    }
    .trade-row.selected {
      border-color: var(--blue);
      background: rgba(41,98,255,0.15);
    }
    .trade-main {
      display: flex;
      gap: 8px;
      align-items: baseline;
      flex-wrap: wrap;
    }
    .badge {
      font-size: 11px;
      color: var(--muted);
      border: 1px solid var(--grid);
      padding: 1px 6px;
      border-radius: 999px;
    }
    .pnl.pos { color: var(--green); font-weight: 600; }
    .pnl.neg { color: var(--red); font-weight: 600; }
    .hint {
      color: var(--muted);
      font-size: 12px;
      margin: 2px 4px 0 4px;
    }
    @media (max-width: 900px) {
      .layout { grid-template-columns: 1fr; }
      .trade-list { max-height: 340px; }
    }
  </style>
</head>
<body>
  <header>
    <div class="title">
      <h1>__PEARL_SYMBOL__ Interactive Backtest</h1>
      <span class="pill">__PEARL_DECISION__ decision</span>
      <span class="pill">data __PEARL_DATA_TF__</span>
      <span class="pill">__PEARL_PERIOD_START__ → __PEARL_PERIOD_END__</span>
    </div>
    <div class="stats" id="stats"></div>
  </header>
  <main>
    <div class="layout">
      <div class="charts">
        <div id="chart"></div>
        <div id="equity"></div>
        <div id="drawdown"></div>
        <div class="hint">Tip: click a trade to jump the charts. Markers: E=entry, X=exit.</div>
      </div>
      <aside class="sidebar">
        <div class="filters">
          <button class="seg active" id="flt-all">All</button>
          <button class="seg" id="flt-win">Wins</button>
          <button class="seg" id="flt-loss">Losses</button>
          <select id="flt-type"><option value="all">All types</option></select>
        </div>
        <div class="selected" id="selected">Select a trade to focus the charts.</div>
        <div class="trade-list" id="trade-list"></div>
      </aside>
    </div>
  </main>

  <script>
    const summary = __PEARL_SUMMARY_JSON__;
    const bars = __PEARL_BARS_JSON__;
    const markers = __PEARL_MARKERS_JSON__;
    const trades = __PEARL_TRADES_JSON__;

    function fmtPct(x) {
      const v = (x || 0) * 100;
      return v.toFixed(1) + '%';
    }
    function fmtNum(x, d=2) {
      if (x === null || x === undefined) return 'n/a';
      const v = Number(x);
      if (!isFinite(v)) return 'n/a';
      return v.toFixed(d);
    }
    function fmtUsd(x) {
      const v = Number(x || 0);
      const sign = v >= 0 ? '+' : '';
      return sign + '$' + Math.abs(v).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 });
    }

    // Header stats
    const stats = document.getElementById('stats');
    const items = [
      { k: 'Trades', v: String(summary.total_trades || 0) },
      { k: 'Win rate', v: fmtPct(summary.win_rate) },
      { k: 'Profit factor', v: fmtNum(summary.profit_factor, 2) },
      { k: 'Total P&L', v: fmtUsd(summary.total_pnl), cls: (summary.total_pnl || 0) >= 0 ? 'pos' : 'neg' },
      { k: 'Max DD', v: '$' + Math.abs(summary.max_drawdown || 0).toLocaleString(undefined, { maximumFractionDigits: 2, minimumFractionDigits: 2 }) },
      { k: 'Sharpe', v: fmtNum(summary.sharpe, 2) },
    ];
    stats.innerHTML = items.map(i => `
      <div class="stat">
        <div class="k">${i.k}</div>
        <div class="v ${i.cls || ''}">${i.v}</div>
      </div>
    `).join('');

    const barsStart = bars.length ? bars[0].time : 0;
    const barsEnd = bars.length ? bars[bars.length - 1].time : 0;
    const barSec = (bars.length > 1) ? Math.max(1, Math.round(bars[1].time - bars[0].time)) : 60;

    function baseChartOptions(container, height) {
      return {
        width: container.clientWidth,
        height: height,
        layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#787b86' },
        grid: { vertLines: { color: '#1e2127' }, horzLines: { color: '#1e2127' } },
        crosshair: { mode: LightweightCharts.CrosshairMode.Magnet },
        rightPriceScale: { borderColor: '#2a2e36' },
        timeScale: { borderColor: '#2a2e36', timeVisible: true, secondsVisible: false },
      };
    }

    // Price chart
    const container = document.getElementById('chart');
    const chart = LightweightCharts.createChart(container, baseChartOptions(container, container.clientHeight));
    const candle = chart.addCandlestickSeries({ upColor: '#26a69a', downColor: '#ef5350', borderDownColor: '#ef5350', borderUpColor: '#26a69a', wickDownColor: '#ef5350', wickUpColor: '#26a69a' });
    candle.setData(bars.map(b => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));

    const volume = chart.addHistogramSeries({ color: '#26a69a', priceFormat: { type: 'volume' }, priceScaleId: '', scaleMargins: { top: 0.86, bottom: 0 } });
    volume.setData(bars.map(b => ({ time: b.time, value: b.volume, color: b.close >= b.open ? '#26a69a80' : '#ef535080' })));

    if (markers && markers.length) candle.setMarkers(markers);
    chart.timeScale().fitContent();

    // Equity chart
    const eqEl = document.getElementById('equity');
    const eqChart = LightweightCharts.createChart(eqEl, baseChartOptions(eqEl, eqEl.clientHeight));
    const eqSeries = eqChart.addLineSeries({ color: '#2962ff', lineWidth: 2 });

    // Drawdown chart
    const ddEl = document.getElementById('drawdown');
    const ddChart = LightweightCharts.createChart(ddEl, baseChartOptions(ddEl, ddEl.clientHeight));
    const ddSeries = ddChart.addHistogramSeries({ color: '#ef5350', priceScaleId: 'right', scaleMargins: { top: 0.1, bottom: 0.1 } });

    // Compute equity + drawdown (by trade exit time)
    const tradesSorted = [...trades].filter(t => (t.exit_time || t.entry_time)).sort((a, b) => ((a.exit_time || a.entry_time) - (b.exit_time || b.entry_time)));
    let cum = 0;
    let peak = 0;
    const equity = [];
    const drawdown = [];
    for (const t of tradesSorted) {
      const tt = t.exit_time || t.entry_time;
      cum += Number(t.pnl || 0);
      equity.push({ time: tt, value: cum });
      peak = Math.max(peak, cum);
      const dd = Math.max(0, peak - cum);
      drawdown.push({ time: tt, value: dd, color: dd > 0 ? '#ef535080' : '#26a69a20' });
    }
    eqSeries.setData(equity);
    ddSeries.setData(drawdown);
    eqChart.timeScale().fitContent();
    ddChart.timeScale().fitContent();

    // Trade list UI
    let outcomeFilter = 'all';
    let typeFilter = 'all';
    let selectedTradeId = null;

    const btnAll = document.getElementById('flt-all');
    const btnWin = document.getElementById('flt-win');
    const btnLoss = document.getElementById('flt-loss');
    const selType = document.getElementById('flt-type');
    const tradeList = document.getElementById('trade-list');
    const selected = document.getElementById('selected');

    function setOutcomeFilter(v) {
      outcomeFilter = v;
      btnAll.classList.toggle('active', v === 'all');
      btnWin.classList.toggle('active', v === 'wins');
      btnLoss.classList.toggle('active', v === 'losses');
      renderTrades();
    }

    btnAll.addEventListener('click', () => setOutcomeFilter('all'));
    btnWin.addEventListener('click', () => setOutcomeFilter('wins'));
    btnLoss.addEventListener('click', () => setOutcomeFilter('losses'));
    selType.addEventListener('change', () => { typeFilter = selType.value; renderTrades(); });

    // Populate types
    const types = Array.from(new Set(trades.map(t => t.signal_type || 'unknown'))).sort();
    for (const t of types) {
      const opt = document.createElement('option');
      opt.value = t;
      opt.textContent = t;
      selType.appendChild(opt);
    }

    function passFilters(t) {
      const pnl = Number(t.pnl || 0);
      if (outcomeFilter === 'wins' && pnl <= 0) return false;
      if (outcomeFilter === 'losses' && pnl >= 0) return false;
      if (typeFilter !== 'all' && (t.signal_type || 'unknown') !== typeFilter) return false;
      return true;
    }

    function fmtTime(ts) {
      if (!ts) return 'n/a';
      const d = new Date(ts * 1000);
      return d.toISOString().replace('T', ' ').slice(0, 16);
    }

    function selectTrade(t) {
      selectedTradeId = t.i;
      const pnl = Number(t.pnl || 0);
      const pnlClass = pnl >= 0 ? 'pos' : 'neg';
      selected.innerHTML = `
        <div style="display:flex; justify-content:space-between; gap:10px; flex-wrap:wrap;">
          <div><span class="badge">${t.signal_type || 'unknown'}</span> <span class="badge">${(t.direction || '').toUpperCase()}</span></div>
          <div class="pnl ${pnlClass}">${fmtUsd(pnl)}</div>
        </div>
        <div style="margin-top:8px; line-height:1.4;">
          Entry: ${fmtTime(t.entry_time)} @ ${fmtNum(t.entry_price, 2)}<br/>
          Exit: ${fmtTime(t.exit_time)} @ ${fmtNum(t.exit_price, 2)}
        </div>
      `;
      renderTrades();
      const a = t.entry_time || t.exit_time || barsStart;
      const b = t.exit_time || t.entry_time || barsEnd;
      const from = Math.max(barsStart, a - barSec * 50);
      const to = Math.min(barsEnd, b + barSec * 80);
      if (barsStart && barsEnd) {
        chart.timeScale().setVisibleRange({ from, to });
        eqChart.timeScale().setVisibleRange({ from, to });
        ddChart.timeScale().setVisibleRange({ from, to });
      }
    }

    function renderTrades() {
      const filtered = trades.filter(passFilters);
      if (!filtered.length) {
        tradeList.innerHTML = '<div class="hint">No trades match the filter.</div>';
        return;
      }
      tradeList.innerHTML = filtered.map(t => {
        const pnl = Number(t.pnl || 0);
        const pnlClass = pnl >= 0 ? 'pos' : 'neg';
        const sel = (selectedTradeId === t.i) ? 'selected' : '';
        const dir = (t.direction || '').toUpperCase();
        const st = t.signal_type || 'unknown';
        return `
          <div class="trade-row ${sel}" data-i="${t.i}">
            <div class="trade-main">
              <span class="badge">${st}</span>
              <span class="badge">${dir}</span>
              <span class="badge">${fmtTime(t.exit_time || t.entry_time)}</span>
            </div>
            <div class="pnl ${pnlClass}">${fmtUsd(pnl)}</div>
          </div>
        `;
      }).join('');
      document.querySelectorAll('.trade-row').forEach(el => {
        el.addEventListener('click', () => {
          const id = Number(el.getAttribute('data-i'));
          const t = trades.find(x => x.i === id);
          if (t) selectTrade(t);
        });
      });
    }

    renderTrades();

    // Responsive resize (all charts)
    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
      eqChart.applyOptions({ width: eqEl.clientWidth, height: eqEl.clientHeight });
      ddChart.applyOptions({ width: ddEl.clientWidth, height: ddEl.clientHeight });
    });
    ro.observe(container);
    ro.observe(eqEl);
    ro.observe(ddEl);
  </script>
</body>
</html>
"""

    html = (
        html.replace("__PEARL_SYMBOL__", str(symbol))
        .replace("__PEARL_DECISION__", str(decision_timeframe))
        .replace("__PEARL_DATA_TF__", str(effective_tf))
        .replace("__PEARL_PERIOD_START__", str(summary.get("period_start") or ""))
        .replace("__PEARL_PERIOD_END__", str(summary.get("period_end") or ""))
        .replace("__PEARL_SUMMARY_JSON__", summary_json)
        .replace("__PEARL_BARS_JSON__", bars_json)
        .replace("__PEARL_MARKERS_JSON__", markers_json)
        .replace("__PEARL_TRADES_JSON__", trades_json)
    )

    out_path.write_text(html, encoding="utf-8")
    return out_path


