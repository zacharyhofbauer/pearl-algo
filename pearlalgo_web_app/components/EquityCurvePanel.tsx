'use client'

import { useEffect, useRef } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { StatDisplay } from './ui'
import { formatPnL } from '@/lib/formatters'
import type { EquityCurvePoint } from '@/stores'
import { getChartColors } from '@/utils/chartColors'

interface EquityCurvePanelProps {
  equityCurve: EquityCurvePoint[]
}

export default function EquityCurvePanel({ equityCurve }: EquityCurvePanelProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<any>(null)

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!containerRef.current || equityCurve.length === 0) return

    const { createChart, ColorType } = require('lightweight-charts')

    // Remove existing chart safely
    if (chartRef.current) {
      try {
        chartRef.current.remove()
      } catch (e) {
        // Chart already removed
      }
      chartRef.current = null
    }

    // Get colors from tokens (U1.2)
    const chartColors = getChartColors()

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 100,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: chartColors.textColor,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: chartColors.gridColor, style: 1 },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        visible: false,
        borderVisible: false,
      },
      crosshair: {
        horzLine: { visible: false },
        vertLine: { visible: false },
      },
      handleScale: false,
      handleScroll: false,
    })

    // Determine if overall P&L is positive or negative
    const lastValue = equityCurve[equityCurve.length - 1]?.value ?? 0
    const isPositive = lastValue >= 0

    // Area series with gradient
    const series = chart.addAreaSeries({
      lineColor: isPositive ? chartColors.equityLineUp : chartColors.equityLineDown,
      topColor: isPositive ? chartColors.equityAreaUpTop : chartColors.equityAreaDownTop,
      bottomColor: isPositive ? chartColors.equityAreaUpBottom : chartColors.equityAreaDownBottom,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    })

    series.setData(equityCurve)
    chart.timeScale().fitContent()

    chartRef.current = chart

    // Handle resize
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      try {
        chart.remove()
      } catch (e) {
        // Chart already removed
      }
    }
  }, [equityCurve])

  // Calculate summary stats (with safety for empty arrays)
  const lastValue = equityCurve.length > 0 ? equityCurve[equityCurve.length - 1]?.value ?? 0 : 0
  const values = equityCurve.map(p => p.value)
  const maxValue = values.length > 0 ? Math.max(...values) : 0
  const minValue = values.length > 0 ? Math.min(...values) : 0

  // Calculate gap from peak
  const gapFromPeak = lastValue - maxValue
  const showPeakGap = maxValue > 0 && gapFromPeak < -1 // Only show if down more than $1 from peak

  return (
    <DataPanel title="Equity Curve (72h)" icon="📈">
      <div className="equity-curve-container">
        <div className="grid grid-cols-3 gap-sm">
          <StatDisplay
            label="Current"
            value={formatPnL(lastValue)}
            variant="compact"
            colorMode="financial"
            positive={lastValue >= 0}
            negative={lastValue < 0}
          />
          <StatDisplay
            label="Peak"
            value={formatPnL(maxValue)}
            variant="compact"
            positive
          />
          <StatDisplay
            label="Trough"
            value={formatPnL(minValue)}
            variant="compact"
            negative
          />
        </div>
        {showPeakGap && (
          <div className="peak-gap-indicator">
            {formatPnL(gapFromPeak)} from peak
          </div>
        )}
        <div ref={containerRef} className="equity-curve-chart" />
      </div>
    </DataPanel>
  )
}
