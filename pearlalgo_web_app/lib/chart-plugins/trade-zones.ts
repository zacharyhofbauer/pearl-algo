/**
 * TradeZones — shaded region between entry and SL/TP for active positions.
 *
 * Renders:
 *   - Risk zone (entry → SL): red fill rgba(244,67,54,0.08)
 *   - Reward zone (entry → TP): green fill rgba(76,175,80,0.08)
 *   - Entry line: solid colored horizontal
 *
 * Attach to candleSeries and call setZones() when positions change.
 */

import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

export interface TradeZone {
  entryPrice:  number
  slPrice?:    number
  tpPrice?:    number
  direction:   'long' | 'short'
}

// ─── Renderer ─────────────────────────────────────────────────────────────────

class TradeZonesRenderer implements ISeriesPrimitivePaneRenderer {
  private _zones:  TradeZone[]
  private _toY:    (p: number) => number | null
  private _width:  number

  constructor(zones: TradeZone[], toY: (p: number) => number | null, width: number) {
    this._zones = zones
    this._toY   = toY
    this._width = width
  }

  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const prY  = scope.verticalPixelRatio
      const w    = scope.bitmapSize.width

      for (const z of this._zones) {
        const entryY = this._toY(z.entryPrice)
        if (entryY === null) continue

        // Risk zone (entry → SL)
        if (z.slPrice !== undefined) {
          const slY = this._toY(z.slPrice)
          if (slY !== null) {
            const top    = Math.round(Math.min(entryY, slY) * prY)
            const bottom = Math.round(Math.max(entryY, slY) * prY)
            ctx.fillStyle = 'rgba(244,67,54,0.06)'
            ctx.fillRect(0, top, w, bottom - top)
            // Entry line
            ctx.strokeStyle = z.direction === 'long'
              ? 'rgba(33,150,243,0.7)' : 'rgba(156,39,176,0.7)'
            ctx.lineWidth = 1.5 * scope.horizontalPixelRatio
            ctx.setLineDash([])
            ctx.beginPath()
            ctx.moveTo(0, Math.round(entryY * prY))
            ctx.lineTo(w, Math.round(entryY * prY))
            ctx.stroke()
          }
        }

        // Reward zone (entry → TP)
        if (z.tpPrice !== undefined) {
          const tpY = this._toY(z.tpPrice)
          if (tpY !== null) {
            const top    = Math.round(Math.min(entryY, tpY) * prY)
            const bottom = Math.round(Math.max(entryY, tpY) * prY)
            ctx.fillStyle = 'rgba(76,175,80,0.06)'
            ctx.fillRect(0, top, w, bottom - top)
          }
        }
      }
    })
  }
}

// ─── Pane View ────────────────────────────────────────────────────────────────

class TradeZonesPaneView implements ISeriesPrimitivePaneView {
  private _plugin: TradeZones

  constructor(plugin: TradeZones) { this._plugin = plugin }

  update() {}

  renderer(): ISeriesPrimitivePaneRenderer {
    const series = this._plugin._series
    if (!series) return new TradeZonesRenderer([], () => null, 0)
    const toY = (p: number) => series.priceToCoordinate(p) as number | null
    return new TradeZonesRenderer(this._plugin._zones, toY, 0)
  }

  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
}

// ─── Plugin ───────────────────────────────────────────────────────────────────

export class TradeZones implements ISeriesPrimitive<Time> {
  _series:    any
  _zones:     TradeZone[] = []
  _paneViews: TradeZonesPaneView[]
  private _requestUpdate?: () => void

  constructor() {
    this._paneViews = [new TradeZonesPaneView(this)]
  }

  setZones(zones: TradeZone[]) {
    this._zones = zones
    this._requestUpdate?.()
  }

  attached(p: SeriesAttachedParameter<Time>) {
    this._series        = (p as any).series
    this._requestUpdate = (p as any).requestUpdate
  }

  detached() {
    this._series = undefined
  }

  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews()      { return this._paneViews }
}
