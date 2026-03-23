import {
  ISeriesPrimitive,
  ISeriesPrimitivePaneView,
  ISeriesPrimitivePaneRenderer,
  SeriesAttachedParameter,
  SeriesPrimitivePaneViewZOrder,
  Time,
} from 'lightweight-charts'

/**
 * Key Levels plugin — renders horizontal price lines BEHIND candles
 * using the 'bottom' z-order (same layer as session highlighting).
 *
 * Unlike IPriceLine which always renders on top, this draws via canvas
 * at the lowest z-order so candles and indicators sit above.
 */

export interface KeyLevel {
  price: number
  title: string
  color: string  // rgba string
}

interface PixelLevel {
  y: number
  title: string
  color: string
  rightX: number  // right edge of visible area
}

class KeyLevelsRenderer implements ISeriesPrimitivePaneRenderer {
  private _levels: PixelLevel[]
  constructor(levels: PixelLevel[]) { this._levels = levels }

  draw(target: any) {
    target.useBitmapCoordinateSpace((scope: any) => {
      const ctx: CanvasRenderingContext2D = scope.context
      const pr = scope.horizontalPixelRatio
      const vpr = scope.verticalPixelRatio || pr
      const w = scope.bitmapSize.width

      for (const lv of this._levels) {
        const y = Math.round(lv.y * vpr)
        if (y < 0 || y > scope.bitmapSize.height) continue

        // Dashed horizontal line across full width
        ctx.strokeStyle = lv.color
        ctx.lineWidth = 1 * pr
        ctx.setLineDash([4 * pr, 3 * pr])
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(w, y)
        ctx.stroke()
        ctx.setLineDash([])

        // Label at right side of chart (before the price scale)
        const fontSize = Math.round(10 * vpr)
        ctx.font = `500 ${fontSize}px -apple-system, BlinkMacSystemFont, sans-serif`
        ctx.textAlign = 'right'
        ctx.textBaseline = 'middle'
        ctx.fillStyle = lv.color
        ctx.fillText(lv.title, w - Math.round(4 * pr), y - Math.round(6 * vpr))
        ctx.textAlign = 'left'
      }
    })
  }
}

class KeyLevelsPaneView implements ISeriesPrimitivePaneView {
  private _plugin: KeyLevelsPlugin
  constructor(plugin: KeyLevelsPlugin) { this._plugin = plugin }
  update() {}

  renderer(): ISeriesPrimitivePaneRenderer {
    const series = this._plugin._series
    if (!series) return new KeyLevelsRenderer([])

    const pixelLevels: PixelLevel[] = []
    for (const lv of this._plugin._levels) {
      const y = series.priceToCoordinate(lv.price)
      if (y === null) continue
      pixelLevels.push({
        y: y as number,
        title: lv.title,
        color: lv.color,
        rightX: 0,
      })
    }

    return new KeyLevelsRenderer(pixelLevels)
  }

  zOrder(): SeriesPrimitivePaneViewZOrder { return 'bottom' }
}

export class KeyLevelsPlugin implements ISeriesPrimitive<Time> {
  _chart: any
  _series: any
  _levels: KeyLevel[] = []
  _paneViews: KeyLevelsPaneView[]
  private _requestUpdate?: () => void

  constructor() { this._paneViews = [new KeyLevelsPaneView(this)] }

  attached(p: SeriesAttachedParameter<Time>) {
    this._chart = (p as any).chart
    this._series = (p as any).series
    this._requestUpdate = (p as any).requestUpdate
  }

  detached() {
    this._chart = undefined
    this._series = undefined
  }

  setLevels(levels: KeyLevel[]) {
    this._levels = levels
    this._requestUpdate?.()
  }

  updateAllViews() { this._paneViews.forEach(v => v.update()) }
  paneViews() { return this._paneViews }
}
