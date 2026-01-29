'use client'

import { useEffect, useRef, useState, useMemo } from 'react'
import { createChart, ColorType, CrosshairMode, IChartApi, ISeriesApi } from 'lightweight-charts'

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
}

interface TooltipState {
  visible: boolean
  x: number
  y: number
  marker: MarkerData | null
}

export default function CandlestickChart({ data, indicators, markers }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const ema9SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const ema21SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false,
    x: 0,
    y: 0,
    marker: null,
  })

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
        visible: false,  // Hide x-axis - RSI panel shows the timeline
        borderColor: '#2a2a3a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: 8,
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

    // Candlestick series
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

    // VWAP line (purple, dashed)
    const vwapSeries = chart.addLineSeries({
      color: '#ab47bc',
      lineWidth: 2,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries
    ema9SeriesRef.current = ema9Series
    ema21SeriesRef.current = ema21Series
    vwapSeriesRef.current = vwapSeries

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
      chart.remove()
    }
  }, [])

  // Subscribe to crosshair move for tooltip
  useEffect(() => {
    if (!chartRef.current || !containerRef.current) return

    const chart = chartRef.current
    const container = containerRef.current

    const handleCrosshairMove = (param: any) => {
      if (!param.time || !param.point) {
        setTooltip((prev) => ({ ...prev, visible: false }))
        return
      }

      const time = typeof param.time === 'object' ? param.time.valueOf() : param.time
      const markersAtTime = markersByTime.get(time)

      if (markersAtTime && markersAtTime.length > 0) {
        // Show tooltip near the crosshair
        const containerRect = container.getBoundingClientRect()
        let x = param.point.x + 15
        let y = param.point.y - 10

        // Clamp to container bounds
        const tooltipWidth = 220
        const tooltipHeight = 120
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
          marker: markersAtTime[0], // Show first marker if multiple
        })
      } else {
        setTooltip((prev) => ({ ...prev, visible: false }))
      }
    }

    chart.subscribeCrosshairMove(handleCrosshairMove)

    return () => {
      chart.unsubscribeCrosshairMove(handleCrosshairMove)
    }
  }, [markersByTime])

  // Update candle data
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !data?.length) return

    candleSeriesRef.current.setData(data)

    const volumeData = data.map((d) => ({
      time: d.time,
      value: d.volume || 0,
      color: d.close >= d.open ? 'rgba(0, 230, 118, 0.3)' : 'rgba(255, 82, 82, 0.3)',
    }))
    volumeSeriesRef.current.setData(volumeData)

    chartRef.current?.timeScale().scrollToRealTime()
  }, [data])

  // Update indicators
  useEffect(() => {
    if (!indicators) return

    if (ema9SeriesRef.current && indicators.ema9?.length) {
      ema9SeriesRef.current.setData(indicators.ema9)
    }
    if (ema21SeriesRef.current && indicators.ema21?.length) {
      ema21SeriesRef.current.setData(indicators.ema21)
    }
    if (vwapSeriesRef.current && indicators.vwap?.length) {
      vwapSeriesRef.current.setData(indicators.vwap)
    }
  }, [indicators])

  // Update markers
  useEffect(() => {
    if (!candleSeriesRef.current || !markers?.length) return

    try {
      candleSeriesRef.current.setMarkers(
        markers.map((m) => ({
          time: m.time as any,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }))
      )
    } catch (e) {
      console.warn('Failed to set markers:', e)
    }
  }, [markers])

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

  // Truncate reason string
  const truncateReason = (reason?: string, maxLen = 60) => {
    if (!reason) return ''
    if (reason.length <= maxLen) return reason
    return reason.slice(0, maxLen) + '…'
  }

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: 500, position: 'relative' }}>
      {/* Marker Tooltip */}
      {tooltip.visible && tooltip.marker && (
        <div
          className="marker-tooltip"
          style={{
            position: 'absolute',
            left: tooltip.x,
            top: tooltip.y,
            pointerEvents: 'none',
          }}
        >
          <div className="tooltip-header">
            <span className={`tooltip-kind ${tooltip.marker.kind}`}>
              {tooltip.marker.kind === 'entry' ? '▶ Entry' : '◀ Exit'}
            </span>
            <span className={`tooltip-direction ${tooltip.marker.direction}`}>
              {tooltip.marker.direction?.toUpperCase()}
            </span>
          </div>
          <div className="tooltip-row">
            <span className="tooltip-label">ID</span>
            <span className="tooltip-value">{tooltip.marker.signal_id?.slice(0, 16)}…</span>
          </div>
          {tooltip.marker.kind === 'entry' && (
            <>
              <div className="tooltip-row">
                <span className="tooltip-label">Price</span>
                <span className="tooltip-value">{formatPrice(tooltip.marker.entry_price)}</span>
              </div>
              {tooltip.marker.reason && (
                <div className="tooltip-reason">{truncateReason(tooltip.marker.reason)}</div>
              )}
            </>
          )}
          {tooltip.marker.kind === 'exit' && (
            <>
              <div className="tooltip-row">
                <span className="tooltip-label">Price</span>
                <span className="tooltip-value">{formatPrice(tooltip.marker.exit_price)}</span>
              </div>
              <div className="tooltip-row">
                <span className="tooltip-label">P&L</span>
                <span className={`tooltip-value ${(tooltip.marker.pnl || 0) >= 0 ? 'positive' : 'negative'}`}>
                  {formatPnL(tooltip.marker.pnl)}
                </span>
              </div>
              {tooltip.marker.exit_reason && (
                <div className="tooltip-reason">{tooltip.marker.exit_reason}</div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
