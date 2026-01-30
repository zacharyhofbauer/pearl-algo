'use client'

import { DataPanel } from './DataPanelsContainer'

interface RiskMetrics {
  max_drawdown: number
  max_drawdown_pct: number
  sharpe_ratio: number | null
  profit_factor: number | null
  avg_win: number
  avg_loss: number
  avg_rr: number | null
  largest_win: number
  largest_loss: number
  expectancy: number
}

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

  return (
    <DataPanel title="Risk Metrics" icon="⚖️">
      <div className="stats-grid risk-metrics-grid">
        <div className="stat-item">
          <span className="stat-item-label">Max Drawdown</span>
          <span className="stat-item-value negative">
            ${riskMetrics.max_drawdown.toFixed(2)}
            <span className="stat-sub">({riskMetrics.max_drawdown_pct.toFixed(1)}%)</span>
          </span>
        </div>

        <div className="stat-item">
          <span className="stat-item-label">Sharpe Ratio</span>
          <span className={`stat-item-value ${riskMetrics.sharpe_ratio && riskMetrics.sharpe_ratio > 0 ? 'positive' : ''}`}>
            {formatRatio(riskMetrics.sharpe_ratio)}
          </span>
        </div>

        <div className="stat-item">
          <span className="stat-item-label">Profit Factor</span>
          <span className={`stat-item-value ${riskMetrics.profit_factor && riskMetrics.profit_factor > 1 ? 'positive' : 'negative'}`}>
            {formatRatio(riskMetrics.profit_factor)}
          </span>
        </div>

        <div className="stat-item">
          <span className="stat-item-label">Avg R:R</span>
          <span className={`stat-item-value ${riskMetrics.avg_rr && riskMetrics.avg_rr > 1 ? 'positive' : ''}`}>
            {formatRatio(riskMetrics.avg_rr)}
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

        <div className="stat-item stat-item-full">
          <span className="stat-item-label">Expectancy (per trade)</span>
          <span className={`stat-item-value ${riskMetrics.expectancy >= 0 ? 'positive' : 'negative'}`}>
            {formatCurrency(riskMetrics.expectancy)}
          </span>
        </div>
      </div>
    </DataPanel>
  )
}
