'use client'

import { useEffect, useRef } from 'react'
import { createChart, ColorType, IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import type { MACDData } from '@/stores'
import { useChartSettingsStore } from '@/stores'
import { getChartColors } from '@/utils/chartColors'

interface MACDPanelProps {
  data: MACDData[]
  barSpacing?: number
  mainChart?: IChartApi | null
  height?: number
}

export default function MACDPanel({
  data,
  barSpacing = 10,
  mainChart,
  height
}: MACDPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const macdLineRef = useRef<ISeriesApi<'Line'> | null>(null)
  const signalLineRef = useRef<ISeriesApi<'Line'> | null>(null)
  const histogramRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const zeroLineRef = useRef<ISeriesApi<'Line'> | null>(null)

  const colors = useChartSettingsStore((s) => s.colors)

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    // Use container height if available, otherwise fall back to prop or default
    const chartHeight = height || containerRef.current.clientHeight || 140

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: chartHeight,
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
        scaleMargins: { top: 0.15, bottom: 0.15 },
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

    // Get indicator colors from tokens (U1.2)
    const chartColors = getChartColors()

    // Histogram (add first so it's behind the lines)
    const histogram = chart.addHistogramSeries({
      color: chartColors.macdHistogramUp,
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      priceScaleId: 'right',
    })

    // Zero line
    const zeroLine = chart.addLineSeries({
      color: chartColors.macdZeroLine,
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // MACD line (blue)
    const macdLine = chart.addLineSeries({
      color: chartColors.macdLine,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
    })

    // Signal line (orange)
    const signalLine = chart.addLineSeries({
      color: chartColors.macdSignal,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
    })

    chartRef.current = chart
    macdLineRef.current = macdLine
    signalLineRef.current = signalLine
    histogramRef.current = histogram
    zeroLineRef.current = zeroLine

    // Handle resize
    const handleResize = () => {
      if (containerRef.current && chartRef.current) {
        const newHeight = height || containerRef.current.clientHeight || 140
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: newHeight,
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
      const macdTimeScale = chartRef.current.timeScale()

      const visibleRange = mainTimeScale.getVisibleLogicalRange()
      if (visibleRange) {
        macdTimeScale.setVisibleLogicalRange(visibleRange)
      }
    }

    mainChart.timeScale().subscribeVisibleLogicalRangeChange(handler)

    return () => {
      mainChart.timeScale().unsubscribeVisibleLogicalRangeChange(handler)
    }
  }, [mainChart])

  // Update data
  useEffect(() => {
    if (!macdLineRef.current || !signalLineRef.current ||
        !histogramRef.current || !zeroLineRef.current || !data?.length) return

    // MACD line data
    const macdData = data.map(d => ({
      time: d.time as Time,
      value: d.macd
    }))
    macdLineRef.current.setData(macdData)

    // Signal line data
    const signalData = data.map(d => ({
      time: d.time as Time,
      value: d.signal
    }))
    signalLineRef.current.setData(signalData)

    // Get colors for histogram (U1.2)
    const histColors = getChartColors()

    // Histogram data with colors based on value and direction
    const histogramData = data.map((d, i) => {
      const prevHistogram = i > 0 ? data[i - 1].histogram : 0
      const isRising = d.histogram >= prevHistogram

      let color: string
      if (d.histogram >= 0) {
        // Positive: green shades
        color = isRising ? histColors.macdHistogramUp : histColors.macdHistogramUpFade
      } else {
        // Negative: red shades
        color = isRising ? histColors.macdHistogramDown : histColors.macdHistogramDownFade
      }

      return {
        time: d.time as Time,
        value: d.histogram,
        color: color
      }
    })
    histogramRef.current.setData(histogramData)

    // Zero line
    const zeroData = data.map(d => ({
      time: d.time as Time,
      value: 0
    }))
    zeroLineRef.current.setData(zeroData)

    // Auto-fit content
    if (chartRef.current) {
      chartRef.current.timeScale().fitContent()
    }
  }, [data])

  // Get current values for display (U1.2 - use token colors)
  const displayColors = getChartColors()
  const currentData = data.length > 0 ? data[data.length - 1] : null
  const macdColor = currentData
    ? currentData.macd >= currentData.signal ? displayColors.macdHistogramUp : displayColors.macdHistogramDown
    : displayColors.textColor
  const histColor = currentData
    ? currentData.histogram >= 0 ? displayColors.macdHistogramUp : displayColors.macdHistogramDown
    : displayColors.textColor

  return (
    <div className="indicator-panel macd-panel">
      <div className="indicator-header">
        <div className="indicator-title">
          <span className="indicator-name">MACD</span>
          <span className="indicator-params">(12,26,9)</span>
        </div>
        <div className="indicator-values">
          {currentData && (
            <>
              <span className="indicator-value macd" style={{ color: displayColors.macdLine }}>
                {currentData.macd.toFixed(2)}
              </span>
              <span className="indicator-value signal" style={{ color: displayColors.macdSignal }}>
                {currentData.signal.toFixed(2)}
              </span>
              <span className="indicator-value histogram" style={{ color: histColor }}>
                {currentData.histogram >= 0 ? '+' : ''}{currentData.histogram.toFixed(2)}
              </span>
            </>
          )}
        </div>
      </div>
      <div ref={containerRef} className="indicator-chart" style={{ height: height ? `${height}px` : '100%', minHeight: '120px' }} />
    </div>
  )
}
