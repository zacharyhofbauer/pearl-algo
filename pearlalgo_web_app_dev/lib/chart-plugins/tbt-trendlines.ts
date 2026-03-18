import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

interface LinePoint { x: number; y: number }
interface TrendLine { points: LinePoint[]; color: string; width: number }

class TBTRenderer implements ISeriesPrimitivePaneRenderer {
  private _lines: TrendLine[]
  constructor(lines: TrendLine[]) { this._lines = lines }

  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr  = scope.horizontalPixelRatio
      const prY = scope.verticalPixelRatio
      const W   = scope.bitmapSize.width
      const H   = scope.bitmapSize.height

      for (const line of this._lines) {
        if (line.points.length < 2) continue
        // Skip bounds check — let lines draw even if start is off screen; canvas clips naturally

        ctx.save()
        ctx.strokeStyle = line.color
        ctx.lineWidth   = line.width * pr
        ctx.setLineDash([6 * pr, 4 * pr])
        ctx.lineCap = 'round'
        ctx.beginPath()
        ctx.moveTo(line.points[0].x * pr, line.points[0].y * prY)
        for (let i = 1; i < line.points.length; i++) {
          ctx.lineTo(line.points[i].x * pr, line.points[i].y * prY)
        }
        ctx.stroke()
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
      this._plugin._trendLines.map(tl => ({
        points: tl.pts.map(p => ({ x: toX(p.time), y: toY(p.price) })),
        color:  tl.color,
        width:  tl.width,
      }))
    )
  }

  zOrder(): SeriesPrimitivePaneViewZOrder { return 'normal' }
}

interface Candle { time: number; high: number; low: number }
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

interface InternalTrendLine {
  pts:   Array<{ time: number; price: number }>
  color: string
  width: number
}

export class TBTTrendlines implements ISeriesPrimitive<Time> {
  _chart:      any
  _series:     any
  _trendLines: InternalTrendLine[] = []
  _paneViews:  TBTPaneView[]
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
    if (raw.length < 20) { this._trendLines = []; this._requestUpdate?.(); return }

    const lastTime = raw[raw.length - 1].time
    const barInterval = raw.length >= 2 ? raw[raw.length - 1].time - raw[raw.length - 2].time : 300
    const extendTime = lastTime + 10 * barInterval
    const lines: InternalTrendLine[] = []

    // Resistance — last 3 pivot highs connected, extended 10 bars past last candle
    const highs = pivotHighs(raw, 5)
    if (highs.length >= 2) {
      const take = highs.slice(-3)
      const last2 = take.slice(-2)
      const endPrice = extendTo(last2[0], last2[1], extendTime)
      lines.push({
        color: 'rgba(255,140,0,0.50)',
        width: 1,
        pts: [...take, { time: extendTime, price: endPrice }],
      })
    }

    // Support — last 3 pivot lows connected, extended 10 bars past last candle
    const lows = pivotLows(raw, 5)
    if (lows.length >= 2) {
      const take = lows.slice(-3)
      const last2 = take.slice(-2)
      const endPrice = extendTo(last2[0], last2[1], extendTime)
      lines.push({
        color: 'rgba(38,200,154,0.50)',
        width: 1,
        pts: [...take, { time: extendTime, price: endPrice }],
      })
    }

    this._trendLines = lines
    this._requestUpdate?.()
  }

  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews() { return this._paneViews }
}
