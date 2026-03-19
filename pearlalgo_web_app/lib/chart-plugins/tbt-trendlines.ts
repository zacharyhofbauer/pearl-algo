import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

/**
 * TBT [ChartPrime] — Trendline Breakouts With Targets
 *
 * Renders filled channel bands (not just lines) matching the PineScript:
 *  - Bearish (resistance) channel: rgba(212,46,0,0.46) red-orange fill
 *  - Bullish (support) channel:    rgba(11,139,7,0.47) green fill
 *  - Band width based on ATR * 0.3 (volAdj in PineScript)
 *  - Gray fill between middle and lower edge: rgba(109,111,111,0.81)
 */

interface BandPoint { x: number; yTop: number; yMid: number; yBot: number }
interface TrendBand {
  points: BandPoint[]
  fillColor: string     // main fill (top → mid)
  grayFill: string      // secondary fill (mid → bot)
}

class TBTRenderer implements ISeriesPrimitivePaneRenderer {
  private _bands: TrendBand[]
  constructor(bands: TrendBand[]) { this._bands = bands }

  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr  = scope.horizontalPixelRatio
      const prY = scope.verticalPixelRatio

      for (const band of this._bands) {
        if (band.points.length < 2) continue

        // Fill top → mid (main color)
        ctx.save()
        ctx.fillStyle = band.fillColor
        ctx.beginPath()
        ctx.moveTo(band.points[0].x * pr, band.points[0].yTop * prY)
        for (let i = 1; i < band.points.length; i++) {
          ctx.lineTo(band.points[i].x * pr, band.points[i].yTop * prY)
        }
        for (let i = band.points.length - 1; i >= 0; i--) {
          ctx.lineTo(band.points[i].x * pr, band.points[i].yMid * prY)
        }
        ctx.closePath()
        ctx.fill()

        // Fill mid → bot (gray)
        ctx.fillStyle = band.grayFill
        ctx.beginPath()
        ctx.moveTo(band.points[0].x * pr, band.points[0].yMid * prY)
        for (let i = 1; i < band.points.length; i++) {
          ctx.lineTo(band.points[i].x * pr, band.points[i].yMid * prY)
        }
        for (let i = band.points.length - 1; i >= 0; i--) {
          ctx.lineTo(band.points[i].x * pr, band.points[i].yBot * prY)
        }
        ctx.closePath()
        ctx.fill()

        // Edge stroke lines (top, mid, bot) — thin, matching TradingView linefill edges
        ctx.lineWidth = 1 * pr
        ctx.setLineDash([])
        for (const key of ['yTop', 'yMid', 'yBot'] as const) {
          ctx.strokeStyle = key === 'yMid' ? 'rgba(255,255,255,0.08)' : 'rgba(255,255,255,0.04)'
          ctx.beginPath()
          ctx.moveTo(band.points[0].x * pr, band.points[0][key] * prY)
          for (let i = 1; i < band.points.length; i++) {
            ctx.lineTo(band.points[i].x * pr, band.points[i][key] * prY)
          }
          ctx.stroke()
        }
        ctx.restore()
      }
    })
  }
}

class TBTPaneView implements ISeriesPrimitivePaneView {
  private _plugin: TBTTrendlines
  constructor(plugin: TBTTrendlines) { this._plugin = plugin }
  update() {}

  renderer(): ISeriesPrimitivePaneRenderer {
    const chart  = this._plugin._chart
    const series = this._plugin._series
    if (!chart || !series) return new TBTRenderer([])

    const timeScale = chart.timeScale()
    const toX = (t: number): number => (timeScale.timeToCoordinate(t as Time) ?? -9999) as number
    const toY = (p: number): number => (series.priceToCoordinate(p) ?? -9999) as number

    return new TBTRenderer(
      this._plugin._bands.map(b => ({
        points: b.pts.map(p => ({
          x: toX(p.time),
          yTop: toY(p.priceTop),
          yMid: toY(p.priceMid),
          yBot: toY(p.priceBot),
        })),
        fillColor: b.fillColor,
        grayFill:  b.grayFill,
      }))
    )
  }

  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
}

interface Candle { time: number; high: number; low: number; close: number }
interface Pivot  { time: number; price: number }

function pivotHighs(c: Candle[], lb = 5): Pivot[] {
  const out: Pivot[] = []
  for (let i = lb; i < c.length - lb; i++) {
    const h = c[i].high; let ok = true
    for (let j = i - lb; j <= i + lb; j++) if (j !== i && c[j].high >= h) { ok = false; break }
    if (ok) out.push({ time: c[i].time, price: h })
  }
  return out
}

function pivotLows(c: Candle[], lb = 5): Pivot[] {
  const out: Pivot[] = []
  for (let i = lb; i < c.length - lb; i++) {
    const l = c[i].low; let ok = true
    for (let j = i - lb; j <= i + lb; j++) if (j !== i && c[j].low <= l) { ok = false; break }
    if (ok) out.push({ time: c[i].time, price: l })
  }
  return out
}

function extendTo(p1: Pivot, p2: Pivot, toTime: number): number {
  if (p2.time === p1.time) return p2.price
  return p2.price + ((p2.price - p1.price) / (p2.time - p1.time)) * (toTime - p2.time)
}

/** ATR-like half-width: avg(high-low) * 0.3 / 2, matching PineScript volAdj/2 with 20-bar lookback */
function bandWidth(candles: Candle[]): number {
  const slice = candles.slice(-20)
  if (slice.length === 0) return 0
  let sum = 0
  for (const c of slice) sum += c.high - c.low
  return (sum / slice.length) * 0.3 / 2
}

interface InternalBand {
  pts: Array<{ time: number; priceTop: number; priceMid: number; priceBot: number }>
  fillColor: string
  grayFill: string
}

export class TBTTrendlines implements ISeriesPrimitive<Time> {
  _chart:     any
  _series:    any
  _bands:     InternalBand[] = []
  _paneViews: TBTPaneView[]
  private _requestUpdate?: () => void
  private _onDataChanged = () => this._rebuild()

  constructor() { this._paneViews = [new TBTPaneView(this)] }

  attached(p: SeriesAttachedParameter<Time>) {
    this._chart  = (p as any).chart
    this._series = (p as any).series
    this._requestUpdate = (p as any).requestUpdate
    this._series.subscribeDataChanged(this._onDataChanged)
    this._rebuild()
  }

  detached() {
    this._series?.unsubscribeDataChanged(this._onDataChanged)
    this._chart  = undefined
    this._series = undefined
  }

  private _rebuild() {
    const raw: Candle[] = this._series?.data() ?? []
    if (raw.length < 20) { this._bands = []; this._requestUpdate?.(); return }

    const lastTime = raw[raw.length - 1].time
    const barInterval = raw.length >= 2 ? raw[raw.length - 1].time - raw[raw.length - 2].time : 300
    const extendTime = lastTime + 10 * barInterval
    const bw = bandWidth(raw)
    const bands: InternalBand[] = []

    // Resistance band (bearish) — connects pivot highs
    const highs = pivotHighs(raw, 5)
    if (highs.length >= 2) {
      const take = highs.slice(-3)
      const last2 = take.slice(-2)
      const endPrice = extendTo(last2[0], last2[1], extendTime)
      const pts = [...take, { time: extendTime, price: endPrice }]
      bands.push({
        fillColor: 'rgba(212,46,0,0.46)',       // PineScript: color.rgb(212, 46, 0, 54)
        grayFill:  'rgba(109,111,111,0.20)',     // PineScript: color.rgb(109, 111, 111, 19) — subtler
        pts: pts.map(p => ({
          time: p.time,
          priceTop: p.price,
          priceMid: p.price - bw,
          priceBot: p.price - bw * 2,
        })),
      })
    }

    // Support band (bullish) — connects pivot lows
    const lows = pivotLows(raw, 5)
    if (lows.length >= 2) {
      const take = lows.slice(-3)
      const last2 = take.slice(-2)
      const endPrice = extendTo(last2[0], last2[1], extendTime)
      const pts = [...take, { time: extendTime, price: endPrice }]
      bands.push({
        fillColor: 'rgba(11,139,7,0.47)',        // PineScript: color.rgb(11, 139, 7, 53)
        grayFill:  'rgba(109,111,111,0.20)',
        pts: pts.map(p => ({
          time: p.time,
          priceTop: p.price + bw * 2,
          priceMid: p.price + bw,
          priceBot: p.price,
        })),
      })
    }

    this._bands = bands
    this._requestUpdate?.()
  }

  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews() { return this._paneViews }
}
