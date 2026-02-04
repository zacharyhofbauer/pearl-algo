'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { StatDisplay } from './ui'
import type { EquityCurvePoint, RiskMetrics } from '@/stores'

interface RiskEquityPanelProps {
  riskMetrics: RiskMetrics | null
  equityCurve: EquityCurvePoint[]
}

type Tab = 'risk' | 'equity'

export default function RiskEquityPanel({ riskMetrics, equityCurve }: RiskEquityPanelProps) {
  const [tab, setTab] = useState<Tab>(() => {
    if (riskMetrics) return 'risk'
    if (equityCurve && equityCurve.length > 0) return 'equity'
    return 'risk'
  })

  // Lightweight-charts instance (created only when Equity tab is open)
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<any>(null)

  useEffect(() => {
    if (typeof window === 'undefined') return

    // Clean up chart when leaving Equity tab
    if (tab !== 'equity') {
      if (chartRef.current) {
        try {
          chartRef.current.remove()
        } catch {
          // ignore
        }
        chartRef.current = null
      }
      return
    }

    if (!containerRef.current || equityCurve.length === 0) return

    const { createChart, ColorType } = require('lightweight-charts')

    // Remove existing chart safely
    if (chartRef.current) {
      try {
        chartRef.current.remove()
      } catch {
        // ignore
      }
      chartRef.current = null
    }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 100,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: '#8a94a6',
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: '#1e222d', style: 1 },
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

    const lastValue = equityCurve[equityCurve.length - 1]?.value ?? 0
    const isPositive = lastValue >= 0

    const series = chart.addAreaSeries({
      lineColor: isPositive ? '#00e676' : '#ff5252',
      topColor: isPositive ? 'rgba(0, 230, 118, 0.3)' : 'rgba(255, 82, 82, 0.3)',
      bottomColor: isPositive ? 'rgba(0, 230, 118, 0.0)' : 'rgba(255, 82, 82, 0.0)',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
    })

    series.setData(equityCurve)
    chart.timeScale().fitContent()

    chartRef.current = chart

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
      } catch {
        // ignore
      }
      chartRef.current = null
    }
  }, [tab, equityCurve])

  const equityStats = useMemo(() => {
    const lastValue = equityCurve.length > 0 ? equityCurve[equityCurve.length - 1]?.value ?? 0 : 0
    const values = equityCurve.map((p) => p.value)
    const maxValue = values.length > 0 ? Math.max(...values) : 0
    const minValue = values.length > 0 ? Math.min(...values) : 0
    const gapFromPeak = lastValue - maxValue
    const showPeakGap = maxValue > 0 && gapFromPeak < -1

    return { lastValue, maxValue, minValue, gapFromPeak, showPeakGap }
  }, [equityCurve])

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  const formatCurrency = (value: number) => {
    const sign = value >= 0 ? '+' : ''
    return `${sign}$${value.toFixed(2)}`
  }

  const formatRatio = (value: number | null) => {
    if (value === null) return '—'
    return value.toFixed(2)
  }

  const formatExitReason = (reason: string): string => {
    if (!reason) return ''
    const lowerReason = reason.toLowerCase()

    if (lowerReason.includes('close_all') || lowerReason.includes('close all')) return 'Manual'
    if (lowerReason.includes('stop') || lowerReason.includes('sl_')) return 'Stop Loss'
    if (lowerReason.includes('target') || lowerReason.includes('tp_') || lowerReason.includes('profit')) return 'Target'
    if (lowerReason.includes('trail')) return 'Trail'
    if (lowerReason.includes('time') || lowerReason.includes('eod') || lowerReason.includes('session')) return 'Time'

    const formatted = reason.replace(/_/g, ' ')
    return formatted.length > 12 ? `${formatted.substring(0, 12)}...` : formatted
  }

  const renderRisk = () => {
    if (!riskMetrics) {
      return <div className="no-data-message">No risk metrics available</div>
    }

    return (
      <>
        <div className="metrics-section">
          <div className="metrics-section-header">Profitability</div>
          <div className="grid grid-cols-2 gap-md">
            <StatDisplay
              label="Expectancy"
              value={formatCurrency(riskMetrics.expectancy)}
              colorMode="financial"
              positive={riskMetrics.expectancy >= 0}
              negative={riskMetrics.expectancy < 0}
              tooltip="Average profit per trade"
            />
            <StatDisplay
              label="Profit Factor"
              value={formatRatio(riskMetrics.profit_factor)}
              colorMode="financial"
              positive={riskMetrics.profit_factor !== null && riskMetrics.profit_factor > 1}
              negative={riskMetrics.profit_factor !== null && riskMetrics.profit_factor <= 1}
              tooltip="Gross profit / Gross loss"
            />
            <StatDisplay label="Avg Win" value={formatCurrency(riskMetrics.avg_win)} positive />
            <StatDisplay label="Avg Loss" value={formatCurrency(riskMetrics.avg_loss)} negative />
          </div>
        </div>

        <div className="metrics-section">
          <div className="metrics-section-header">Risk</div>
          <div className="grid grid-cols-2 gap-md">
            <StatDisplay
              label="Max Drawdown"
              value={
                <>
                  ${riskMetrics.max_drawdown.toFixed(2)}
                  <span className="stat-sub">({riskMetrics.max_drawdown_pct.toFixed(1)}%)</span>
                </>
              }
              negative
            />
            <StatDisplay
              label="Sharpe Ratio"
              value={formatRatio(riskMetrics.sharpe_ratio)}
              colorMode="financial"
              positive={riskMetrics.sharpe_ratio !== null && riskMetrics.sharpe_ratio > 0}
              tooltip="Risk-adjusted return"
            />
            <StatDisplay
              label="Avg R:R"
              value={formatRatio(riskMetrics.avg_rr)}
              colorMode="financial"
              positive={riskMetrics.avg_rr !== null && riskMetrics.avg_rr > 1}
              tooltip="Average reward-to-risk ratio"
            />
          </div>
        </div>

        <div className="metrics-section">
          <div className="metrics-section-header">Trade Stats</div>
          <div className="grid grid-cols-2 gap-md">
            <StatDisplay label="Best Trade" value={formatCurrency(riskMetrics.largest_win)} positive />
            <StatDisplay label="Worst Trade" value={formatCurrency(riskMetrics.largest_loss)} negative />
          </div>
        </div>

        {(riskMetrics.max_concurrent_positions_peak !== undefined ||
          riskMetrics.max_stop_risk_exposure !== undefined ||
          (riskMetrics.top_losses && riskMetrics.top_losses.length > 0)) && (
          <div className="metrics-section">
            <div className="metrics-section-header">Exposure</div>
            <div className="grid grid-cols-2 gap-md">
              {riskMetrics.max_concurrent_positions_peak !== undefined && (
                <StatDisplay label="Peak Positions" value={riskMetrics.max_concurrent_positions_peak} />
              )}
              {riskMetrics.max_stop_risk_exposure !== undefined && (
                <StatDisplay
                  label="Max Stop Risk"
                  value={`$${riskMetrics.max_stop_risk_exposure.toFixed(2)}`}
                  negative
                  tooltip="Total $ at risk if all stops hit"
                />
              )}
            </div>

            {riskMetrics.top_losses && riskMetrics.top_losses.length > 0 && (
              <div className="top-losses-section">
                <div className="top-losses-header">Top 3 Losses</div>
                <div className="top-losses-list">
                  {riskMetrics.top_losses.map((loss, idx) => (
                    <div key={loss.signal_id} className="top-loss-item">
                      <span className="top-loss-rank">#{idx + 1}</span>
                      <span className="top-loss-pnl negative">${Math.abs(loss.pnl).toFixed(2)}</span>
                      <span className="top-loss-reason">{formatExitReason(loss.exit_reason)}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </>
    )
  }

  const renderEquity = () => {
    if (!equityCurve || equityCurve.length === 0) {
      return <div className="no-data-message">No equity curve data available</div>
    }

    return (
      <div className="equity-curve-container">
        <div className="grid grid-cols-3 gap-sm">
          <StatDisplay
            label="Current"
            value={formatPnL(equityStats.lastValue)}
            variant="compact"
            colorMode="financial"
            positive={equityStats.lastValue >= 0}
            negative={equityStats.lastValue < 0}
          />
          <StatDisplay label="Peak" value={formatPnL(equityStats.maxValue)} variant="compact" positive />
          <StatDisplay label="Trough" value={formatPnL(equityStats.minValue)} variant="compact" negative />
        </div>

        {equityStats.showPeakGap && (
          <div className="peak-gap-indicator">{formatPnL(equityStats.gapFromPeak)} from peak</div>
        )}

        <div ref={containerRef} className="equity-curve-chart" />
      </div>
    )
  }

  const showTabs = (riskMetrics !== null) && (equityCurve.length > 0)

  return (
    <DataPanel title="Risk & Equity" icon="🧮">
      {showTabs && (
        <div className="perf-tabs" role="tablist" aria-label="Risk and equity tabs">
          <button
            type="button"
            className={`perf-tab ${tab === 'risk' ? 'active' : ''}`}
            onClick={() => setTab('risk')}
            role="tab"
            aria-selected={tab === 'risk'}
          >
            Risk
          </button>
          <button
            type="button"
            className={`perf-tab ${tab === 'equity' ? 'active' : ''}`}
            onClick={() => setTab('equity')}
            role="tab"
            aria-selected={tab === 'equity'}
          >
            Equity (72h)
          </button>
        </div>
      )}

      {tab === 'equity' ? renderEquity() : renderRisk()}
    </DataPanel>
  )
}

