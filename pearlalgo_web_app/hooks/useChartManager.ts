import { useEffect, useRef } from 'react'
import { createChart, ColorType, CrosshairMode, IChartApi, ISeriesApi, IPriceLine, TickMarkType } from 'lightweight-charts'
import { SessionHighlighting } from '@/lib/chart-plugins/session-highlighting'
import { SDZones }              from '@/lib/chart-plugins/sd-zones'
import { TradeZones }           from '@/lib/chart-plugins/trade-zones'
import { VWAPBandFill }         from '@/lib/chart-plugins/vwap-band-fill'
import { KeyLevelsPlugin }      from '@/lib/chart-plugins/key-levels'
// TBT Trendlines disabled — tracked as future work on kanban

export interface UseChartManagerOptions {
  containerRef: React.RefObject<HTMLDivElement>
  barSpacing: number
  timeframe: string
  onChartReady?: (chart: IChartApi | null) => void
}

export interface ChartManagerRefs {
  chart: IChartApi | null
  candleSeries: ISeriesApi<'Candlestick'> | null
  volumeSeries: ISeriesApi<'Histogram'> | null
  ema9Series: ISeriesApi<'Line'> | null
  ema21Series: ISeriesApi<'Line'> | null
  vwapSeries: ISeriesApi<'Line'> | null
  positionGuideSeries: ISeriesApi<'Line'> | null
  connectionLine: ISeriesApi<'Line'> | null
  bbUpper: ISeriesApi<'Line'> | null
  bbMiddle: ISeriesApi<'Line'> | null
  bbLower: ISeriesApi<'Line'> | null
  atrUpper: ISeriesApi<'Line'> | null
  atrLower: ISeriesApi<'Line'> | null
  vwapUpper1: ISeriesApi<'Line'> | null
  vwapLower1: ISeriesApi<'Line'> | null
  tradeZones: TradeZones | null
  sessionPlugin: SessionHighlighting | null
  sdZonesPlugin: SDZones | null
  vwapBandFill: VWAPBandFill | null
  keyLevelsPlugin: KeyLevelsPlugin | null
  tbtPlugin: null
  positionPriceLines: IPriceLine[]
  userScrolledAway: boolean
}

function createInitialRefs(): ChartManagerRefs {
  return {
    chart: null,
    candleSeries: null,
    volumeSeries: null,
    ema9Series: null,
    ema21Series: null,
    vwapSeries: null,
    positionGuideSeries: null,
    connectionLine: null,
    bbUpper: null,
    bbMiddle: null,
    bbLower: null,
    atrUpper: null,
    atrLower: null,
    vwapUpper1: null,
    vwapLower1: null,
    tradeZones: null,
    sessionPlugin: null,
    sdZonesPlugin: null,
    vwapBandFill: null,
    keyLevelsPlugin: null,
    tbtPlugin: null,
    positionPriceLines: [],
    userScrolledAway: false,
  }
}

export function useChartManager({ containerRef, barSpacing, timeframe, onChartReady }: UseChartManagerOptions) {
  const refs = useRef<ChartManagerRefs>(createInitialRefs())

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#d1d4dc',
      },
      watermark: { visible: false },
      grid: {
        vertLines: { color: 'rgba(42,46,57,0.3)' },
        horzLines: { color: 'rgba(42,46,57,0.3)' },
      },
      rightPriceScale: {
        borderColor: '#2a2e39',
        textColor: '#787b86',
        scaleMargins: { top: 0.1, bottom: 0.15 },
      },
      timeScale: {
        visible: true,
        borderColor: '#2a2e39',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 20,
        barSpacing: barSpacing,
        tickMarkFormatter: (time: number, tickMarkType: TickMarkType) => {
          const date = new Date(time * 1000)
          if (tickMarkType <= 2) {
            // Date label: MM/DD in ET
            return date.toLocaleDateString('en-US', { month: '2-digit', day: '2-digit', timeZone: 'America/New_York' })
          }
          // Time label: h:MM AM/PM in ET
          return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' })
        },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#758696',
          width: 1,
          style: 0,
          labelBackgroundColor: '#363a45',
        },
        horzLine: {
          color: '#758696',
          width: 1,
          style: 0,
          labelBackgroundColor: '#363a45',
        },
      },
    })

    // EMA 9 line (cyan)
    const ema9Series = chart.addLineSeries({
      color: '#00d4ff',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // EMA 21 line (yellow)
    const ema21Series = chart.addLineSeries({
      color: '#ffc107',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // VWAP line (no title — label handled by key levels price line)
    const vwapSeries = chart.addLineSeries({
      color: 'rgba(100,181,246,0.85)',
      lineWidth: 1,
      lineStyle: 0,
      autoscaleInfoProvider: () => null,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Bollinger Bands (blue, semi-transparent)
    const bbUpper = chart.addLineSeries({
      color: 'rgba(41, 98, 255, 0.5)',
      lineWidth: 1,
      lineStyle: 0,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    const bbMiddle = chart.addLineSeries({
      color: 'rgba(41, 98, 255, 0.8)',
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    const bbLower = chart.addLineSeries({
      color: 'rgba(41, 98, 255, 0.5)',
      lineWidth: 1,
      lineStyle: 0,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // ATR Bands (orange, semi-transparent)
    const atrUpper = chart.addLineSeries({
      color: 'rgba(255, 152, 0, 0.5)',
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    const atrLower = chart.addLineSeries({
      color: 'rgba(255, 152, 0, 0.5)',
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // VWAP AA Bands — 1x std dev only (green, matching TradingView band 1)
    const vwapBandOpts = { lineWidth: 1 as const, lineStyle: 0, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, autoscaleInfoProvider: () => null }
    const vwapUpper1 = chart.addLineSeries({ ...vwapBandOpts, color: 'rgba(76, 175, 80, 0.5)' })
    const vwapLower1 = chart.addLineSeries({ ...vwapBandOpts, color: 'rgba(76, 175, 80, 0.5)' })

    // Position line guide series (added before candles so its price lines render
    // behind candles/markers instead of on top of price action).
    const positionGuideSeries = chart.addLineSeries({
      color: 'rgba(0, 0, 0, 0)',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Candlestick series - TradingView standard teal/red
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#26a69a',
      downColor: '#ef5350',
      borderVisible: false,
      wickUpColor: '#26a69a',
      wickDownColor: '#ef5350',
      priceFormat: { type: 'price', precision: 2, minMove: 0.25 },
      lastValueVisible: true,
      priceLineVisible: true,
      priceLineWidth: 1,
      priceLineColor: 'rgba(255, 255, 255, 0.6)',
      priceLineStyle: 2,
    })

    // Volume series
    const volumeSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      priceLineVisible: false,
      lastValueVisible: false,
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.82, bottom: 0 },
      visible: false,
    })

    // Connection line - added LAST so it renders ON TOP of everything when hovering
    const connectionLine = chart.addLineSeries({
      color: '#00e676',
      lineWidth: 4,
      lineStyle: 0, // solid
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // ─── Overlay Plugins (attached to candleSeries) ───────────────────────────
    const tradeZonesPlugin = new TradeZones()
    const sessionPlugin = new SessionHighlighting()
    const sdZonesPlugin = new SDZones()
    const vwapBandFillPlugin = new VWAPBandFill(vwapUpper1, vwapLower1)
    const keyLevelsPlugin = new KeyLevelsPlugin()
    candleSeries.attachPrimitive(tradeZonesPlugin)
    candleSeries.attachPrimitive(sessionPlugin)
    candleSeries.attachPrimitive(sdZonesPlugin)
    candleSeries.attachPrimitive(vwapBandFillPlugin)
    candleSeries.attachPrimitive(keyLevelsPlugin)

    // Populate refs
    refs.current = {
      chart,
      candleSeries,
      volumeSeries,
      ema9Series,
      ema21Series,
      vwapSeries,
      positionGuideSeries,
      connectionLine,
      bbUpper,
      bbMiddle,
      bbLower,
      atrUpper,
      atrLower,
      vwapUpper1,
      vwapLower1,
      tradeZones: tradeZonesPlugin,
      sessionPlugin,
      sdZonesPlugin,
      vwapBandFill: vwapBandFillPlugin,
      keyLevelsPlugin,
      tbtPlugin: null,
      positionPriceLines: [],
      userScrolledAway: false,
    }

    // Detect if user has manually scrolled away from live
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => {
      // Reset on any range change (will be set true by wheel/touch)
      // This keeps it accurate but wheel handler is the real trigger
    })

    // On mouse wheel / touch, mark user as having scrolled
    const handleUserScroll = () => { refs.current.userScrolledAway = true }
    containerRef.current?.addEventListener('wheel', handleUserScroll, { passive: true })
    containerRef.current?.addEventListener('touchstart', handleUserScroll, { passive: true })

    // Notify parent that chart is ready
    onChartReady?.(chart)

    // autoSize: true handles resize automatically via ResizeObserver

    return () => {
      // Detach plugins before removing chart
      try { candleSeries.detachPrimitive(tradeZonesPlugin) } catch {}
      try { candleSeries.detachPrimitive(sessionPlugin) } catch {}
      try { candleSeries.detachPrimitive(sdZonesPlugin) } catch {}
      try { candleSeries.detachPrimitive(vwapBandFillPlugin) } catch {}
      try { candleSeries.detachPrimitive(keyLevelsPlugin) } catch {}
      // tbtPlugin detach removed — trendlines disabled
      refs.current.tradeZones = null
      refs.current.sessionPlugin = null
      refs.current.sdZonesPlugin = null
      onChartReady?.(null)
      chart.remove()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [barSpacing]) // onChartReady intentionally excluded to avoid recreation

  // (watermark removed — timeframe shown in legend header instead)

  const setUserScrolledAway = (value: boolean) => {
    refs.current.userScrolledAway = value
  }

  return { refs, setUserScrolledAway }
}
