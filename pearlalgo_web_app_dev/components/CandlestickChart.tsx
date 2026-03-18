'use client'

import React, { useEffect, useRef, useState, useMemo, useCallback } from 'react'
import Image from 'next/image'
import { createChart, ColorType, CrosshairMode, IChartApi, ISeriesApi, Time, IPriceLine } from 'lightweight-charts'
import type { CandleData, IndicatorData, MarkerData, Indicators, BollingerBandsData, ATRBandsData } from '@/stores'
import { useChartSettingsStore } from '@/stores'
import { SessionHighlighting } from '@/lib/chart-plugins/session-highlighting'
import { SDZones }              from '@/lib/chart-plugins/sd-zones'
import { TBTTrendlines }        from '@/lib/chart-plugins/tbt-trendlines'
import { TradeZones, type TradeZone } from '@/lib/chart-plugins/trade-zones'

interface PositionLine {
  price: number
  color: string
  title: string
  kind?: 'entry' | 'sl' | 'tp'
  lineWidth?: 1 | 2 | 3 | 4
  lineStyle?: number
  axisLabelVisible?: boolean
}

interface ChartProps {
  data: CandleData[]
  indicators?: Indicators
  markers?: MarkerData[]
  barSpacing?: number
  timeframe?: string
  onChartReady?: (chart: IChartApi | null) => void
  positionLines?: PositionLine[]  // Entry, SL, TP lines for active positions
}

interface TooltipState {
  visible: boolean
  x: number
  y: number
  marker: MarkerData | null
  groupedMarkers: MarkerData[] | null  // All markers at this time
}



function CandlestickChart({ data, indicators, markers, barSpacing = 10, timeframe = '5m', onChartReady, positionLines }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const ema9SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const ema21SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const positionGuideSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const connectionLineRef = useRef<ISeriesApi<'Line'> | null>(null)
  const resizeHandlerRef = useRef<(() => void) | null>(null)

  // Bollinger Bands series refs
  const bbUpperRef = useRef<ISeriesApi<'Line'> | null>(null)
  const bbMiddleRef = useRef<ISeriesApi<'Line'> | null>(null)
  const bbLowerRef = useRef<ISeriesApi<'Line'> | null>(null)

  // ATR Bands series refs
  const atrUpperRef = useRef<ISeriesApi<'Line'> | null>(null)
  const atrLowerRef = useRef<ISeriesApi<'Line'> | null>(null)

  // Chart overlay plugins (attached as primitives to candleSeries)
  const sessionPluginRef = useRef<SessionHighlighting | null>(null)
  const sdZonesPluginRef = useRef<SDZones | null>(null)
  const tbtPluginRef      = useRef<TBTTrendlines | null>(null)
  const tradeZonesRef     = useRef<TradeZones | null>(null)

  // S&R Power overlay ref
  const srPowerRef = useRef<HTMLDivElement>(null)

  // Position price lines refs (for cleanup)
  const positionPriceLinesRef = useRef<IPriceLine[]>([])

  // Chart settings for indicator visibility
  const indicatorSettings = useChartSettingsStore((s) => s.indicators)

  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    marker: null,
    groupedMarkers: null,
  })

  // Track the active signal for highlighting
  const [activeSignalId, setActiveSignalId] = useState<string | null>(null)

  // Candle countdown timer
  const [candleCountdown, setCandleCountdown] = useState<string>('')

  // Get timeframe in seconds
  const getTimeframeSeconds = useCallback(() => {
    switch (timeframe) {
      case '1m': return 60
      case '5m': return 300
      case '15m': return 900
      case '1h': return 3600
      default: return 300
    }
  }, [timeframe])

  // Update candle countdown every second
  useEffect(() => {
    const updateCountdown = () => {
      const now = Math.floor(Date.now() / 1000)
      const tfSeconds = getTimeframeSeconds()
      const secondsIntoCandle = now % tfSeconds
      const secondsRemaining = tfSeconds - secondsIntoCandle

      const mins = Math.floor(secondsRemaining / 60)
      const secs = secondsRemaining % 60

      if (mins > 0) {
        setCandleCountdown(`${mins}:${secs.toString().padStart(2, '0')}`)
      } else {
        setCandleCountdown(`${secs}s`)
      }
    }

    updateCountdown()
    const interval = setInterval(updateCountdown, 1000)
    return () => clearInterval(interval)
  }, [getTimeframeSeconds])

  // Build a lookup map for markers by time
  const markersByTime = useMemo(() => {
    const map = new Map<number, MarkerData[]>()
    if (!markers) return map
    for (const m of markers) {
      const existing = map.get(m.time) || []
      existing.push(m)
      map.set(m.time, existing)
    }
    return map
  }, [markers])

  // Build a lookup map for candles by time (for marker hit-testing)
  const candlesByTime = useMemo(() => {
    const map = new Map<number, CandleData>()
    for (const c of data) map.set(c.time, c)
    return map
  }, [data])

  // Aggregate markers by time - combine stacked markers into single visual marker
  const aggregatedMarkers = useMemo(() => {
    if (!markers) return []
    
    const groups = new Map<number, MarkerData[]>()
    markers.forEach(m => {
      const existing = groups.get(m.time) || []
      existing.push(m)
      groups.set(m.time, existing)
    })
    
    // Create single marker per time slot
    return Array.from(groups.entries()).map(([time, group]) => {
      // Single marker - return as-is
      if (group.length === 1) return group[0]
      
      // Multiple markers at same time - create combined marker
      const entries = group.filter(m => m.kind === 'entry')
      const exits = group.filter(m => m.kind === 'exit')
      const totalPnl = exits.reduce((sum, m) => sum + (m.pnl || 0), 0)
      const wins = exits.filter(m => (m.pnl || 0) >= 0).length
      const losses = exits.length - wins
      
      // Determine dominant type and position
      const isExitDominant = exits.length >= entries.length
      const dominantDirection = exits.length > 0 
        ? (exits.filter(m => m.direction === 'long').length > exits.length / 2 ? 'long' : 'short')
        : (entries.filter(m => m.direction === 'long').length > entries.length / 2 ? 'long' : 'short')
      
      return {
        time,
        position: (isExitDominant 
          ? (dominantDirection === 'long' ? 'aboveBar' : 'belowBar')
          : (dominantDirection === 'long' ? 'belowBar' : 'aboveBar')) as 'aboveBar' | 'belowBar',
        color: isExitDominant 
          ? (totalPnl >= 0 ? 'rgba(100, 200, 180, 0.9)' : 'rgba(220, 140, 100, 0.9)')
          : 'rgba(180, 180, 180, 0.9)',
        shape: 'circle' as const,
        text: `${group.length}`,
        kind: isExitDominant ? 'exit' : 'entry',
        direction: dominantDirection,
        pnl: totalPnl,
        // Store group metadata for tooltip
        _isGrouped: true,
        _groupCount: group.length,
        _entriesCount: entries.length,
        _exitsCount: exits.length,
        _wins: wins,
        _losses: losses,
      } as MarkerData & { _isGrouped?: boolean; _groupCount?: number; _entriesCount?: number; _exitsCount?: number; _wins?: number; _losses?: number }
    })
  }, [markers])

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 600,
      layout: {
        background: { type: ColorType.Solid, color: '#0a0a0f' },
        textColor: '#8a94a6',
      },
      grid: {
        vertLines: { color: 'rgba(30,34,45,0.40)' },
        horzLines: { color: 'rgba(30,34,45,0.40)' },
      },
      rightPriceScale: {
        borderColor: '#2a2a3a',
        // Reduce unused bottom space; volume is handled by its own scale margins below
        scaleMargins: { top: 0.08, bottom: 0.12 },
      },
      timeScale: {
        visible: true,
        borderColor: '#2a2a3a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 15,  // More space between candles and price labels
        barSpacing: barSpacing,
        tickMarkFormatter: (time: number) => {
          const date = new Date(time * 1000)
          const hours = date.getHours().toString().padStart(2, '0')
          const minutes = date.getMinutes().toString().padStart(2, '0')
          return `${hours}:${minutes}`
        },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#758696',
          width: 1,
          style: 3,
          labelBackgroundColor: '#2a2a3a',
        },
        horzLine: {
          color: '#758696',
          width: 1,
          style: 3,
          labelBackgroundColor: '#2a2a3a',
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

    // VWAP line (blue, solid)
    const vwapSeries = chart.addLineSeries({
      color: '#2962ff',
      lineWidth: 2,
      lineStyle: 0,
      // Don't let VWAP (or any outlier points) blow out the chart's vertical scaling.
      // The candlestick series should drive autoscale; VWAP will still render when within range.
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
    bbUpperRef.current = bbUpper
    bbMiddleRef.current = bbMiddle
    bbLowerRef.current = bbLower

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
    atrUpperRef.current = atrUpper
    atrLowerRef.current = atrLower

    // Position line guide series (added before candles so its price lines render
    // behind candles/markers instead of on top of price action).
    const positionGuideSeries = chart.addLineSeries({
      color: 'rgba(0, 0, 0, 0)',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    positionGuideSeriesRef.current = positionGuideSeries

    // Candlestick series - bright green/red
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00e676',
      downColor: '#ff5252',
      borderVisible: false,
      wickUpColor: '#00e676',
      wickDownColor: '#ff5252',
      priceFormat: { type: 'price', precision: 2, minMove: 0.25 },
      lastValueVisible: true,
      priceLineVisible: true,
      priceLineWidth: 1,
      priceLineColor: 'rgba(255, 215, 0, 0.35)',  // Gold/yellow - subtle, less visible than position lines
      priceLineStyle: 2,  // Dashed
    })

    // Volume series
    const volumeSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      // Keep volume visible but don't let it add right-axis labels (TradingView-like).
      priceLineVisible: false,
      lastValueVisible: false,
    })
    volumeSeries.priceScale().applyOptions({
      // Make volume bars smaller (less busy, more room for price action)
      scaleMargins: { top: 0.88, bottom: 0 },
      // Hide the volume scale entirely so it doesn't stack with price labels.
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
    connectionLineRef.current = connectionLine

    // ─── Overlay Plugins (attached to candleSeries) ───────────────────────────
    const tradeZonesPlugin = new TradeZones()
    const sessionPlugin = new SessionHighlighting()
    const sdZonesPlugin = new SDZones()
    const tbtPlugin     = new TBTTrendlines()
    candleSeries.attachPrimitive(tradeZonesPlugin)
    candleSeries.attachPrimitive(sessionPlugin)
    candleSeries.attachPrimitive(sdZonesPlugin)
    candleSeries.attachPrimitive(tbtPlugin)
    tradeZonesRef.current     = tradeZonesPlugin
    sessionPluginRef.current = sessionPlugin
    sdZonesPluginRef.current = sdZonesPlugin
    tbtPluginRef.current     = tbtPlugin

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries
    ema9SeriesRef.current = ema9Series
    ema21SeriesRef.current = ema21Series
    vwapSeriesRef.current = vwapSeries

    // Notify parent that chart is ready
    onChartReady?.(chart)

    // Clean up any existing resize handler before adding new one
    if (resizeHandlerRef.current) {
      window.removeEventListener('resize', resizeHandlerRef.current)
    }

    // Handle resize - store in ref to ensure proper cleanup
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || 600,
        })
      }
    }
    resizeHandlerRef.current = handleResize
    window.addEventListener('resize', handleResize)

    return () => {
      if (resizeHandlerRef.current) {
        window.removeEventListener('resize', resizeHandlerRef.current)
        resizeHandlerRef.current = null
      }
      // Detach plugins before removing chart
      try { candleSeries.detachPrimitive(tradeZonesPlugin) } catch {}
      try { candleSeries.detachPrimitive(sessionPlugin) } catch {}
      try { candleSeries.detachPrimitive(sdZonesPlugin) } catch {}
      try { candleSeries.detachPrimitive(tbtPlugin) }     catch {}
      tradeZonesRef.current     = null
      sessionPluginRef.current = null
      sdZonesPluginRef.current = null
      tbtPluginRef.current     = null
      onChartReady?.(null)
      chart.remove()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [barSpacing]) // onChartReady intentionally excluded to avoid recreation

  // Subscribe to crosshair move for tooltip
  useEffect(() => {
    if (!chartRef.current || !containerRef.current) return

    const chart = chartRef.current
    const container = containerRef.current

    const handleCrosshairMove = (param: any) => {
      if (!param.time || !param.point) {
        setTooltip((prev) => ({ ...prev, visible: false }))
        setActiveSignalId(null)
        return
      }

      const time = typeof param.time === 'object' ? param.time.valueOf() : param.time
      const markersAtTime = markersByTime.get(time)

      if (markersAtTime && markersAtTime.length > 0) {
        // Only trigger tooltip when the pointer is actually near a marker (not anywhere along the crosshair line).
        const series = candleSeriesRef.current
        const candle = candlesByTime.get(time)
        const HIT_RADIUS_PX = 22

        let bestMarker: MarkerData | null = null
        let bestDist = Number.POSITIVE_INFINITY

        if (series) {
          for (const m of markersAtTime) {
            // Markers are drawn above/below the bar, so use candle high/low as anchor.
            // Fallback to entry/exit price if candle is missing (rare).
            const anchorPrice =
              candle
                ? (m.position === 'aboveBar' ? candle.high : candle.low)
                : (m.kind === 'exit'
                    ? (m.exit_price ?? m.entry_price)
                    : (m.entry_price ?? m.exit_price))

            if (anchorPrice === undefined || anchorPrice === null) continue

            const y = series.priceToCoordinate(anchorPrice)
            if (y === null || y === undefined) continue

            const dist = Math.abs(y - param.point.y)
            if (dist < bestDist) {
              bestDist = dist
              bestMarker = m
            }
          }
        }

        if (!bestMarker || bestDist > HIT_RADIUS_PX) {
          setTooltip((prev) => ({ ...prev, visible: false, groupedMarkers: null }))
          setActiveSignalId(null)
          return
        }

        const marker = bestMarker
        
        // Show tooltip near the crosshair
        const containerRect = container.getBoundingClientRect()
        let x = param.point.x + 15
        let y = param.point.y - 10

        // Responsive tooltip dimensions - larger for grouped markers
        const isGrouped = markersAtTime.length > 1
        const tooltipWidth = Math.min(isGrouped ? 280 : 240, window.innerWidth - 40)
        const tooltipHeight = Math.min(isGrouped ? 300 : 160, window.innerHeight * 0.4)
        if (x + tooltipWidth > containerRect.width) {
          x = param.point.x - tooltipWidth - 15
        }
        if (y + tooltipHeight > containerRect.height) {
          y = containerRect.height - tooltipHeight - 10
        }
        if (y < 10) y = 10
        if (x < 10) x = 10

        setTooltip({
          visible: true,
          x,
          y,
          marker,
          groupedMarkers: markersAtTime.length > 1 ? markersAtTime : null,
        })
        // For single markers, set active signal; for grouped, don't highlight individual
        setActiveSignalId(markersAtTime.length === 1 ? (marker.signal_id || null) : null)
      } else {
        setTooltip((prev) => ({ ...prev, visible: false, groupedMarkers: null }))
        setActiveSignalId(null)
      }
    }

    chart.subscribeCrosshairMove(handleCrosshairMove)

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
    }
  }, [markersByTime, candlesByTime])

  // Track previous data length to detect major changes (like timeframe switch)
  const prevDataLength = useRef(0)

  // Update candle data
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !data?.length) return

    // Cast time to Time type for lightweight-charts
    const candleData = data.map((d) => ({
      time: d.time as Time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    }))
    candleSeriesRef.current.setData(candleData)

    // Keep the background guide series populated so its price lines render.
    // (Lightweight Charts may not draw series price lines on an empty series.)
    if (positionGuideSeriesRef.current) {
      const guideData = data.map((d) => ({
        time: d.time as Time,
        value: d.close,
      }))
      positionGuideSeriesRef.current.setData(guideData)
    }

    const volumeData = data.map((d) => ({
      time: d.time as Time,
      value: d.volume || 0,
      color: d.close >= d.open ? 'rgba(0, 230, 118, 0.3)' : 'rgba(255, 82, 82, 0.3)',
    }))
    volumeSeriesRef.current.setData(volumeData)

    // On data load: show recent bars (zoomed in) rather than fitting ALL content.
    // fitContent() zooms out too far showing all bars. Instead, show the last N bars
    // with a sensible zoom level, then scroll to the latest bar.
    if (chartRef.current) {
      const lengthChanged = Math.abs(data.length - prevDataLength.current) > 5
      if (lengthChanged || prevDataLength.current === 0) {
        // Show last ~100 bars (reasonable zoom level for readability)
        const visibleBars = Math.min(100, data.length)
        if (data.length > visibleBars) {
          const fromTime = data[data.length - visibleBars].time as Time
          const toTime = data[data.length - 1].time as Time
          chartRef.current.timeScale().setVisibleRange({ from: fromTime, to: toTime })
        } else {
          chartRef.current.timeScale().fitContent()
        }
      }
      chartRef.current.timeScale().scrollToRealTime()
      prevDataLength.current = data.length
    }
  }, [data])

  // Update indicators
  useEffect(() => {
    if (!indicators) return

    if (ema9SeriesRef.current && indicators.ema9?.length) {
      const ema9Data = indicators.ema9.map((d) => ({ time: d.time as Time, value: d.value }))
      ema9SeriesRef.current.setData(ema9Data)
    }
    if (ema21SeriesRef.current && indicators.ema21?.length) {
      const ema21Data = indicators.ema21.map((d) => ({ time: d.time as Time, value: d.value }))
      ema21SeriesRef.current.setData(ema21Data)
    }
    if (vwapSeriesRef.current && indicators.vwap?.length) {
      const vwapData = indicators.vwap.map((d) => ({ time: d.time as Time, value: d.value }))
      vwapSeriesRef.current.setData(vwapData)
    }

    // Update Bollinger Bands
    if (indicatorSettings.bollingerBands && indicators.bollingerBands?.length) {
      if (bbUpperRef.current) {
        const upperData = indicators.bollingerBands.map((d) => ({ time: d.time as Time, value: d.upper }))
        bbUpperRef.current.setData(upperData)
      }
      if (bbMiddleRef.current) {
        const middleData = indicators.bollingerBands.map((d) => ({ time: d.time as Time, value: d.middle }))
        bbMiddleRef.current.setData(middleData)
      }
      if (bbLowerRef.current) {
        const lowerData = indicators.bollingerBands.map((d) => ({ time: d.time as Time, value: d.lower }))
        bbLowerRef.current.setData(lowerData)
      }
    } else {
      // Clear Bollinger Bands if disabled
      bbUpperRef.current?.setData([])
      bbMiddleRef.current?.setData([])
      bbLowerRef.current?.setData([])
    }

    // Update ATR Bands
    if (indicatorSettings.atrBands && indicators.atrBands?.length) {
      if (atrUpperRef.current) {
        const upperData = indicators.atrBands.map((d) => ({ time: d.time as Time, value: d.upper }))
        atrUpperRef.current.setData(upperData)
      }
      if (atrLowerRef.current) {
        const lowerData = indicators.atrBands.map((d) => ({ time: d.time as Time, value: d.lower }))
        atrLowerRef.current.setData(lowerData)
      }
    } else {
      // Clear ATR Bands if disabled
      atrUpperRef.current?.setData([])
      atrLowerRef.current?.setData([])
    }
  }, [indicators, indicatorSettings.bollingerBands, indicatorSettings.atrBands])

  // Update markers - use aggregated markers to prevent stacking
  useEffect(() => {
    if (!candleSeriesRef.current || !aggregatedMarkers?.length) return

    try {
      // When hovering on a single trade, show that trade's entry+exit
      // Otherwise show aggregated markers
      let displayMarkers: any[] = []
      
      if (activeSignalId && markers) {
        // Show individual markers for the active trade
        displayMarkers = markers
          .filter(m => m.signal_id === activeSignalId)
          .map((m) => {
            let position = m.position
            if (m.kind === 'exit') {
              position = m.direction === 'long' ? 'aboveBar' : 'belowBar'
            }
            let color = m.kind === 'entry' 
              ? 'rgba(180, 180, 180, 0.9)' 
              : ((m.pnl || 0) >= 0 ? 'rgba(100, 200, 180, 0.9)' : 'rgba(220, 140, 100, 0.9)')
            
            return {
              time: m.time as any,
              position,
              color,
              shape: m.kind === 'exit' ? 'circle' : m.shape,
              text: '',
            }
          })
      } else {
        // Show aggregated markers
        displayMarkers = aggregatedMarkers.map((m: any) => {
          let position = m.position
          if (m.kind === 'exit' && !m._isGrouped) {
            position = m.direction === 'long' ? 'aboveBar' : 'belowBar'
          }
          
          let color = m.color
          if (!m._isGrouped) {
            if (m.kind === 'entry') {
              color = 'rgba(180, 180, 180, 0.8)'
            } else if (m.kind === 'exit') {
              const isWin = (m.pnl || 0) >= 0
              color = isWin ? 'rgba(100, 200, 180, 0.8)' : 'rgba(220, 140, 100, 0.8)'
            }
          }
          
          return {
            time: m.time as any,
            position,
            color,
            // Grouped markers show circle with count, singles show original shape
            shape: m._isGrouped ? 'circle' : (m.kind === 'exit' ? 'circle' : m.shape),
            // Show count for grouped markers
            text: m._isGrouped ? `${m._groupCount}` : '',
          }
        })
      }
      
      candleSeriesRef.current.setMarkers(displayMarkers)
    } catch (e) {
      console.warn('Failed to set markers:', e)
    }
  }, [aggregatedMarkers, markers, activeSignalId])

  // Draw connection line between entry and exit when hovering
  // Update position lines (Entry, SL, TP)
  useEffect(() => {
    if (!candleSeriesRef.current || !positionGuideSeriesRef.current) return
    const guideSeries = positionGuideSeriesRef.current

    // Remove all existing position price lines first
    positionPriceLinesRef.current.forEach((priceLine) => {
      try {
        guideSeries.removePriceLine(priceLine)
      } catch {
        // Line may already be removed
      }
    })
    positionPriceLinesRef.current = []

    // If no position lines, we're done
    if (!positionLines?.length) return

    // Neat label de-clutter: keep the lines, but hide axis labels that would stack.
    // We use pixel coordinates to be zoom-aware.
    const series = candleSeriesRef.current
    const MIN_LABEL_GAP_PX = 18
    const priorityForKind = (kind?: string) => {
      switch (kind) {
        case 'entry': return 3
        case 'tp': return 2
        case 'sl': return 1
        default: return 0
      }
    }

    type Candidate = { idx: number; y: number | null; priority: number }
    const candidates: Candidate[] = positionLines.map((l, idx) => ({
      idx,
      y: series?.priceToCoordinate(l.price) ?? null,
      priority: priorityForKind((l as any).kind),
    }))

    const keepAxisLabels = new Set<number>()

    // Keep all labels with unknown coordinates (rare), otherwise cluster by pixel gap
    const sortable = candidates
      .filter((c) => c.y !== null && c.y !== undefined)
      .map((c) => ({ ...c, y: c.y as number }))
      .sort((a, b) => a.y - b.y)

    let cluster: typeof sortable = []
    const flushCluster = () => {
      if (cluster.length === 0) return
      // Pick the most important label within the cluster
      let best = cluster[0]
      for (const c of cluster) {
        if (c.priority > best.priority) best = c
      }
      keepAxisLabels.add(best.idx)
      cluster = []
    }

    for (const item of sortable) {
      // Respect caller preference: if axis label is explicitly disabled, skip it.
      const requested = positionLines[item.idx].axisLabelVisible ?? true
      if (!requested) continue

      if (cluster.length === 0) {
        cluster.push(item)
        continue
      }

      const last = cluster[cluster.length - 1]
      if (item.y - last.y < MIN_LABEL_GAP_PX) {
        cluster.push(item)
      } else {
        flushCluster()
        cluster.push(item)
      }
    }
    flushCluster()

    // Lines with unknown coordinates: keep label if requested
    for (const c of candidates) {
      if (c.y === null) {
        const requested = positionLines[c.idx].axisLabelVisible ?? true
        if (requested) keepAxisLabels.add(c.idx)
      }
    }

    // Create price lines for each position
    positionLines.forEach((line, idx) => {
      if (guideSeries) {
        const requested = line.axisLabelVisible ?? true
        const axisVisible = requested && keepAxisLabels.has(idx)
        // Hide text badges (ENTRY/SL/TP) on the right price scale while
        // keeping numeric price labels visible.
        const title = ''
        const lineWidth: 1 | 2 | 3 | 4 = line.lineWidth ?? (line.kind === 'entry' ? 2 : 1)
        const lineStyle = line.lineStyle ?? (line.kind === 'entry' ? 0 : 2)
        const priceLine = guideSeries.createPriceLine({
          price: line.price,
          color: line.color,
          lineWidth,
          lineStyle,
          axisLabelVisible: axisVisible,
          title,
        })
        positionPriceLinesRef.current.push(priceLine)
      }
    })

    // Cleanup function on unmount
    return () => {
      positionPriceLinesRef.current.forEach((priceLine) => {
        try {
          guideSeries.removePriceLine(priceLine)
        } catch {
          // Line may already be removed
        }
      })
      positionPriceLinesRef.current = []
    }
  }, [positionLines])




  // ── TradeZones: update shaded risk/reward regions when positions change ──────
  useEffect(() => {
    if (!tradeZonesRef.current) return
    const zones: TradeZone[] = (positionLines || []).reduce((acc: TradeZone[], line, _i, arr) => {
      if (line.kind !== 'entry') return acc
      const sl = arr.find(l => l.kind === 'sl')
      const tp = arr.find(l => l.kind === 'tp')
      const dir: 'long' | 'short' = sl ? (line.price > sl.price ? 'long' : 'short') : 'long'
      acc.push({ entryPrice: line.price, slPrice: sl?.price, tpPrice: tp?.price, direction: dir })
      return acc
    }, [])
    tradeZonesRef.current.setZones(zones)
  }, [positionLines])

  // ── SpacemanBTC Key Levels ──────────────────────────────────────────────────
  const keyLevelLinesRef = useRef<import('lightweight-charts').IPriceLine[]>([])
  useEffect(() => {
    const series = candleSeriesRef.current
    if (!series || !data?.length) return

    keyLevelLinesRef.current.forEach(l => { try { series.removePriceLine(l) } catch {} })
    keyLevelLinesRef.current = []

    const toET = (unix: number) => unix - 4 * 3600
    const nowET = toET(data[data.length - 1].time as number)
    const todayETMidnight = nowET - (nowET % 86400)

    let dailyOpen: number | null = null
    let weeklyOpen: number | null = null
    let prevDayHigh = -Infinity, prevDayLow = Infinity

    for (const c of data) {
      const t = toET(c.time as number)
      const dayStart = t - (t % 86400)
      const hour = Math.floor((t % 86400) / 3600)
      const min  = Math.floor((t % 3600) / 60)
      const dayOfWeek = new Date((c.time as number) * 1000).getUTCDay()

      if (dayStart === todayETMidnight && hour === 9 && min === 30 && dailyOpen === null)
        dailyOpen = c.open
      if (dayOfWeek === 1 && hour === 9 && min === 30 && weeklyOpen === null)
        weeklyOpen = c.open
      const prevMidnight = todayETMidnight - 86400
      if (dayStart === prevMidnight && hour >= 9 && (hour < 16 || (hour === 16 && min <= 15))) {
        if (c.high > prevDayHigh) prevDayHigh = c.high
        if (c.low  < prevDayLow)  prevDayLow  = c.low
      }
    }

    const levels: Array<{ price: number; title: string; color: string }> = []
    if (dailyOpen)               levels.push({ price: dailyOpen,  title: 'D Open', color: 'rgba(255,235,59,0.45)' })
    if (weeklyOpen)              levels.push({ price: weeklyOpen, title: 'W Open', color: 'rgba(255,152,0,0.45)'  })
    if (prevDayHigh > -Infinity) levels.push({ price: prevDayHigh, title: 'PDH',  color: 'rgba(76,175,80,0.40)'  })
    if (prevDayLow  <  Infinity) levels.push({ price: prevDayLow,  title: 'PDL',  color: 'rgba(244,67,54,0.40)'  })

    for (const lv of levels) {
      try {
        keyLevelLinesRef.current.push(series.createPriceLine({
          price: lv.price, color: lv.color, lineWidth: 1, lineStyle: 2,
          axisLabelVisible: true, title: lv.title,
        }))
      } catch {}
    }
    return () => {
      keyLevelLinesRef.current.forEach(l => { try { series.removePriceLine(l) } catch {} })
      keyLevelLinesRef.current = []
    }
  }, [data])

  // ── S&R Power overlay ──────────────────────────────────────────────────────
  useEffect(() => {
    const el = srPowerRef.current
    if (!el || !data?.length) return
    const current = data[data.length - 1].close
    const LB = 3
    let sells = 0, buys = 0
    for (let i = LB; i < data.length - LB; i++) {
      const h = data[i].high, l = data[i].low
      let isH = true, isL = true
      for (let j = i - LB; j <= i + LB; j++) {
        if (j !== i) { if (data[j].high >= h) isH = false; if (data[j].low <= l) isL = false }
      }
      if (isH && h > current && h < current * 1.015) sells++
      if (isL && l < current && l > current * 0.985) buys++
    }
    // Scale relative to total pivots found — avoids always-100 issue
    const totalPivots = Math.max(sells + buys, 1)
    const sp = Math.round((sells / totalPivots) * 100)
    const bp = Math.round((buys  / totalPivots) * 100)
    el.innerHTML =
      '<div style="color:rgba(239,83,80,0.60);font-size:10px;font-weight:600;font-family:monospace;letter-spacing:0.3px;text-shadow:0 1px 2px rgba(0,0,0,0.6);margin-bottom:2px">Sell Power: ' + sp + '</div>' +
      '<div style="color:rgba(38,166,154,0.60);font-size:10px;font-weight:600;font-family:monospace;letter-spacing:0.3px;text-shadow:0 1px 2px rgba(0,0,0,0.6)">Buy Power: ' + bp + '</div>'
  }, [data])

  // Format price
  const formatPrice = (price?: number) => {
    if (price === undefined || price === null) return '—'
    return price.toFixed(2)
  }

  // Format PnL
  const formatPnL = (pnl?: number) => {
    if (pnl === undefined || pnl === null) return '—'
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  // Find paired marker (entry finds exit, exit finds entry) for the same signal_id
  const findPairedMarker = (marker: MarkerData) => {
    if (!markers) return null
    return markers.find(m => 
      m.signal_id === marker.signal_id && m.kind !== marker.kind
    ) || null
  }

  const pairedMarker = tooltip.marker ? findPairedMarker(tooltip.marker) : null

  // Responsive min-height based on viewport
  const minHeight = typeof window !== 'undefined'
    ? Math.max(260, window.innerHeight * 0.42)
    : 500

  // Get current price and change
  const currentCandle = data[data.length - 1]
  const prevCandle = data[data.length - 2]
  const priceChange = currentCandle && prevCandle
    ? currentCandle.close - prevCandle.close
    : 0
  const priceChangePercent = prevCandle
    ? ((priceChange / prevCandle.close) * 100)
    : 0

  return (
    <div
      ref={containerRef}
      className={`chart-container-inner ${activeSignalId ? 'trade-focused' : ''}`}
      style={{ width: '100%', height: '100%', minHeight, position: 'relative' }}>
      {/* S&R Power badges */}
      <div
        ref={srPowerRef}
        style={{ position: 'absolute', top: 36, right: 8, zIndex: 10, display: 'flex', flexDirection: 'column', gap: 3, pointerEvents: 'none' }}
      />
      {/* Unified Chart Info Bar - Price, Countdown, Legend */}
      <div className="chart-info-bar">
        {/* Price Section */}
        {currentCandle && (
          <div className={`info-price ${priceChange >= 0 ? 'up' : 'down'}`}>
            <span className="price-value">{currentCandle.close.toFixed(2)}</span>
          </div>
        )}

        {/* Countdown Section */}
        <div className="info-countdown">
          <span className="countdown-dot"></span>
          <span className="countdown-tf">{timeframe}</span>
          <span className="countdown-time">{candleCountdown}</span>
        </div>

        {/* Legend Section */}
        <div className="info-legend">
          <span className="leg"><span className="line ema9"></span>9</span>
          <span className="leg"><span className="line ema21"></span>21</span>
          <span className="leg"><span className="line vwap"></span>V</span>
          <span className="leg-sep"></span>
          <span className="leg"><span className="line entry"></span>E</span>
          <span className="leg"><span className="line sl"></span>SL</span>
          <span className="leg"><span className="line tp"></span>TP</span>
          <span className="leg-sep"></span>
          <span className="leg"><span className="mkr entry">▲●</span>In</span>
          <span className="leg"><span className="mkr win">●</span>W</span>
          <span className="leg"><span className="mkr loss">●</span>L</span>
        </div>
      </div>

      {/* Marker Tooltip - Single Trade */}
      {tooltip.visible && tooltip.marker && !tooltip.groupedMarkers && (
        <div
          className={`marker-tooltip ${(tooltip.marker.pnl || pairedMarker?.pnl || 0) >= 0 ? 'win' : 'loss'}`}
          style={{
            position: 'absolute',
            left: tooltip.x,
            top: tooltip.y,
            pointerEvents: 'none',
          }}
        >
          {/* Header */}
          <div className="tooltip-header">
            <span className={`tooltip-direction ${tooltip.marker.direction}`}>
              {tooltip.marker.direction?.toUpperCase()}
            </span>
            <span className={`tooltip-kind ${tooltip.marker.kind}`}>
              {tooltip.marker.kind === 'entry' ? 'ENTRY' : 'EXIT'}
            </span>
          </div>

          {/* Time */}
          <div className="tooltip-time">
            {new Date(tooltip.marker.time * 1000).toLocaleString('en-US', {
              month: 'short',
              day: 'numeric',
              hour: '2-digit',
              minute: '2-digit',
              hour12: false
            })}
          </div>

          {/* Trade details - always show both entry and exit */}
          <div className="tooltip-body">
            <div className="tooltip-row">
              <span className="tooltip-label">Entry</span>
              <span className="tooltip-value">
                {formatPrice(tooltip.marker.kind === 'entry' ? tooltip.marker.entry_price : pairedMarker?.entry_price)}
              </span>
            </div>

            {(tooltip.marker.kind === 'exit' || pairedMarker) && (
              <div className="tooltip-row">
                <span className="tooltip-label">Exit</span>
                <span className="tooltip-value">
                  {formatPrice(tooltip.marker.kind === 'exit' ? tooltip.marker.exit_price : pairedMarker?.exit_price)}
                </span>
              </div>
            )}

            {/* P&L - prominent */}
            {(tooltip.marker.pnl !== undefined || pairedMarker?.pnl !== undefined) && (
              <div className={`tooltip-pnl ${((tooltip.marker.pnl || pairedMarker?.pnl || 0) >= 0) ? 'positive' : 'negative'}`}>
                {formatPnL(tooltip.marker.pnl || pairedMarker?.pnl)}
              </div>
            )}

            {/* Exit reason badge */}
            {(tooltip.marker.exit_reason || pairedMarker?.exit_reason) && (
              <div className="tooltip-reason-badge">
                {(tooltip.marker.exit_reason || pairedMarker?.exit_reason)?.replace(/_/g, ' ')}
              </div>
            )}
          </div>

          {/* Entry signals */}
          {(tooltip.marker.reason || pairedMarker?.reason) && (
            <div className="tooltip-signals">
              <div className="tooltip-signals-label">Signals</div>
              <div className="tooltip-signals-list">
                {(tooltip.marker.reason || pairedMarker?.reason)?.split(' | ').slice(0, 4).map((signal, i) => (
                  <span
                    key={i}
                    className={`tooltip-signal-tag ${
                      signal.includes('UP') || signal.includes('LONG') || signal.includes('BULL') ? 'bullish' :
                      signal.includes('DOWN') || signal.includes('SHORT') || signal.includes('BEAR') ? 'bearish' : ''
                    }`}
                  >
                    {signal.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Hold duration - show if we have both entry and exit */}
          {pairedMarker && tooltip.marker.kind === 'entry' && (
            <div className="tooltip-hold-duration">
              <span>Hold Time</span>
              <span className="duration-value">
                {(() => {
                  const mins = Math.round((pairedMarker.time - tooltip.marker.time) / 60)
                  if (mins < 60) return `${mins}m`
                  const hrs = Math.floor(mins / 60)
                  const remainMins = mins % 60
                  return `${hrs}h ${remainMins}m`
                })()}
              </span>
            </div>
          )}
          {pairedMarker && tooltip.marker.kind === 'exit' && (
            <div className="tooltip-hold-duration">
              <span>Hold Time</span>
              <span className="duration-value">
                {(() => {
                  const mins = Math.round((tooltip.marker.time - pairedMarker.time) / 60)
                  if (mins < 60) return `${mins}m`
                  const hrs = Math.floor(mins / 60)
                  const remainMins = mins % 60
                  return `${hrs}h ${remainMins}m`
                })()}
              </span>
            </div>
          )}

          {/* PEARL Logo - small */}
          <Image src="/pearl-emoji.png" alt="" className="tooltip-logo" width={14} height={14} />
        </div>
      )}

    </div>
  )
}

export default React.memo(CandlestickChart)
