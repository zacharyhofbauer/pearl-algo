'use client'

import { useEffect, useRef } from 'react'
import { createChart, ColorType, IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import type { MACDData } from '@/stores'
import { useChartSettingsStore } from '@/stores'

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
  height = 120
}: MACDPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const macdLineRef = useRef<ISeriesApi<'Line'> | null>(null)
  const signalLineRef = useRef<ISeriesApi<'Line'> | null>(null)
  const histogramRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const zeroLineRef = useRef<ISeriesApi<'Line'> | null>(null)
  const hasInitialFit = useRef(false)
  const prevDataLength = useRef(0)

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

    // Histogram (add first so it's behind the lines)
    const histogram = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
      priceScaleId: 'right',
    })

    // Zero line
    const zeroLine = chart.addLineSeries({
      color: 'rgba(255, 255, 255, 0.3)',
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // MACD line (blue)
    const macdLine = chart.addLineSeries({
      color: '#2196F3',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
    })

    // Signal line (orange)
    const signalLine = chart.addLineSeries({
      color: '#ff9800',
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
        chartRef.current.applyOptions({
          width: containerRef.current.clientWidth,
          height: height,
        })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      hasInitialFit.current = false
      chart.remove()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]) // Only recreate on height change - barSpacing/colors handled separately

  // Update barSpacing without recreating the chart
  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.timeScale().applyOptions({ barSpacing })
    }
  }, [barSpacing])

  // Update colors without recreating the chart
  useEffect(() => {
    if (chartRef.current) {
      chartRef.current.applyOptions({
        layout: {
          background: { type: ColorType.Solid, color: colors.background },
          textColor: colors.text,
        },
        grid: {
          vertLines: { color: colors.grid },
          horzLines: { color: colors.grid },
        },
      })
    }
  }, [colors])

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

  // Track previous state for optimized updates
  const prevLastTimeRef = useRef<number>(0)
  const updateThrottleRef = useRef<NodeJS.Timeout | null>(null)

  // Helper to get histogram color
  const getHistogramColor = (histogram: number, prevHistogram: number): string => {
    const isRising = histogram >= prevHistogram
    if (histogram >= 0) {
      return isRising ? '#26a69a' : '#1e8c7e'
    } else {
      return isRising ? '#ef5350' : '#c62828'
    }
  }

  // Update data - optimized to prevent flickering
  useEffect(() => {
    if (!macdLineRef.current || !signalLineRef.current ||
        !histogramRef.current || !zeroLineRef.current || !data?.length) return

    const lastPoint = data[data.length - 1]
    const prevPoint = data.length > 1 ? data[data.length - 2] : null
    const isInitialLoad = prevDataLength.current === 0
    const isTimeframeChange = Math.abs(data.length - prevDataLength.current) > 10
    const isSameTime = lastPoint.time === prevLastTimeRef.current
    
    // For real-time updates to the same time, use update()
    if (isSameTime && !isInitialLoad) {
      macdLineRef.current.update({ time: lastPoint.time as Time, value: lastPoint.macd })
      signalLineRef.current.update({ time: lastPoint.time as Time, value: lastPoint.signal })
      histogramRef.current.update({
        time: lastPoint.time as Time,
        value: lastPoint.histogram,
        color: getHistogramColor(lastPoint.histogram, prevPoint?.histogram || 0)
      })
      return
    }
    
    // For new data points, use update() if not a major change
    if (!isInitialLoad && !isTimeframeChange) {
      macdLineRef.current.update({ time: lastPoint.time as Time, value: lastPoint.macd })
      signalLineRef.current.update({ time: lastPoint.time as Time, value: lastPoint.signal })
      histogramRef.current.update({
        time: lastPoint.time as Time,
        value: lastPoint.histogram,
        color: getHistogramColor(lastPoint.histogram, prevPoint?.histogram || 0)
      })
      zeroLineRef.current.update({ time: lastPoint.time as Time, value: 0 })
      prevLastTimeRef.current = lastPoint.time
      prevDataLength.current = data.length
      return
    }
    
    // For initial load or timeframe change, do full setData with throttle
    if (updateThrottleRef.current) {
      clearTimeout(updateThrottleRef.current)
    }
    
    updateThrottleRef.current = setTimeout(() => {
      if (!macdLineRef.current || !signalLineRef.current ||
          !histogramRef.current || !zeroLineRef.current) return

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

      // Histogram data with colors
      const histogramData = data.map((d, i) => {
        const prevHistogram = i > 0 ? data[i - 1].histogram : 0
        return {
          time: d.time as Time,
          value: d.histogram,
          color: getHistogramColor(d.histogram, prevHistogram)
        }
      })
      histogramRef.current.setData(histogramData)

      // Zero line
      const zeroData = data.map(d => ({
        time: d.time as Time,
        value: 0
      }))
      zeroLineRef.current.setData(zeroData)

      if (chartRef.current && (!hasInitialFit.current || isTimeframeChange)) {
        chartRef.current.timeScale().fitContent()
        hasInitialFit.current = true
      }
      
      prevLastTimeRef.current = lastPoint.time
      prevDataLength.current = data.length
    }, isInitialLoad ? 0 : 100)

    return () => {
      if (updateThrottleRef.current) {
        clearTimeout(updateThrottleRef.current)
      }
    }
  }, [data])

  // Get current values for display
  const currentData = data.length > 0 ? data[data.length - 1] : null
  const macdColor = currentData
    ? currentData.macd >= currentData.signal ? '#26a69a' : '#ef5350'
    : '#8a94a6'
  const histColor = currentData
    ? currentData.histogram >= 0 ? '#26a69a' : '#ef5350'
    : '#8a94a6'

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
              <span className="indicator-value macd" style={{ color: '#2196F3' }}>
                {currentData.macd.toFixed(2)}
              </span>
              <span className="indicator-value signal" style={{ color: '#ff9800' }}>
                {currentData.signal.toFixed(2)}
              </span>
              <span className="indicator-value histogram" style={{ color: histColor }}>
                {currentData.histogram >= 0 ? '+' : ''}{currentData.histogram.toFixed(2)}
              </span>
            </>
          )}
        </div>
      </div>
      <div ref={containerRef} className="indicator-chart" style={{ height: `${height}px` }} />
    </div>
  )
}
