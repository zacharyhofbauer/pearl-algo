import {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  SeriesAttachedParameter,
  PrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

export interface Zone {
  topPrice:    number
  bottomPrice: number
  startTime:   number
  endTime:     number
  kind:        'supply' | 'demand'
}

class SDZonesRenderer implements IPrimitivePaneRenderer {
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
      const W    = scope.bitmapSize.width
      const H    = scope.bitmapSize.height

      for (const z of this._zones) {
        const x1raw = this._toX(z.startTime)
        const x2raw = this._toX(z.endTime)
        const y1raw = this._toY(z.topPrice)
        const y2raw = this._toY(z.bottomPrice)

        if (y1raw === null || y2raw === null) continue

        // x: clamp to canvas, allow full width
        const x1 = Math.max(0, Math.round(x1raw * pr))
        const x2 = Math.min(W, Math.round(x2raw * pr))
        if (x2 <= x1) continue

        // y: clamp but allow partial visibility
        const yTop    = Math.min(y1raw, y2raw)
        const yBottom = Math.max(y1raw, y2raw)
        const y1 = Math.max(0, Math.round(yTop    * prY))
        const y2 = Math.min(H, Math.round(yBottom * prY))

        // Draw even if partially off screen — only skip if fully invisible
        if (y2 <= y1 && y1 >= H) continue
        if (y2 <= y1 && y2 <= 0) continue

        const h = Math.max(1, y2 - y1)
        const w = x2 - x1

        if (z.kind === 'demand') {
          // Demand: orange/brown fill — prominent like LuxAlgo
          ctx.fillStyle = 'rgba(180,83,9,0.30)'
          ctx.fillRect(x1, y1, w, h)
          // Top border — thick orange
          ctx.strokeStyle = 'rgba(255,140,0,1.0)'
          ctx.lineWidth = Math.round(3 * pr)
          ctx.setLineDash([])
          ctx.beginPath()
          ctx.moveTo(x1, y1 + Math.round(1.5 * prY))
          ctx.lineTo(x2, y1 + Math.round(1.5 * prY))
          ctx.stroke()
          // Bottom border — thinner
          ctx.strokeStyle = 'rgba(255,140,0,0.5)'
          ctx.lineWidth = Math.round(1 * pr)
          ctx.beginPath()
          ctx.moveTo(x1, y2 - Math.round(0.5 * prY))
          ctx.lineTo(x2, y2 - Math.round(0.5 * prY))
          ctx.stroke()
          // Mid dashed line
          const mid = Math.round((y1 + y2) / 2)
          ctx.strokeStyle = 'rgba(255,140,0,0.35)'
          ctx.setLineDash([6 * pr, 4 * pr])
          ctx.beginPath()
          ctx.moveTo(x1, mid)
          ctx.lineTo(x2, mid)
          ctx.stroke()
          ctx.setLineDash([])
        } else {
          // Supply: red fill
          ctx.fillStyle = 'rgba(239,83,80,0.22)'
          ctx.fillRect(x1, y1, w, h)
          // Bottom border — thick red
          ctx.strokeStyle = 'rgba(239,83,80,1.0)'
          ctx.lineWidth = Math.round(3 * pr)
          ctx.setLineDash([])
          ctx.beginPath()
          ctx.moveTo(x1, y2 - Math.round(1.5 * prY))
          ctx.lineTo(x2, y2 - Math.round(1.5 * prY))
          ctx.stroke()
          // Top border — thinner
          ctx.strokeStyle = 'rgba(239,83,80,0.5)'
          ctx.lineWidth = Math.round(1 * pr)
          ctx.beginPath()
          ctx.moveTo(x1, y1 + Math.round(0.5 * prY))
          ctx.lineTo(x2, y1 + Math.round(0.5 * prY))
          ctx.stroke()
          // Mid dashed line
          const mid = Math.round((y1 + y2) / 2)
          ctx.strokeStyle = 'rgba(239,83,80,0.35)'
          ctx.setLineDash([6 * pr, 4 * pr])
          ctx.beginPath()
          ctx.moveTo(x1, mid)
          ctx.lineTo(x2, mid)
          ctx.stroke()
          ctx.setLineDash([])
        }
      }
    })
  }
}

class SDZonesPaneView implements IPrimitivePaneView {
  private _plugin: SDZones
  constructor(plugin: SDZones) { this._plugin = plugin }
  update() {}
  renderer(): IPrimitivePaneRenderer {
    const chart  = this._plugin._chart
    const series = this._plugin._series
    if (!chart || !series) return new SDZonesRenderer([], () => -1, () => null)
    const timeScale = chart.timeScale()
    const toX = (t: number) => (timeScale.timeToCoordinate(t as Time) ?? -9999) as number
    const toY = (p: number) => series.priceToCoordinate(p) as number | null
    return new SDZonesRenderer(this._plugin._zones, toX, toY)
  }
  zOrder(): PrimitivePaneViewZOrder { return 'bottom' }
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

const MAX_SUPPLY = 1
const MAX_DEMAND = 1
const MIN_ZONE_HEIGHT = 8

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

    const zh = Math.min(Math.max(atr(raw) * 0.4, MIN_ZONE_HEIGHT), 20)
    if (zh <= 0) { this._zones = []; this._requestUpdate?.(); return }

    const barInterval = raw.length >= 2 ? raw[raw.length - 1].time - raw[raw.length - 2].time : 300
    const zoneEndTime = endTime + 2 * barInterval

    const supply = pivotHighs(raw, 7)
      .filter(p => p.price > current)
      .sort((a, b) => Math.abs(a.price - current) - Math.abs(b.price - current))
      .slice(0, MAX_SUPPLY)
      .map(p => ({
        topPrice:    p.price + zh * 0.15,
        bottomPrice: p.price - zh * 0.85,
        startTime,
        endTime: zoneEndTime,
        kind: 'supply' as const,
      }))

    const demand = pivotLows(raw, 7)
      .filter(p => p.price < current)
      .sort((a, b) => Math.abs(a.price - current) - Math.abs(b.price - current))
      .slice(0, MAX_DEMAND)
      .map(p => ({
        topPrice:    p.price + zh * 0.85,
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
