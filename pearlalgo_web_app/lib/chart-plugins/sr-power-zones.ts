import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

export interface SRPowerZoneData {
  resistance: number
  support: number
  buyPower: number
  sellPower: number
}

class SRPowerRenderer implements ISeriesPrimitivePaneRenderer {
  private _data: SRPowerZoneData | null
  private _toY: (p: number) => number | null
  private _width: number

  constructor(data: SRPowerZoneData | null, toY: (p: number) => number | null, width: number) {
    this._data = data
    this._toY = toY
    this._width = width
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

      // Resistance zone (top) — red fill spanning full width
      const yRes = this._toY(resistance)
      if (yRes !== null) {
        const yTop = Math.max(0, Math.round((yRes - 20) * prY))
        const yBot = Math.min(H, Math.round((yRes + 20) * prY))
        const h = Math.max(1, yBot - yTop)

        // Fill
        ctx.fillStyle = 'rgba(239,83,80,0.12)'
        ctx.fillRect(0, yTop, W, h)

        // Border line
        ctx.strokeStyle = 'rgba(239,83,80,0.6)'
        ctx.lineWidth = Math.round(1 * pr)
        ctx.setLineDash([6 * pr, 4 * pr])
        ctx.beginPath()
        ctx.moveTo(0, Math.round(yRes * prY))
        ctx.lineTo(W, Math.round(yRes * prY))
        ctx.stroke()
        ctx.setLineDash([])

        // Sell Power label
        ctx.font = `bold ${Math.round(11 * pr)}px sans-serif`
        ctx.fillStyle = 'rgba(239,83,80,0.85)'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        ctx.fillText(`Sell Power: ${sellPower}`, Math.round(8 * pr), Math.round(yRes * prY))
      }

      // Support zone (bottom) — green fill spanning full width
      const ySup = this._toY(support)
      if (ySup !== null) {
        const yTop = Math.max(0, Math.round((ySup - 20) * prY))
        const yBot = Math.min(H, Math.round((ySup + 20) * prY))
        const h = Math.max(1, yBot - yTop)

        // Fill
        ctx.fillStyle = 'rgba(38,166,154,0.12)'
        ctx.fillRect(0, yTop, W, h)

        // Border line
        ctx.strokeStyle = 'rgba(38,166,154,0.6)'
        ctx.lineWidth = Math.round(1 * pr)
        ctx.setLineDash([6 * pr, 4 * pr])
        ctx.beginPath()
        ctx.moveTo(0, Math.round(ySup * prY))
        ctx.lineTo(W, Math.round(ySup * prY))
        ctx.stroke()
        ctx.setLineDash([])

        // Buy Power label
        ctx.font = `bold ${Math.round(11 * pr)}px sans-serif`
        ctx.fillStyle = 'rgba(38,166,154,0.85)'
        ctx.textAlign = 'left'
        ctx.textBaseline = 'middle'
        ctx.fillText(`Buy Power: ${buyPower}`, Math.round(8 * pr), Math.round(ySup * prY))
      }
    })
  }
}

class SRPowerPaneView implements ISeriesPrimitivePaneView {
  private _plugin: SRPowerZones
  constructor(plugin: SRPowerZones) { this._plugin = plugin }
  update() {}
  renderer(): ISeriesPrimitivePaneRenderer {
    const chart = this._plugin._chart
    const series = this._plugin._series
    if (!chart || !series) return new SRPowerRenderer(null, () => null, 0)
    const toY = (p: number) => series.priceToCoordinate(p) as number | null
    return new SRPowerRenderer(this._plugin._data, toY, 0)
  }
  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
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
