'use client'

import { useEffect, useRef, useCallback } from 'react'
import { createChart, ColorType, IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import type { IndicatorData } from '@/stores'
import { useChartSettingsStore } from '@/stores'

interface RSIPanelProps {
  data: IndicatorData[]
  barSpacing?: number
  mainChart?: IChartApi | null
  height?: number
}

export default function RSIPanel({
  data,
  barSpacing = 10,
  mainChart,
  height = 100
}: RSIPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const rsiSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const overboughtRef = useRef<ISeriesApi<'Line'> | null>(null)
  const oversoldRef = useRef<ISeriesApi<'Line'> | null>(null)
  const midlineRef = useRef<ISeriesApi<'Line'> | null>(null)

  const colors = useChartSettingsStore((s) => s.colors)

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: colors.background },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid },
        horzLines: { color: colors.grid },
      },
      rightPriceScale: {
        borderColor: colors.border,
        scaleMargins: { top: 0.1, bottom: 0.1 },
        autoScale: false,
      },
      timeScale: {
        visible: true,
        borderColor: colors.border,
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: barSpacing,
        tickMarkFormatter: (time: number) => {
          const date = new Date(time * 1000)
          return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
        },
      },
      crosshair: {
        vertLine: {
          color: colors.crosshair,
          width: 1,
          style: 3,
          labelBackgroundColor: colors.border,
        },
        horzLine: {
          color: colors.crosshair,
          width: 1,
          style: 3,
          labelBackgroundColor: colors.border,
        },
      },
    })

    // RSI line
    const rsiSeries = chart.addLineSeries({
      color: '#ab47bc',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
    })

    // Overbought line (70)
    const overbought = chart.addLineSeries({
      color: 'rgba(255, 82, 82, 0.6)',
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Oversold line (30)
    const oversold = chart.addLineSeries({
      color: 'rgba(0, 230, 118, 0.6)',
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Midline (50)
    const midline = chart.addLineSeries({
      color: 'rgba(255, 255, 255, 0.2)',
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Set fixed scale for RSI (0-100)
    chart.priceScale('right').applyOptions({
      autoScale: false,
      scaleMargins: { top: 0.05, bottom: 0.05 },
    })

    chartRef.current = chart
    rsiSeriesRef.current = rsiSeries
    overboughtRef.current = overbought
    oversoldRef.current = oversold
    midlineRef.current = midline

    // Handle resize
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: height,
        })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [barSpacing, colors, height])

  // Sync time scale with main chart
  useEffect(() => {
    if (!mainChart || !chartRef.current) return

    const handler = () => {
      if (!chartRef.current) return
      const mainTimeScale = mainChart.timeScale()
      const rsiTimeScale = chartRef.current.timeScale()

      // Sync visible range
      const visibleRange = mainTimeScale.getVisibleLogicalRange()
      if (visibleRange) {
        rsiTimeScale.setVisibleLogicalRange(visibleRange)
      }
    }

    mainChart.timeScale().subscribeVisibleLogicalRangeChange(handler)

    return () => {
      mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(handler)
    }
  }, [mainChart])

  // Update data
  useEffect(() => {
    if (!rsiSeriesRef.current || !overboughtRef.current ||
        !oversoldRef.current || !midlineRef.current || !data?.length) return

    const rsiData = data.map(d => ({ time: d.time as Time, value: d.value }))
    rsiSeriesRef.current.setData(rsiData)

    // Create horizontal lines for the full time range
    const overboughtData = data.map(d => ({ time: d.time as Time, value: 70 }))
    const oversoldData = data.map(d => ({ time: d.time as Time, value: 30 }))
    const midlineData = data.map(d => ({ time: d.time as Time, value: 50 }))

    overboughtRef.current.setData(overboughtData)
    oversoldRef.current.setData(oversoldData)
    midlineRef.current.setData(midlineData)

    // Auto-fit content
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent()
    }
  }, [data])

  // Get current RSI value for display
  const currentRSI = data.length > 0 ? data[data.length - 1].value : null
  const rsiColor = currentRSI
    ? currentRSI >= 70 ? '#ff5252'
      : currentRSI <= 30 ? '#00e676'
      : '#ab47bc'
    : '#ab47bc'

  return (
    <div className="indicator-panel rsi-panel">
      <div className="indicator-header">
        <div className="indicator-title">
          <span className="indicator-name">RSI</span>
          <span className="indicator-params">(14)</span>
        </div>
        <div className="indicator-values">
          {currentRSI !== null && (
            <span className="indicator-value" style={{ color: rsiColor }}>
              {currentRSI.toFixed(1)}
            </span>
          )}
          <span className="indicator-levels">
            <span className="level overbought">70</span>
            <span className="level-sep">/</span>
            <span className="level oversold">30</span>
          </span>
        </div>
      </div>
      <div ref={containerRef} className="indicator-chart" style={{ height: `${height}px` }} />
    </div>
  )
}
