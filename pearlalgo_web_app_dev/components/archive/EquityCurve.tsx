'use client'

import React, { useEffect, useRef } from 'react'
import { createChart, IChartApi, LineData } from 'lightweight-charts'

interface DataPoint {
  time: string
  cumulative_pnl: number
}

interface EquityCurveProps {
  data: DataPoint[]
  height?: number
}

const EquityCurve = React.memo(function EquityCurve({ data, height = 280 }: EquityCurveProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartApiRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return

    const chart = createChart(chartRef.current, {
      height,
      layout: { background: { color: 'transparent' }, textColor: '#8a92a0' },
      grid: {
        vertLines: { color: 'rgba(255,255,255,0.04)' },
        horzLines: { color: 'rgba(255,255,255,0.04)' },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false },
      crosshair: {
        horzLine: { labelVisible: true },
        vertLine: { labelVisible: true },
      },
    })

    const lineData: LineData[] = data.map((d) => ({
      time: d.time.slice(0, 10) as string,
      value: d.cumulative_pnl,
    }))

    // Deduplicate by time (lightweight-charts requires unique times)
    const seen = new Set<string>()
    const deduped = lineData.filter((d) => {
      const key = d.time as string
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })

    const series = chart.addLineSeries({
      color: '#00d4ff',
      lineWidth: 2,
      crosshairMarkerVisible: true,
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    })
    series.setData(deduped)

    // Zero line
    series.createPriceLine({
      price: 0,
      color: 'rgba(255, 255, 255, 0.15)',
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: false,
    })

    chart.timeScale().fitContent()
    chartApiRef.current = chart

    return () => {
      chart.remove()
      chartApiRef.current = null
    }
  }, [data, height])

  if (data.length === 0) {
    return <div className="archive-chart-placeholder">No data</div>
  }

  return <div ref={chartRef} className="archive-equity-curve" />
})
export default EquityCurve
