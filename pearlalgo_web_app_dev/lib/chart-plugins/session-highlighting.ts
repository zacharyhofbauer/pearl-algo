import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

interface BarPoint { x: number; color: string }

class SessionRenderer implements ISeriesPrimitivePaneRenderer {
  private _points: BarPoint[]
  private _barWidth: number
  constructor(points: BarPoint[], barWidth: number) {
    this._points = points
    this._barWidth = barWidth
  }
  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr = scope.horizontalPixelRatio
      const hw = (pr * this._barWidth) / 2
      const h  = scope.bitmapSize.height
      const maxX = scope.bitmapSize.width
      for (const p of this._points) {
        const cx = p.x * pr
        if (cx + hw < 0 || cx - hw > maxX) continue
        ctx.fillStyle = p.color
        const left  = Math.max(0, Math.round(cx - hw))
        const right = Math.min(maxX, Math.round(cx + hw))
        ctx.fillRect(left, 0, right - left, h)
      }
    })
  }
}

class SessionPaneView implements ISeriesPrimitivePaneView {
  private _plugin: SessionHighlighting
  constructor(plugin: SessionHighlighting) { this._plugin = plugin }
  update() {}
  renderer(): ISeriesPrimitivePaneRenderer {
    const timeScale = this._plugin._chart!.timeScale()
    const bars      = this._plugin._bars
    const points: BarPoint[] = bars.map(b => ({
      x: (timeScale.timeToCoordinate(b.time) ?? -9999) as number,
      color: b.color,
    }))
    let barWidth = 6
    if (points.length > 2) {
      const deltas: number[] = []
      for (let i = 1; i < points.length; i++) {
        const d = Math.abs(points[i].x - points[i - 1].x)
        if (d > 0) deltas.push(d)
      }
      if (deltas.length > 0) {
        deltas.sort((a, b) => a - b)
        barWidth = deltas[Math.floor(deltas.length / 2)]
      }
    } else if (points.length > 1) {
      barWidth = Math.abs(points[1].x - points[0].x)
    }
    return new SessionRenderer(points, barWidth)
  }
  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
}

function sessionColor(unixSec: number): string {
  const d   = new Date(unixSec * 1000)
  // ET = UTC-5 (EST) or UTC-4 (EDT). Use rough EDT offset for futures hours.
  const etH = (d.getUTCHours() - 4 + 24) % 24
  const etM = d.getUTCMinutes()
  const mins = etH * 60 + etM

  // RTH 09:30–16:15 — subtle navy
  if (mins >= 570 && mins < 975) return 'rgba(15,40,90,0.12)'
  // Pre-market 04:00–09:30 — faint amber
  if (mins >= 240 && mins < 570) return 'rgba(90,45,8,0.09)'
  // Post-market 16:15–18:00 — barely-there brown
  if (mins >= 975 && mins < 1080) return 'rgba(60,30,8,0.06)'
  // Overnight/Asia 18:00–04:00 — muted amber
  return 'rgba(100,55,10,0.12)'
}

interface BarData { time: Time; color: string }

export class SessionHighlighting implements ISeriesPrimitive<Time> {
  _chart:     any
  _series:    any
  _bars:      BarData[] = []
  _paneViews: SessionPaneView[]
  private _requestUpdate?: () => void
  private _onDataChanged = () => this._rebuild()

  constructor() { this._paneViews = [new SessionPaneView(this)] }

  attached(p: SeriesAttachedParameter<Time>) {
    this._chart   = (p as any).chart
    this._series  = (p as any).series
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
    const data = this._series?.data() ?? []
    this._bars = data.map((d: any) => ({
      time:  d.time as Time,
      color: sessionColor(d.time as number),
    }))
    this._requestUpdate?.()
  }

  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews() { return this._paneViews }
}
