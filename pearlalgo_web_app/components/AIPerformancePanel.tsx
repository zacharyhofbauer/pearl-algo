'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { StatDisplay, InfoTooltip } from './ui'
import type {
  MLFilterPerformance,
  ShadowCounters,
  AIStatus,
} from '@/stores'

interface AIPerformancePanelProps {
  mlFilterPerformance: MLFilterPerformance | null
  shadowCounters: ShadowCounters | null
  aiStatus: AIStatus | null
}

export default function AIPerformancePanel({
  mlFilterPerformance,
  shadowCounters,
  aiStatus,
}: AIPerformancePanelProps) {
  const [showDetails, setShowDetails] = useState(false)

  // Calculate ML filter impact
  const getMLImpact = () => {
    if (!mlFilterPerformance) return null

    const passRate = mlFilterPerformance.win_rate_pass
    const failRate = mlFilterPerformance.win_rate_fail
    const passed = mlFilterPerformance.trades_passed
    const blocked = mlFilterPerformance.trades_blocked

    // Calculate lift (difference in win rates)
    let lift = null
    if (passRate !== undefined && failRate !== undefined) {
      lift = ((passRate - failRate) * 100).toFixed(1)
    }

    return { passRate, failRate, passed, blocked, lift }
  }

  const mlImpact = getMLImpact()

  // Get shadow mode stats
  const getShadowStats = () => {
    if (!shadowCounters) return null

    const wouldBlock = shadowCounters.would_block_total
    const byReason = shadowCounters.would_block_by_reason || {}
    const mlSkip = shadowCounters.ml_would_skip
    const mlTotal = shadowCounters.ml_total_decisions
    const executeRate = shadowCounters.ml_execute_rate

    return { wouldBlock, byReason, mlSkip, mlTotal, executeRate }
  }

  const shadowStats = getShadowStats()

  // Check if ML filter is providing value
  const isMLProvingValue = () => {
    if (!mlFilterPerformance) return null
    if (!mlFilterPerformance.lift_ok) return false
    return mlFilterPerformance.lift_win_rate !== undefined && mlFilterPerformance.lift_win_rate > 0.5
  }

  const mlValue = isMLProvingValue()

  // Get mode for display
  const getMode = () => {
    if (!mlFilterPerformance) return 'off'
    return mlFilterPerformance.mode || 'off'
  }

  const mode = getMode()

  // No data state
  if (!mlFilterPerformance && !shadowCounters) {
    return (
      <DataPanel title="AI Performance" icon="🧠" variant="feature">
        <div className="ai-performance-empty">
          <span className="empty-icon">🔮</span>
          <span className="empty-text">AI metrics collecting...</span>
        </div>
      </DataPanel>
    )
  }

  return (
    <DataPanel
      title="AI Performance"
      icon="🧠"
      variant="feature"
      badge={mode === 'shadow' ? 'SHADOW' : mode === 'live' ? 'LIVE' : undefined}
      badgeColor={mode === 'live' ? 'var(--accent-green)' : 'var(--accent-yellow)'}
    >
      <div className="ai-performance-panel">
        {/* ML Filter Win Rate Comparison */}
        {mlImpact && (mlImpact.passRate !== undefined || mlImpact.failRate !== undefined) && (
          <div className="ml-comparison">
            <div className="comparison-header">
              <span className="comparison-title">ML Filter Impact</span>
              {mlImpact.lift && (
                <span className={`lift-badge ${parseFloat(mlImpact.lift) > 0 ? 'positive' : 'negative'}`}>
                  {parseFloat(mlImpact.lift) > 0 ? '+' : ''}{mlImpact.lift}% lift
                </span>
              )}
            </div>

            <div className="comparison-bars">
              {/* Pass Win Rate */}
              <div className="comparison-row">
                <span className="row-label">PASS trades</span>
                <div className="bar-container">
                  <div
                    className="bar pass"
                    style={{ width: `${(mlImpact.passRate || 0) * 100}%` }}
                  >
                    <span className="bar-value">
                      {mlImpact.passRate !== undefined ? `${(mlImpact.passRate * 100).toFixed(0)}%` : '—'}
                    </span>
                  </div>
                </div>
                <span className="row-count">{mlImpact.passed} trades</span>
              </div>

              {/* Fail Win Rate */}
              <div className="comparison-row">
                <span className="row-label">FAIL trades</span>
                <div className="bar-container">
                  <div
                    className="bar fail"
                    style={{ width: `${(mlImpact.failRate || 0) * 100}%` }}
                  >
                    <span className="bar-value">
                      {mlImpact.failRate !== undefined ? `${(mlImpact.failRate * 100).toFixed(0)}%` : '—'}
                    </span>
                  </div>
                </div>
                <span className="row-count">{mlImpact.blocked} blocked</span>
              </div>
            </div>

            {/* Value Indicator */}
            <div className="ml-value-indicator">
              {mlValue === true && (
                <span className="value-badge positive">
                  <span className="value-icon">✓</span>
                  ML filter adding value
                </span>
              )}
              {mlValue === false && (
                <span className="value-badge negative">
                  <span className="value-icon">⚠</span>
                  ML lift not proven yet
                </span>
              )}
            </div>
          </div>
        )}

        {/* Shadow Mode Stats */}
        {shadowStats && shadowStats.wouldBlock > 0 && (
          <div className="shadow-impact">
            <div className="shadow-header">
              <span className="shadow-title">Shadow Mode Impact</span>
              <button
                className="details-btn"
                onClick={() => setShowDetails(!showDetails)}
              >
                {showDetails ? '−' : '+'}
              </button>
            </div>

            <div className="shadow-summary">
              <span className="shadow-main">
                Would have blocked <strong>{shadowStats.wouldBlock}</strong> signals
              </span>
              {shadowStats.mlSkip > 0 && (
                <span className="shadow-ml">
                  ML: {shadowStats.mlSkip}/{shadowStats.mlTotal} skipped
                </span>
              )}
            </div>

            {/* Detailed Breakdown */}
            {showDetails && Object.keys(shadowStats.byReason).length > 0 && (
              <div className="shadow-breakdown">
                {Object.entries(shadowStats.byReason).map(([reason, count]) => (
                  <div key={reason} className="breakdown-item">
                    <span className="breakdown-reason">{formatReason(reason)}</span>
                    <span className="breakdown-count">{count as number}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Execute Rate */}
            {shadowStats.executeRate !== undefined && (
              <div className="execute-rate">
                <span className="rate-label">Execute Rate:</span>
                <span className={`rate-value ${shadowStats.executeRate > 0.7 ? 'high' : shadowStats.executeRate > 0.4 ? 'medium' : 'low'}`}>
                  {(shadowStats.executeRate * 100).toFixed(0)}%
                </span>
              </div>
            )}
          </div>
        )}

        {/* Quick Stats Grid */}
        {mlFilterPerformance && (
          <div className="ai-quick-stats">
            {mlFilterPerformance.lift_win_rate !== undefined && (
              <div className="quick-stat">
                <span className="stat-label">Lift WR</span>
                <span className={`stat-value ${mlFilterPerformance.lift_win_rate > 0.5 ? 'positive' : 'neutral'}`}>
                  {(mlFilterPerformance.lift_win_rate * 100).toFixed(0)}%
                </span>
              </div>
            )}
            {mlFilterPerformance.lift_avg_pnl !== undefined && (
              <div className="quick-stat">
                <span className="stat-label">Lift P&L</span>
                <span className={`stat-value ${mlFilterPerformance.lift_avg_pnl >= 0 ? 'positive' : 'negative'}`}>
                  {mlFilterPerformance.lift_avg_pnl >= 0 ? '+' : ''}${mlFilterPerformance.lift_avg_pnl.toFixed(0)}
                </span>
              </div>
            )}
            <div className="quick-stat">
              <span className="stat-label">Status</span>
              <span className={`stat-value ${mlFilterPerformance.lift_ok ? 'positive' : 'warning'}`}>
                {mlFilterPerformance.lift_ok ? '✓ OK' : '— Testing'}
              </span>
            </div>
          </div>
        )}
      </div>
    </DataPanel>
  )
}

// Helper to format reason strings
function formatReason(reason: string): string {
  const labels: Record<string, string> = {
    direction_gating: 'Direction Gate',
    ml_filter: 'ML Filter',
    circuit_breaker: 'Circuit Breaker',
    session_filter: 'Session Filter',
    max_positions: 'Max Positions',
    regime_mismatch: 'Regime',
    cooldown: 'Cooldown',
  }
  return labels[reason] || reason.replace(/_/g, ' ')
}
