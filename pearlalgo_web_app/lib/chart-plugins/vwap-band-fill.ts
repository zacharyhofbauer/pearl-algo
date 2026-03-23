import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
  ISeriesApi,
} from 'lightweight-charts'

/**
 * VWAP Band Fill — draws a 5% opacity polygon between the upper and lower
 * VWAP AA band series, matching TradingView's "Background" fill option.
 */

class BandFillRenderer implements ISeriesPrimitivePaneRenderer {
  private _points: Array<{ x: number; upperY: number; lowerY: number }>
  private _fillColor: string

  constructor(points: Array<{ x: number; upperY: number; lowerY: number }>, fillColor: string) {
    this._points = points
    this._fillColor = fillColor
  }

  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr = scope.horizontalPixelRatio
      const vpr = scope.verticalPixelRatio || pr
      const pts = this._points

      if (pts.length < 2) return

      ctx.fillStyle = this._fillColor
      ctx.beginPath()

      // Trace upper boundary left → right
      ctx.moveTo(Math.round(pts[0].x * pr), Math.round(pts[0].upperY * vpr))
      for (let i = 1; i < pts.length; i++) {
        ctx.lineTo(Math.round(pts[i].x * pr), Math.round(pts[i].upperY * vpr))
      }

      // Trace lower boundary right → left (closing the polygon)
      for (let i = pts.length - 1; i >= 0; i--) {
        ctx.lineTo(Math.round(pts[i].x * pr), Math.round(pts[i].lowerY * vpr))
      }

      ctx.closePath()
      ctx.fill()
    })
  }
}

class BandFillPaneView implements ISeriesPrimitivePaneView {
  private _plugin: VWAPBandFill
  constructor(plugin: VWAPBandFill) { this._plugin = plugin }
  update() {}

  renderer(): ISeriesPrimitivePaneRenderer {
    const chart = this._plugin._chart
    const upperSeries = this._plugin._upperSeries
    const lowerSeries = this._plugin._lowerSeries
    if (!chart || !upperSeries || !lowerSeries) return new BandFillRenderer([], '')

    const timeScale = chart.timeScale()
    const upperData = upperSeries.data() as Array<{ time: Time; value: number }>
    const lowerData = lowerSeries.data() as Array<{ time: Time; value: number }>

    if (upperData.length === 0 || lowerData.length === 0) return new BandFillRenderer([], '')

    // Build a map of lower series by time for O(1) lookup
    const lowerMap = new Map<number, number>()
    for (const d of lowerData) {
      lowerMap.set(d.time as number, d.value)
    }

    const points: Array<{ x: number; upperY: number; lowerY: number }> = []
    for (const d of upperData) {
      const t = d.time as number
      const lowerVal = lowerMap.get(t)
      if (lowerVal === undefined) continue

      const x = timeScale.timeToCoordinate(d.time)
      if (x === null) continue

      const upperY = upperSeries.priceToCoordinate(d.value)
      const lowerY = lowerSeries.priceToCoordinate(lowerVal)
      if (upperY === null || lowerY === null) continue

      points.push({ x: x as number, upperY: upperY as number, lowerY: lowerY as number })
    }

    return new BandFillRenderer(points, this._plugin._fillColor)
  }

  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
}

export class VWAPBandFill implements ISeriesPrimitive<Time> {
  _chart: any
  _series: any
  _upperSeries: ISeriesApi<'Line'> | null = null
  _lowerSeries: ISeriesApi<'Line'> | null = null
  _fillColor: string
  _paneViews: BandFillPaneView[]
  private _requestUpdate?: () => void

  constructor(upperSeries: ISeriesApi<'Line'>, lowerSeries: ISeriesApi<'Line'>, fillColor = 'rgba(76, 175, 80, 0.05)') {
    this._upperSeries = upperSeries
    this._lowerSeries = lowerSeries
    this._fillColor = fillColor
    this._paneViews = [new BandFillPaneView(this)]
  }

  attached(p: SeriesAttachedParameter<Time>) {
    this._chart = (p as any).chart
    this._series = (p as any).series
    this._requestUpdate = (p as any).requestUpdate
    // Re-render when the host series data changes
    this._series?.subscribeDataChanged(() => this._requestUpdate?.())
  }

  detached() {
    this._chart = undefined
    this._series = undefined
  }

  requestUpdate() { this._requestUpdate?.() }
  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews() { return this._paneViews }
}
