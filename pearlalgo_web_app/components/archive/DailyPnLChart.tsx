'use client'

import React, { useEffect, useRef } from 'react'
import { createChart, IChartApi, HistogramData } from 'lightweight-charts'

interface DayData {
  day: string
  pnl: number
  trades: number
  wins: number
}

interface DailyPnLChartProps {
  data: DayData[]
  height?: number
}

const DailyPnLChart = React.memo(function DailyPnLChart({ data, height = 200 }: DailyPnLChartProps) {
  const chartRef = useRef<HTMLDivElement>(null)
  const chartApiRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!chartRef.current || data.length === 0) return

    const chart = createChart(chartRef.current, {
      height,
      localization: {
        timeFormatter: (time: number) => new Date(time * 1000).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' }),
      },
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

    const barData: HistogramData[] = data.map((d) => ({
      time: d.day as string,
      value: d.pnl,
      color: d.pnl >= 0 ? 'rgba(0, 230, 118, 0.7)' : 'rgba(255, 82, 82, 0.7)',
    }))

    const series = chart.addHistogramSeries({
      priceFormat: { type: 'price', precision: 0, minMove: 1 },
    })
    series.setData(barData)

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
    return <div className="archive-chart-placeholder">No daily data</div>
  }

  return <div ref={chartRef} className="archive-daily-pnl-chart" />
})
export default DailyPnLChart
