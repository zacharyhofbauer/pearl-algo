'use client'

import { DataPanel } from './DataPanelsContainer'
import type { RiskMetrics } from '@/stores'

interface RiskMetricsPanelProps {
  riskMetrics: RiskMetrics
}

// Info tooltip component
function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="tooltip-wrapper">
      <span className="info-icon">?</span>
      <span className="tooltip-content">{text}</span>
    </span>
  )
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
        <div className="stats-grid risk-metrics-grid">
          <div className="stat-item">
            <span className="stat-item-label">
              Expectancy
              <InfoTooltip text="Average profit per trade" />
            </span>
            <span className={`stat-item-value ${riskMetrics.expectancy >= 0 ? 'positive' : 'negative'}`}>
              {formatCurrency(riskMetrics.expectancy)}
            </span>
          </div>

          <div className="stat-item">
            <span className="stat-item-label">
              Profit Factor
              <InfoTooltip text="Gross profit / Gross loss" />
            </span>
            <span className={`stat-item-value ${riskMetrics.profit_factor && riskMetrics.profit_factor > 1 ? 'positive' : 'negative'}`}>
              {formatRatio(riskMetrics.profit_factor)}
            </span>
          </div>

          <div className="stat-item">
            <span className="stat-item-label">Avg Win</span>
            <span className="stat-item-value positive">
              {formatCurrency(riskMetrics.avg_win)}
            </span>
          </div>

          <div className="stat-item">
            <span className="stat-item-label">Avg Loss</span>
            <span className="stat-item-value negative">
              {formatCurrency(riskMetrics.avg_loss)}
            </span>
          </div>
        </div>
      </div>

      {/* Risk Section */}
      <div className="metrics-section">
        <div className="metrics-section-header">Risk</div>
        <div className="stats-grid risk-metrics-grid">
          <div className="stat-item">
            <span className="stat-item-label">Max Drawdown</span>
            <span className="stat-item-value negative">
              ${riskMetrics.max_drawdown.toFixed(2)}
              <span className="stat-sub">({riskMetrics.max_drawdown_pct.toFixed(1)}%)</span>
            </span>
          </div>

          <div className="stat-item">
            <span className="stat-item-label">
              Sharpe Ratio
              <InfoTooltip text="Risk-adjusted return" />
            </span>
            <span className={`stat-item-value ${riskMetrics.sharpe_ratio && riskMetrics.sharpe_ratio > 0 ? 'positive' : ''}`}>
              {formatRatio(riskMetrics.sharpe_ratio)}
              {riskMetrics.sharpe_ratio !== null && riskMetrics.sharpe_ratio >= 1.5 && (
                <span className="quality-badge excellent">Excellent</span>
              )}
              {riskMetrics.sharpe_ratio !== null && riskMetrics.sharpe_ratio >= 1 && riskMetrics.sharpe_ratio < 1.5 && (
                <span className="quality-badge good">Good</span>
              )}
            </span>
          </div>

          <div className="stat-item">
            <span className="stat-item-label">
              Avg R:R
              <InfoTooltip text="Average reward-to-risk ratio" />
            </span>
            <span className={`stat-item-value ${riskMetrics.avg_rr && riskMetrics.avg_rr > 1 ? 'positive' : ''}`}>
              {formatRatio(riskMetrics.avg_rr)}
            </span>
          </div>
        </div>
      </div>

      {/* Trade Stats Section */}
      <div className="metrics-section">
        <div className="metrics-section-header">Trade Stats</div>
        <div className="stats-grid risk-metrics-grid">
          <div className="stat-item">
            <span className="stat-item-label">Best Trade</span>
            <span className="stat-item-value positive">
              {formatCurrency(riskMetrics.largest_win)}
            </span>
          </div>

          <div className="stat-item">
            <span className="stat-item-label">Worst Trade</span>
            <span className="stat-item-value negative">
              {formatCurrency(riskMetrics.largest_loss)}
            </span>
          </div>
        </div>
      </div>

      {/* Exposure Section */}
      {(riskMetrics.max_concurrent_positions_peak !== undefined ||
        riskMetrics.max_stop_risk_exposure !== undefined ||
        (riskMetrics.top_losses && riskMetrics.top_losses.length > 0)) && (
        <div className="metrics-section">
          <div className="metrics-section-header">Exposure</div>
          <div className="stats-grid risk-metrics-grid">
            {riskMetrics.max_concurrent_positions_peak !== undefined && (
              <div className="stat-item">
                <span className="stat-item-label">Peak Positions</span>
                <span className="stat-item-value">
                  {riskMetrics.max_concurrent_positions_peak}
                </span>
              </div>
            )}

            {riskMetrics.max_stop_risk_exposure !== undefined && (
              <div className="stat-item">
                <span className="stat-item-label">
                  Max Stop Risk
                  <InfoTooltip text="Total $ at risk if all stops hit" />
                </span>
                <span className="stat-item-value negative">
                  ${riskMetrics.max_stop_risk_exposure.toFixed(2)}
                </span>
              </div>
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
