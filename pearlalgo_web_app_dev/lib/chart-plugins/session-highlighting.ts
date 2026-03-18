import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

/**
 * Trading Sessions — box-per-session rendering matching TradingView indicator.
 *
 * Colors from PineScript (85% transparent = 0.15 alpha):
 *   Tokyo:    #2962FF @ 85  →  rgba(41,98,255,0.15)
 *   London:   #FF9800 @ 85  →  rgba(255,152,0,0.15)
 *   New York: #089981 @ 85  →  rgba(8,153,129,0.15)
 */

interface SessionSpan {
  startX: number
  endX:   number
  color:  string
  label:  string
  labelColor: string
}

class SessionRenderer implements ISeriesPrimitivePaneRenderer {
  private _spans: SessionSpan[]
  constructor(spans: SessionSpan[]) { this._spans = spans }

  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr = scope.horizontalPixelRatio
      const h  = scope.bitmapSize.height
      const maxX = scope.bitmapSize.width

      for (const s of this._spans) {
        const left  = Math.round(s.startX * pr)
        const right = Math.round(s.endX * pr)
        if (right < 0 || left > maxX) continue
        const x1 = Math.max(0, left)
        const x2 = Math.min(maxX, right)
        if (x2 <= x1) continue

        // Session background fill
        ctx.fillStyle = s.color
        ctx.fillRect(x1, 0, x2 - x1, h)

        // Session name label at top
        const fontSize = Math.round(10 * (scope.verticalPixelRatio || 1))
        ctx.font = `500 ${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`
        ctx.textAlign = 'center'
        ctx.textBaseline = 'top'
        ctx.fillStyle = s.labelColor
        const midX = (x1 + x2) / 2
        ctx.fillText(s.label, midX, Math.round(4 * (scope.verticalPixelRatio || 1)))
        ctx.textAlign = 'left'
      }
    })
  }
}

class SessionPaneView implements ISeriesPrimitivePaneView {
  private _plugin: SessionHighlighting
  constructor(plugin: SessionHighlighting) { this._plugin = plugin }
  update() {}

  renderer(): ISeriesPrimitivePaneRenderer {
    const chart = this._plugin._chart
    if (!chart) return new SessionRenderer([])
    const timeScale = chart.timeScale()
    const toX = (t: number) => (timeScale.timeToCoordinate(t as Time) ?? -9999) as number

    // Convert grouped spans to pixel coordinates
    const spans: SessionSpan[] = this._plugin._spans.map(s => ({
      startX: toX(s.startTime),
      endX:   toX(s.endTime),
      color:  s.color,
      label:  s.label,
      labelColor: s.labelColor,
    }))

    return new SessionRenderer(spans)
  }

  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
}

interface SessionInfo {
  name: string
  color: string
  labelColor: string
}

function getSession(unixSec: number): SessionInfo | null {
  const d   = new Date(unixSec * 1000)
  const etH = (d.getUTCHours() - 4 + 24) % 24
  const etM = d.getUTCMinutes()
  const mins = etH * 60 + etM

  // New York RTH 09:30–16:00 ET
  if (mins >= 570 && mins < 960) return {
    name: 'New York',
    color: 'rgba(8,153,129,0.15)',
    labelColor: 'rgba(8,153,129,0.45)',
  }
  // London overlap/pre-NY: roughly 03:30–09:30 ET (London 08:30–14:30 GMT)
  if (mins >= 210 && mins < 570) return {
    name: 'London',
    color: 'rgba(255,152,0,0.15)',
    labelColor: 'rgba(255,152,0,0.45)',
  }
  // Tokyo: roughly 19:00–01:00 ET (Tokyo 09:00–15:00 JST)
  if (mins >= 1140 || mins < 60) return {
    name: 'Tokyo',
    color: 'rgba(41,98,255,0.15)',
    labelColor: 'rgba(41,98,255,0.45)',
  }
  return null
}

interface InternalSpan {
  startTime: number
  endTime:   number
  color:     string
  label:     string
  labelColor: string
}

export class SessionHighlighting implements ISeriesPrimitive<Time> {
  _chart:     any
  _series:    any
  _spans:     InternalSpan[] = []
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
    if (data.length < 2) { this._spans = []; this._requestUpdate?.(); return }

    const barInterval = (data[data.length - 1] as any).time - (data[data.length - 2] as any).time

    // Group consecutive bars into session spans
    const spans: InternalSpan[] = []
    let current: InternalSpan | null = null

    for (const bar of data) {
      const t = (bar as any).time as number
      const session = getSession(t)

      if (session) {
        if (current && current.label === session.name) {
          // Extend current span
          current.endTime = t + barInterval
        } else {
          // Start new span
          if (current) spans.push(current)
          current = {
            startTime: t,
            endTime: t + barInterval,
            color: session.color,
            label: session.name,
            labelColor: session.labelColor,
          }
        }
      } else {
        // Between sessions
        if (current) {
          spans.push(current)
          current = null
        }
      }
    }
    if (current) spans.push(current)

    this._spans = spans
    this._requestUpdate?.()
  }

  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews() { return this._paneViews }
}
