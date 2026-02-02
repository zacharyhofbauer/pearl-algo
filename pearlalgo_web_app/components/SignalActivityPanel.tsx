'use client'

import { useMemo, memo } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { formatMinutesAgo } from '@/lib/formatters'
import type { SignalActivity, LastSignalDecision } from '@/stores'

interface SignalActivityPanelProps {
  signalActivity: SignalActivity | null
  lastDecision: LastSignalDecision | null
}

function SignalActivityPanel({
  signalActivity,
  lastDecision,
}: SignalActivityPanelProps) {
  // Format time ago from minutes using centralized formatter
  const formatTimeAgo = (minutes: number | undefined) => {
    if (minutes === undefined || minutes === null) return '—'
    if (minutes < 1) return 'Just now'
    const formatted = formatMinutesAgo(minutes)
    return formatted === '—' ? '—' : `${formatted} ago`
  }

  // Get activity level indicator - memoized
  const activityLevel = useMemo(() => {
    if (!signalActivity) return { level: 'unknown', label: 'Unknown', color: 'var(--text-secondary)' }

    const signalsPerHour = signalActivity.signals_last_hour
    if (signalsPerHour >= 3) return { level: 'high', label: 'Active', color: 'var(--accent-green)' }
    if (signalsPerHour >= 1) return { level: 'medium', label: 'Moderate', color: 'var(--accent-yellow)' }
    if (signalsPerHour > 0) return { level: 'low', label: 'Quiet', color: 'var(--accent-yellow)' }
    return { level: 'none', label: 'Silent', color: 'var(--text-tertiary)' }
  }, [signalActivity])

  // Get quiet reason display - memoized
  const quietReason = useMemo(() => {
    if (!signalActivity?.quiet_reason) return null

    // Map internal reasons to user-friendly text
    const reasonMap: Record<string, string> = {
      'no_setup': 'No setup meets criteria',
      'market_closed': 'Market is closed',
      'session_filter': 'Outside trading session',
      'direction_blocked': 'Direction currently blocked',
      'cooldown': 'In cooldown period',
      'max_positions': 'Max positions reached',
      'low_volatility': 'Volatility too low',
      'high_volatility': 'Volatility too high',
      'regime_unfavorable': 'Market regime unfavorable',
      'waiting_for_setup': 'Waiting for valid setup',
    }

    return reasonMap[signalActivity.quiet_reason] || signalActivity.quiet_reason.replace(/_/g, ' ')
  }, [signalActivity?.quiet_reason])

  // No data state
  if (!signalActivity && !lastDecision) {
    return (
      <DataPanel title="Signal Activity" icon="📡" variant="status">
        <div className="signal-activity-empty">
          <span className="empty-icon">📊</span>
          <span className="empty-text">Collecting signal data...</span>
        </div>
      </DataPanel>
    )
  }

  return (
    <DataPanel title="Signal Activity" icon="📡" variant="status">
      <div className="signal-activity-panel">
        {/* Activity Level Badge */}
        <div className="activity-header">
          <div
            className={`activity-badge activity-${activityLevel.level}`}
            style={{ '--activity-color': activityLevel.color } as React.CSSProperties}
          >
            <span className="activity-dot"></span>
            <span className="activity-label">{activityLevel.label}</span>
          </div>
          {signalActivity?.minutes_since_last_signal !== undefined && (
            <span className="last-signal-time">
              Last signal: {formatTimeAgo(signalActivity.minutes_since_last_signal)}
            </span>
          )}
        </div>

        {/* Quiet Reason (if applicable) */}
        {quietReason && activityLevel.level !== 'high' && (
          <div className="quiet-reason-box">
            <span className="quiet-icon">💤</span>
            <span className="quiet-text">Quiet because: {quietReason}</span>
            {signalActivity?.quiet_period_minutes && signalActivity.quiet_period_minutes > 5 && (
              <span className="quiet-duration">
                ({Math.floor(signalActivity.quiet_period_minutes)}m)
              </span>
            )}
          </div>
        )}

        {/* Signal Stats */}
        {signalActivity && (
          <div className="signal-stats">
            <div className="stats-row">
              <div className="stat-item">
                <span className="stat-value">{signalActivity.signals_last_hour}</span>
                <span className="stat-label">Last Hour</span>
              </div>
              <div className="stat-item">
                <span className="stat-value">{signalActivity.signals_today}</span>
                <span className="stat-label">Today</span>
              </div>
            </div>

            {/* Signal Breakdown */}
            {signalActivity.signal_breakdown && (
              <div className="signal-breakdown">
                <div className="breakdown-row">
                  <span className="breakdown-item long">
                    <span className="item-icon">↗</span>
                    <span className="item-count">{signalActivity.signal_breakdown.long_signals}</span>
                    <span className="item-label">Long</span>
                  </span>
                  <span className="breakdown-item short">
                    <span className="item-icon">↘</span>
                    <span className="item-count">{signalActivity.signal_breakdown.short_signals}</span>
                    <span className="item-label">Short</span>
                  </span>
                </div>
                <div className="breakdown-row">
                  <span className="breakdown-item executed">
                    <span className="item-icon">✓</span>
                    <span className="item-count">{signalActivity.signal_breakdown.executed}</span>
                    <span className="item-label">Executed</span>
                  </span>
                  <span className="breakdown-item blocked">
                    <span className="item-icon">✗</span>
                    <span className="item-count">{signalActivity.signal_breakdown.blocked}</span>
                    <span className="item-label">Blocked</span>
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Last Decision */}
        {lastDecision && lastDecision.timestamp && (
          <div className="last-decision">
            <div className="decision-header">
              <span className="decision-label">Last Decision</span>
              <span className={`decision-action ${lastDecision.action}`}>
                {lastDecision.action === 'execute' ? '✓ Execute' : '✗ Skip'}
              </span>
            </div>
            <div className="decision-details">
              <span className="decision-type">{lastDecision.signal_type}</span>
              {lastDecision.ml_probability !== undefined && lastDecision.ml_probability > 0 && (
                <span className="decision-ml">
                  ML: {(lastDecision.ml_probability * 100).toFixed(0)}%
                </span>
              )}
              {lastDecision.reason && (
                <span className="decision-reason">{lastDecision.reason}</span>
              )}
            </div>
          </div>
        )}

        {/* Hourly Trend Visualization (simple bars) */}
        {signalActivity && signalActivity.signals_today > 0 && (
          <div className="signals-per-hour">
            <span className="trend-label">
              {signalActivity.signals_last_hour > 0
                ? `${signalActivity.signals_last_hour} signal${signalActivity.signals_last_hour > 1 ? 's' : ''}/hr`
                : 'Waiting for signals...'}
            </span>
          </div>
        )}
      </div>
    </DataPanel>
  )
}

export default memo(SignalActivityPanel)
