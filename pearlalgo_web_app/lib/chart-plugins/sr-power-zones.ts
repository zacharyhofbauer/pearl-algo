import {
  ISeriesPrimitive,
  IPrimitivePaneView,
  IPrimitivePaneRenderer,
  SeriesAttachedParameter,
  PrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

export interface SRPowerZoneData {
  resistance: number
  support: number
  buyPower: number
  sellPower: number
}

class SRPowerRenderer implements IPrimitivePaneRenderer {
  private _data: SRPowerZoneData | null
  private _toY: (p: number) => number | null

  constructor(data: SRPowerZoneData | null, toY: (p: number) => number | null) {
    this._data = data
    this._toY = toY
  }

  draw(target: any) {
    if (!this._data) return

    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr = scope.horizontalPixelRatio
      const prY = scope.verticalPixelRatio
      const W = scope.bitmapSize.width
      const H = scope.bitmapSize.height

      const { resistance, support, buyPower, sellPower } = this._data!

      // Resistance line — dashed red at top
      const yRes = this._toY(resistance)
      if (yRes !== null) {
        const yPx = Math.round(yRes * prY)
        // Only draw if within canvas bounds (with margin)
        if (yPx > -50 * prY && yPx < H + 50 * prY) {
          // Dashed line
          ctx.strokeStyle = 'rgba(239,83,80,0.5)'
          ctx.lineWidth = Math.round(1 * pr)
          ctx.setLineDash([8 * pr, 4 * pr])
          ctx.beginPath()
          ctx.moveTo(0, yPx)
          ctx.lineTo(W, yPx)
          ctx.stroke()
          ctx.setLineDash([])

          // Label — left side, with background
          const label = `Sell Power: ${sellPower}`
          ctx.font = `${Math.round(10 * pr)}px sans-serif`
          const textW = ctx.measureText(label).width
          const pad = Math.round(4 * pr)
          const labelY = yPx + Math.round(12 * prY)

          ctx.fillStyle = 'rgba(239,83,80,0.15)'
          ctx.fillRect(Math.round(4 * pr), labelY - Math.round(8 * prY), textW + pad * 2, Math.round(14 * prY))
          ctx.fillStyle = 'rgba(239,83,80,0.8)'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillText(label, Math.round(4 * pr) + pad, labelY)
        }
      }

      // Support line — dashed green at bottom
      const ySup = this._toY(support)
      if (ySup !== null) {
        const yPx = Math.round(ySup * prY)
        if (yPx > -50 * prY && yPx < H + 50 * prY) {
          // Dashed line
          ctx.strokeStyle = 'rgba(38,166,154,0.5)'
          ctx.lineWidth = Math.round(1 * pr)
          ctx.setLineDash([8 * pr, 4 * pr])
          ctx.beginPath()
          ctx.moveTo(0, yPx)
          ctx.lineTo(W, yPx)
          ctx.stroke()
          ctx.setLineDash([])

          // Label — left side, with background
          const label = `Buy Power: ${buyPower}`
          ctx.font = `${Math.round(10 * pr)}px sans-serif`
          const textW = ctx.measureText(label).width
          const pad = Math.round(4 * pr)
          const labelY = yPx - Math.round(12 * prY)

          ctx.fillStyle = 'rgba(38,166,154,0.15)'
          ctx.fillRect(Math.round(4 * pr), labelY - Math.round(8 * prY), textW + pad * 2, Math.round(14 * prY))
          ctx.fillStyle = 'rgba(38,166,154,0.8)'
          ctx.textAlign = 'left'
          ctx.textBaseline = 'middle'
          ctx.fillText(label, Math.round(4 * pr) + pad, labelY)
        }
      }
    })
  }
}

class SRPowerPaneView implements IPrimitivePaneView {
  private _plugin: SRPowerZones
  constructor(plugin: SRPowerZones) { this._plugin = plugin }
  update() {}
  renderer(): IPrimitivePaneRenderer {
    const series = this._plugin._series
    if (!series) return new SRPowerRenderer(null, () => null)
    const toY = (p: number) => series.priceToCoordinate(p) as number | null
    return new SRPowerRenderer(this._plugin._data, toY)
  }
  zOrder(): PrimitivePaneViewZOrder { return 'bottom' }
}

export class SRPowerZones implements ISeriesPrimitive<Time> {
  _chart: any
  _series: any
  _data: SRPowerZoneData | null = null
  _paneViews: SRPowerPaneView[]
  private _requestUpdate?: () => void

  constructor() { this._paneViews = [new SRPowerPaneView(this)] }

  attached(p: SeriesAttachedParameter<Time>) {
    this._chart = (p as any).chart
    this._series = (p as any).series
    this._requestUpdate = (p as any).requestUpdate
  }

  detached() {
    this._chart = undefined
    this._series = undefined
  }

  setData(data: SRPowerZoneData | null) {
    this._data = data
    this._requestUpdate?.()
  }

  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews() { return this._paneViews }
}
