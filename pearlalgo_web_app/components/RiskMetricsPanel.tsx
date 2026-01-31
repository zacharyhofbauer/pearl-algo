'use client'

import { DataPanel } from './DataPanelsContainer'
import { StatDisplay } from './ui'
import type { RiskMetrics } from '@/stores'

interface RiskMetricsPanelProps {
  riskMetrics: RiskMetrics
}

export default function RiskMetricsPanel({ riskMetrics }: RiskMetricsPanelProps) {
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

    if (lowerReason.includes('close_all') || lowerReason.includes('close all')) {
      return 'Manual'
    }
    if (lowerReason.includes('stop') || lowerReason.includes('sl_')) {
      return 'Stop Loss'
    }
    if (lowerReason.includes('target') || lowerReason.includes('tp_') || lowerReason.includes('profit')) {
      return 'Target'
    }
    if (lowerReason.includes('trail')) {
      return 'Trail'
    }
    if (lowerReason.includes('time') || lowerReason.includes('eod') || lowerReason.includes('session')) {
      return 'Time'
    }

    // Truncate long reasons
    const formatted = reason.replace(/_/g, ' ')
    return formatted.length > 12 ? formatted.substring(0, 12) + '...' : formatted
  }

  return (
    <DataPanel title="Risk Metrics" icon="⚖️">
      {/* Profitability Section */}
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

          <StatDisplay
            label="Avg Win"
            value={formatCurrency(riskMetrics.avg_win)}
            positive
          />

          <StatDisplay
            label="Avg Loss"
            value={formatCurrency(riskMetrics.avg_loss)}
            negative
          />
        </div>
      </div>

      {/* Risk Section */}
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
            value={
              <>
                {formatRatio(riskMetrics.sharpe_ratio)}
                {riskMetrics.sharpe_ratio !== null && riskMetrics.sharpe_ratio >= 1.5 && (
                  <span className="quality-badge excellent">Excellent</span>
                )}
                {riskMetrics.sharpe_ratio !== null && riskMetrics.sharpe_ratio >= 1 && riskMetrics.sharpe_ratio < 1.5 && (
                  <span className="quality-badge good">Good</span>
                )}
              </>
            }
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

      {/* Trade Stats Section */}
      <div className="metrics-section">
        <div className="metrics-section-header">Trade Stats</div>
        <div className="grid grid-cols-2 gap-md">
          <StatDisplay
            label="Best Trade"
            value={formatCurrency(riskMetrics.largest_win)}
            positive
          />

          <StatDisplay
            label="Worst Trade"
            value={formatCurrency(riskMetrics.largest_loss)}
            negative
          />
        </div>
      </div>

      {/* Exposure Section */}
      {(riskMetrics.max_concurrent_positions_peak !== undefined ||
        riskMetrics.max_stop_risk_exposure !== undefined ||
        (riskMetrics.top_losses && riskMetrics.top_losses.length > 0)) && (
        <div className="metrics-section">
          <div className="metrics-section-header">Exposure</div>
          <div className="grid grid-cols-2 gap-md">
            {riskMetrics.max_concurrent_positions_peak !== undefined && (
              <StatDisplay
                label="Peak Positions"
                value={riskMetrics.max_concurrent_positions_peak}
              />
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

          {/* Top 3 Losses */}
          {riskMetrics.top_losses && riskMetrics.top_losses.length > 0 && (
            <div className="top-losses-section">
              <div className="top-losses-header">Top 3 Losses</div>
              <div className="top-losses-list">
                {riskMetrics.top_losses.map((loss, idx) => (
                  <div key={loss.signal_id} className="top-loss-item">
                    <span className="top-loss-rank">#{idx + 1}</span>
                    <span className="top-loss-pnl negative">
                      ${Math.abs(loss.pnl).toFixed(2)}
                    </span>
                    <span className="top-loss-reason">
                      {formatExitReason(loss.exit_reason)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </DataPanel>
  )
}
