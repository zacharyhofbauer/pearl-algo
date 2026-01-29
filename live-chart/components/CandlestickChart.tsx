'use client'

import { useEffect, useRef, useState, useMemo } from 'react'
import { createChart, ColorType, CrosshairMode, IChartApi, ISeriesApi, Time } from 'lightweight-charts'

interface CandleData {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

interface IndicatorData {
  time: number
  value: number
}

interface MarkerData {
  time: number
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle'
  text: string
  // Tooltip metadata
  kind?: 'entry' | 'exit'
  signal_id?: string
  direction?: string
  entry_price?: number
  exit_price?: number
  pnl?: number
  reason?: string
  exit_reason?: string
}

interface ChartProps {
  data: CandleData[]
  indicators?: {
    ema9?: IndicatorData[]
    ema21?: IndicatorData[]
    vwap?: IndicatorData[]
    rsi?: IndicatorData[]
  }
  markers?: MarkerData[]
  barSpacing?: number
  onChartReady?: (chart: IChartApi | null) => void
}

interface TooltipState {
  visible: boolean
  x: number
  y: number
  marker: MarkerData | null
}

// Session times in UTC hours (futures trade almost 24h)
// Overnight/Asian: 23:00 - 08:00 UTC (6pm-3am ET)
// London: 08:00 - 13:00 UTC (3am-8am ET)  
// NY RTH: 14:30 - 21:00 UTC (9:30am-4pm ET)
const getSessionColor = (hour: number): string => {
  if (hour >= 23 || hour < 8) return 'rgba(30, 60, 114, 0.15)' // Overnight - blue tint
  if (hour >= 8 && hour < 14) return 'rgba(60, 40, 20, 0.15)' // London - brown tint
  if (hour >= 14 && hour < 21) return 'rgba(40, 70, 40, 0.15)' // NY RTH - green tint
  return 'transparent'
}

export default function CandlestickChart({ data, indicators, markers, barSpacing = 10, onChartReady }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const ema9SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const ema21SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const connectionLineRef = useRef<ISeriesApi<'Line'> | null>(null)
  
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    marker: null,
  })
  
  // Track the active signal for highlighting
  const [activeSignalId, setActiveSignalId] = useState<string | null>(null)

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
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      rightPriceScale: {
        borderColor: '#2a2a3a',
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        visible: false,
        borderColor: '#2a2a3a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: barSpacing,
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
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

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
      priceLineColor: '#ff5252',
      priceLineStyle: 2,
    })

    // Volume series
    const volumeSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.75, bottom: 0 },
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

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries
    ema9SeriesRef.current = ema9Series
    ema21SeriesRef.current = ema21Series
    vwapSeriesRef.current = vwapSeries

    // Notify parent that chart is ready
    onChartReady?.(chart)

    // Handle resize
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || 600,
        })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
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
        const marker = markersAtTime[0]
        
        // Show tooltip near the crosshair
        const containerRect = container.getBoundingClientRect()
        let x = param.point.x + 15
        let y = param.point.y - 10

        // Clamp to container bounds
        const tooltipWidth = 240
        const tooltipHeight = 160
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
        })
        setActiveSignalId(marker.signal_id || null)
      } else {
        setTooltip((prev) => ({ ...prev, visible: false }))
        setActiveSignalId(null)
      }
    }

    chart.subscribeCrosshairMove(handleCrosshairMove)

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
    }
  }, [markersByTime])

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

    const volumeData = data.map((d) => ({
      time: d.time as Time,
      value: d.volume || 0,
      color: d.close >= d.open ? 'rgba(0, 230, 118, 0.3)' : 'rgba(255, 82, 82, 0.3)',
    }))
    volumeSeriesRef.current.setData(volumeData)

    // Auto-fit when data length changes significantly (timeframe switch) or on initial load
    if (chartRef.current) {
      const lengthChanged = Math.abs(data.length - prevDataLength.current) > 5
      if (lengthChanged || prevDataLength.current === 0) {
        chartRef.current.timeScale().fitContent()
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
  }, [indicators])

  // Update markers - filter when hovering to show only active trade
  useEffect(() => {
    if (!candleSeriesRef.current || !markers?.length) return

    try {
      let displayMarkers = markers
      
      // When hovering, only show the active trade pair (entry + exit)
      if (activeSignalId) {
        displayMarkers = markers.filter(m => m.signal_id === activeSignalId)
      }
      
      candleSeriesRef.current.setMarkers(
        displayMarkers.map((m) => {
          // For exits: position based on trade direction for better visibility
          // Long exits go above candles, Short exits go below candles
          let position = m.position
          if (m.kind === 'exit') {
            position = m.direction === 'long' ? 'aboveBar' : 'belowBar'
          }
          
          // Muted color scheme with opacity - markers blend better
          // Entries: Semi-transparent white/gray
          // Exits: Muted teal (win) / Muted coral (loss)
          let color = m.color
          if (m.kind === 'entry') {
            color = 'rgba(180, 180, 180, 0.8)'  // Muted gray for entries
          } else if (m.kind === 'exit') {
            const isWin = (m.pnl || 0) >= 0
            color = isWin ? 'rgba(100, 200, 180, 0.8)' : 'rgba(220, 140, 100, 0.8)'  // Muted teal/coral
          }
          
          return {
            time: m.time as any,
            position,
            color,
            // Entries use arrows, exits use circles
            shape: m.kind === 'exit' ? 'circle' : m.shape,
            // Clean look - no text
            text: '',
          }
        })
      )
    } catch (e) {
      console.warn('Failed to set markers:', e)
    }
  }, [markers, activeSignalId])

  // Draw connection line between entry and exit when hovering
  useEffect(() => {
    if (!connectionLineRef.current || !markers) return

    if (activeSignalId) {
      // Find entry and exit for this trade
      const entry = markers.find(m => m.signal_id === activeSignalId && m.kind === 'entry')
      const exit = markers.find(m => m.signal_id === activeSignalId && m.kind === 'exit')
      
      if (entry && exit) {
        const entryPrice = entry.entry_price || 0
        const exitPrice = exit.exit_price || 0
        const isWin = (exit.pnl || 0) >= 0
        
        // Set line color based on win/loss - bright colors to stand out
        connectionLineRef.current.applyOptions({
          color: isWin ? '#00ff88' : '#ff3333',
          lineWidth: 2,
          lineStyle: 2, // dotted
        })
        
        // Draw RIGHT ANGLE step line (doesn't cover candles)
        // Pattern: entry → horizontal → vertical step → horizontal → exit
        // Use entry time + small offset for vertical step to maintain ascending order
        const stepTime = entry.time + 300 // 5 minutes after entry (one bar on 5m)
        
        // Only draw step line if there's enough time gap
        if (exit.time > stepTime) {
          connectionLineRef.current.setData([
            { time: entry.time as Time, value: entryPrice },      // Start at entry
            { time: stepTime as Time, value: entryPrice },        // Horizontal short distance
            { time: (stepTime + 1) as Time, value: exitPrice },   // Vertical step (+1 sec for ascending)
            { time: exit.time as Time, value: exitPrice },        // Horizontal to exit
          ])
        } else {
          // If entry and exit are too close, just draw simple diagonal
          connectionLineRef.current.setData([
            { time: entry.time as Time, value: entryPrice },
            { time: exit.time as Time, value: exitPrice },
          ])
        }
      } else {
        connectionLineRef.current.setData([])
      }
    } else {
      // Clear connection line when not hovering
      connectionLineRef.current.setData([])
    }
  }, [activeSignalId, markers])

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

  return (
    <div 
      ref={containerRef} 
      className={`chart-container-inner ${activeSignalId ? 'trade-focused' : ''}`}
      style={{ width: '100%', height: '100%', minHeight: 500, position: 'relative' }}
    >
      {/* Marker Tooltip */}
      {tooltip.visible && tooltip.marker && (
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
          
          {/* PEARL Logo */}
          <img src="/pearl-emoji.png" alt="" className="tooltip-logo" />
        </div>
      )}
    </div>
  )
}
