/* eslint-disable */
// @ts-nocheck — v4 API types
import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

/**
 * Trading Sessions — matches TradingView Trading Sessions indicator.
 *
 * Features: session box (price-bounded), open/close dashed lines, avg dotted line,
 * range/avg/name text at bottom. Very subtle fill (~8% alpha).
 */

interface SessionSpan {
  startX: number
  endX:   number
  yHigh:  number | null
  yLow:   number | null
  yOpen:  number | null
  yClose: number | null
  yAvg:   number | null
  highPrice: number
  lowPrice:  number
  avgPrice:  number
  fillColor: string
  lineColor: string
  label:     string
}

class SessionRenderer implements ISeriesPrimitivePaneRenderer {
  private _spans: SessionSpan[]
  constructor(spans: SessionSpan[]) { this._spans = spans }

  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr = scope.horizontalPixelRatio
      const prY = scope.verticalPixelRatio
      const maxX = scope.bitmapSize.width
      const maxY = scope.bitmapSize.height

      for (const s of this._spans) {
        const left  = Math.round(s.startX * pr)
        const right = Math.round(s.endX * pr)
        if (right < 0 || left > maxX) continue
        const x1 = Math.max(0, left)
        const x2 = Math.min(maxX, right)
        if (x2 <= x1) continue

        // Session box fill — bounded to price range
        let y1 = 0
        let y2 = maxY
        if (s.yHigh !== null && s.yLow !== null) {
          y1 = Math.max(0, Math.round(Math.min(s.yHigh, s.yLow) * prY))
          y2 = Math.min(maxY, Math.round(Math.max(s.yHigh, s.yLow) * prY))
        }
        if (y2 > y1) {
          ctx.fillStyle = s.fillColor
          ctx.fillRect(x1, y1, x2 - x1, y2 - y1)
        }

        // Session open line (dashed)
        if (s.yOpen !== null) {
          const yPx = Math.round(s.yOpen * prY)
          if (yPx >= 0 && yPx <= maxY) {
            ctx.strokeStyle = s.lineColor
            ctx.lineWidth = Math.round(1 * pr)
            ctx.setLineDash([4 * pr, 3 * pr])
            ctx.beginPath()
            ctx.moveTo(x1, yPx)
            ctx.lineTo(x2, yPx)
            ctx.stroke()
          }
        }

        // Session close line (dashed)
        if (s.yClose !== null) {
          const yPx = Math.round(s.yClose * prY)
          if (yPx >= 0 && yPx <= maxY) {
            ctx.strokeStyle = s.lineColor
            ctx.lineWidth = Math.round(1 * pr)
            ctx.setLineDash([4 * pr, 3 * pr])
            ctx.beginPath()
            ctx.moveTo(x1, yPx)
            ctx.lineTo(x2, yPx)
            ctx.stroke()
          }
        }

        // Average price line (dotted)
        if (s.yAvg !== null) {
          const yPx = Math.round(s.yAvg * prY)
          if (yPx >= 0 && yPx <= maxY) {
            ctx.strokeStyle = s.lineColor
            ctx.lineWidth = Math.round(1 * pr)
            ctx.setLineDash([2 * pr, 2 * pr])
            ctx.beginPath()
            ctx.moveTo(x1, yPx)
            ctx.lineTo(x2, yPx)
            ctx.stroke()
          }
        }

        ctx.setLineDash([])

        // Range, Avg, and Name text — below session box
        const fontSize = Math.round(9 * prY)
        ctx.font = `${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`
        ctx.textAlign = 'left'
        ctx.fillStyle = s.lineColor

        const range = s.highPrice - s.lowPrice
        const textX = x1 + Math.round(6 * pr)
        const bottomY = y2 > y1 ? y2 : maxY
        const lineH = Math.round(13 * prY)

        ctx.fillText(`Range: ${range.toFixed(2)}`, textX, bottomY + lineH)
        ctx.fillText(`Avg: ${s.avgPrice.toFixed(2)}`, textX, bottomY + lineH * 2)
        ctx.fillText(s.label, textX, bottomY + lineH * 3)
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
    const series = this._plugin._series
    if (!chart || !series) return new SessionRenderer([])
    const timeScale = chart.timeScale()
    const toX = (t: number) => (timeScale.timeToCoordinate(t as Time) ?? -9999) as number
    const toY = (p: number) => series.priceToCoordinate(p) as number | null

    const spans: SessionSpan[] = this._plugin._spans.map(s => ({
      startX:    toX(s.startTime),
      endX:      toX(s.endTime),
      yHigh:     s.highPrice !== null ? toY(s.highPrice) : null,
      yLow:      s.lowPrice !== null ? toY(s.lowPrice) : null,
      yOpen:     s.openPrice !== null ? toY(s.openPrice) : null,
      yClose:    s.closePrice !== null ? toY(s.closePrice) : null,
      yAvg:      s.avgPrice !== null ? toY(s.avgPrice) : null,
      highPrice: s.highPrice ?? 0,
      lowPrice:  s.lowPrice ?? 0,
      avgPrice:  s.avgPrice ?? 0,
      fillColor: s.fillColor,
      lineColor: s.lineColor,
      label:     s.label,
    }))

    return new SessionRenderer(spans)
  }

  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
}

interface SessionInfo {
  name: string
  fillColor: string
  lineColor: string
}

function getSession(unixSec: number): SessionInfo | null {
  const d   = new Date(unixSec * 1000)
  const etH = (d.getUTCHours() - 4 + 24) % 24
  const etM = d.getUTCMinutes()
  const mins = etH * 60 + etM

  // New York RTH 09:30–16:00 ET
  if (mins >= 570 && mins < 960) return {
    name: 'New York',
    fillColor: 'rgba(8,153,129,0.08)',
    lineColor: 'rgba(8,153,129,0.35)',
  }
  // London: roughly 03:30–09:30 ET
  if (mins >= 210 && mins < 570) return {
    name: 'London',
    fillColor: 'rgba(255,152,0,0.08)',
    lineColor: 'rgba(255,152,0,0.35)',
  }
  // Tokyo: roughly 19:00–01:00 ET
  if (mins >= 1140 || mins < 60) return {
    name: 'Tokyo',
    fillColor: 'rgba(41,98,255,0.08)',
    lineColor: 'rgba(41,98,255,0.35)',
  }
  return null
}

interface InternalSpan {
  startTime:  number
  endTime:    number
  highPrice:  number | null
  lowPrice:   number | null
  openPrice:  number | null
  closePrice: number | null
  avgPrice:   number | null
  fillColor:  string
  lineColor:  string
  label:      string
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

    const spans: InternalSpan[] = []
    let current: InternalSpan | null = null
    let sumClose = 0
    let barCount = 0

    for (const bar of data) {
      const t = (bar as any).time as number
      const high = (bar as any).high as number
      const low = (bar as any).low as number
      const open = (bar as any).open as number
      const close = (bar as any).close as number
      const session = getSession(t)

      if (session) {
        if (current && current.label === session.name) {
          current.endTime = t + barInterval
          if (current.highPrice === null || high > current.highPrice) current.highPrice = high
          if (current.lowPrice === null || low < current.lowPrice) current.lowPrice = low
          current.closePrice = close
          sumClose += close
          barCount++
          current.avgPrice = sumClose / barCount
        } else {
          if (current) spans.push(current)
          sumClose = close
          barCount = 1
          current = {
            startTime: t,
            endTime: t + barInterval,
            highPrice: high,
            lowPrice: low,
            openPrice: open,
            closePrice: close,
            avgPrice: close,
            fillColor: session.fillColor,
            lineColor: session.lineColor,
            label: session.name,
          }
        }
      } else {
        if (current) {
          spans.push(current)
          current = null
          sumClose = 0
          barCount = 0
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
