import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

export interface Zone {
  topPrice:    number
  bottomPrice: number
  startTime:   number
  endTime:     number
  kind:        'supply' | 'demand'
}

class SDZonesRenderer implements ISeriesPrimitivePaneRenderer {
  private _zones: Zone[]
  private _toX: (t: number) => number
  private _toY: (p: number) => number | null

  constructor(zones: Zone[], toX: (t: number) => number, toY: (p: number) => number | null) {
    this._zones = zones
    this._toX   = toX
    this._toY   = toY
  }

  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr   = scope.horizontalPixelRatio
      const prY  = scope.verticalPixelRatio
      const maxX = scope.bitmapSize.width
      const maxY = scope.bitmapSize.height

      for (const z of this._zones) {
        const x1raw = this._toX(z.startTime)
        const x2raw = this._toX(z.endTime)
        const y1raw = this._toY(z.topPrice)
        const y2raw = this._toY(z.bottomPrice)

        if (y1raw === null || y2raw === null) continue

        const x1 = Math.max(0,    Math.round(x1raw * pr))
        const x2 = Math.min(maxX, Math.round(x2raw * pr))
        const y1 = Math.max(0,    Math.round(y1raw * prY))
        const y2 = Math.min(maxY, Math.round(y2raw * prY))

        if (x2 <= x1 || y2 <= y1) continue

        // Fill — subtle semi-transparent
        ctx.fillStyle = z.kind === 'supply'
          ? 'rgba(239,83,80,0.08)'
          : 'rgba(38,166,154,0.08)'
        ctx.fillRect(x1, y1, x2 - x1, y2 - y1)

        // Borders — thin, consistent
        const strongEdge = z.kind === 'supply' ? y1 : y2  // top for supply, bottom for demand
        const weakEdge   = z.kind === 'supply' ? y2 : y1

        // Strong edge: 1px solid
        ctx.lineWidth = Math.round(1 * pr)
        ctx.strokeStyle = z.kind === 'supply'
          ? 'rgba(239,83,80,0.55)' : 'rgba(38,166,154,0.55)'
        ctx.setLineDash([])
        ctx.beginPath()
        ctx.moveTo(x1, strongEdge); ctx.lineTo(x2, strongEdge)
        ctx.stroke()

        // Weak edge: 1px dashed, very subtle
        ctx.strokeStyle = z.kind === 'supply'
          ? 'rgba(239,83,80,0.25)' : 'rgba(38,166,154,0.25)'
        ctx.setLineDash([4 * pr, 4 * pr])
        ctx.beginPath()
        ctx.moveTo(x1, weakEdge); ctx.lineTo(x2, weakEdge)
        ctx.stroke()
        ctx.setLineDash([])
      }
    })
  }
}

class SDZonesPaneView implements ISeriesPrimitivePaneView {
  private _plugin: SDZones
  constructor(plugin: SDZones) { this._plugin = plugin }
  update() {}
  renderer(): ISeriesPrimitivePaneRenderer {
    const chart  = this._plugin._chart
    const series = this._plugin._series
    if (!chart || !series) return new SDZonesRenderer([], () => -1, () => null)
    const timeScale = chart.timeScale()
    const toX = (t: number) => (timeScale.timeToCoordinate(t as Time) ?? -9999) as number
    const toY = (p: number) => series.priceToCoordinate(p) as number | null
    return new SDZonesRenderer(this._plugin._zones, toX, toY)
  }
  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
}

interface Candle { time: number; high: number; low: number; close: number }

function pivotHighs(candles: Candle[], lb = 5): Array<{ time: number; price: number }> {
  const out: Array<{ time: number; price: number }> = []
  for (let i = lb; i < candles.length - lb; i++) {
    const h = candles[i].high
    let ok = true
    for (let j = i - lb; j <= i + lb; j++) {
      if (j !== i && candles[j].high >= h) { ok = false; break }
    }
    if (ok) out.push({ time: candles[i].time, price: h })
  }
  return out
}

function pivotLows(candles: Candle[], lb = 5): Array<{ time: number; price: number }> {
  const out: Array<{ time: number; price: number }> = []
  for (let i = lb; i < candles.length - lb; i++) {
    const l = candles[i].low
    let ok = true
    for (let j = i - lb; j <= i + lb; j++) {
      if (j !== i && candles[j].low <= l) { ok = false; break }
    }
    if (ok) out.push({ time: candles[i].time, price: l })
  }
  return out
}

function atr(candles: Candle[], period = 14): number {
  if (candles.length < 1) return 0
  const slice = candles.slice(-period)
  let sum = 0
  for (let i = 0; i < slice.length; i++) {
    sum += slice[i].high - slice[i].low
  }
  return slice.length > 0 ? sum / slice.length : 0
}

const MAX_ZONES = 2

export class SDZones implements ISeriesPrimitive<Time> {
  _chart:     any
  _series:    any
  _zones:     Zone[] = []
  _paneViews: SDZonesPaneView[]
  private _requestUpdate?: () => void
  private _onDataChanged = () => this._rebuild()

  constructor() { this._paneViews = [new SDZonesPaneView(this)] }

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
    if (raw.length < 15) { this._zones = []; this._requestUpdate?.(); return }

    const current   = raw[raw.length - 1].close
    const endTime   = raw[raw.length - 1].time
    const startTime = raw[0].time

    // Zone height = ATR(14) simple avg(high-low)
    const zh = atr(raw)
    if (zh <= 0) { this._zones = []; this._requestUpdate?.(); return }

    const barInterval = raw.length >= 2 ? raw[raw.length - 1].time - raw[raw.length - 2].time : 300
    const zoneEndTime = endTime + 2 * barInterval

    const supply = pivotHighs(raw, 7)
      .filter(p => p.price > current)
      .sort((a, b) => Math.abs(a.price - current) - Math.abs(b.price - current))
      .slice(0, MAX_ZONES)
      .map(p => ({
        topPrice: p.price + zh * 0.15,
        bottomPrice: p.price - zh * 0.85,
        startTime,
        endTime: zoneEndTime,
        kind: 'supply' as const,
      }))

    const demand = pivotLows(raw, 7)
      .filter(p => p.price < current)
      .sort((a, b) => Math.abs(a.price - current) - Math.abs(b.price - current))
      .slice(0, MAX_ZONES)
      .map(p => ({
        topPrice: p.price + zh * 0.85,
        bottomPrice: p.price - zh * 0.15,
        startTime,
        endTime: zoneEndTime,
        kind: 'demand' as const,
      }))

    this._zones = [...supply, ...demand]
    this._requestUpdate?.()
  }

  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews() { return this._paneViews }
}
