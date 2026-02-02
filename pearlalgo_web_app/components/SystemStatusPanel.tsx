'use client'

import { useMemo, memo } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { InfoTooltip } from './ui'
import { formatCountdown } from '@/lib/formatters'
import type {
  ExecutionState,
  CircuitBreakerStatus,
  MarketRegime,
  SessionContext,
  ErrorSummary,
} from '@/stores'

interface SystemStatusPanelProps {
  executionState: ExecutionState | null
  circuitBreaker: CircuitBreakerStatus | null
  marketRegime: MarketRegime | null
  sessionContext: SessionContext | null
  errorSummary: ErrorSummary | null
  isRunning: boolean
  isPaused: boolean
}

function SystemStatusPanel({
  executionState,
  circuitBreaker,
  marketRegime,
  sessionContext,
  errorSummary,
  isRunning,
  isPaused,
}: SystemStatusPanelProps) {
  // Determine overall system readiness - memoized
  const readiness = useMemo(() => {
    if (!isRunning) return { status: 'offline', label: 'Offline', color: 'var(--accent-red)' }
    if (isPaused) return { status: 'paused', label: 'Paused', color: 'var(--accent-yellow)' }
    if (circuitBreaker?.in_cooldown) return { status: 'cooldown', label: 'Cooldown', color: 'var(--accent-yellow)' }
    if (executionState && !executionState.armed) return { status: 'disarmed', label: 'Disarmed', color: 'var(--accent-yellow)' }
    if (executionState?.armed) return { status: 'armed', label: 'Armed', color: 'var(--accent-green)' }
    return { status: 'ready', label: 'Ready', color: 'var(--accent-green)' }
  }, [isRunning, isPaused, circuitBreaker?.in_cooldown, executionState])

  // Use centralized countdown formatter
  const formatTimeRemaining = (seconds: number) => formatCountdown(seconds)

  // Get session display info - memoized
  const sessionLabel = useMemo(() => {
    if (!sessionContext?.current_session) return null
    const sessionLabels: Record<string, string> = {
      premarket: 'Pre-Market',
      morning: 'Morning',
      midday: 'Midday',
      afternoon: 'Afternoon',
      extended: 'Extended',
      closed: 'Closed',
    }
    return sessionLabels[sessionContext.current_session] || sessionContext.current_session
  }, [sessionContext?.current_session])

  // Get direction restriction display - memoized
  const directionInfo = useMemo(() => {
    if (!marketRegime?.allowed_direction) return null
    switch (marketRegime.allowed_direction) {
      case 'long':
        return { label: 'Long Only', icon: '↗', color: 'var(--accent-cyan)' }
      case 'short':
        return { label: 'Short Only', icon: '↘', color: 'var(--color-short)' }
      case 'both':
        return { label: 'Both', icon: '↔', color: 'var(--text-secondary)' }
      default:
        return null
    }
  }, [marketRegime?.allowed_direction])

  // Get error trend indicator - memoized
  const errorTrend = useMemo(() => {
    if (!errorSummary) return null
    const count = errorSummary.session_error_count
    if (count === 0) return { icon: '✓', label: 'No Errors', color: 'var(--accent-green)' }
    if (count < 5) return { icon: '→', label: `${count} Errors`, color: 'var(--accent-yellow)' }
    return { icon: '↑', label: `${count} Errors`, color: 'var(--accent-red)' }
  }, [errorSummary])

  return (
    <DataPanel title="System Status" icon="🎯" variant="status">
      <div className="system-status-panel" role="region" aria-label="System Status">
        {/* Main Readiness Indicator - with ARIA live region */}
        <div className="status-readiness" role="status" aria-live="polite" aria-atomic="true">
          <div
            className={`readiness-badge readiness-${readiness.status}`}
            style={{ '--badge-color': readiness.color } as React.CSSProperties}
            aria-label={`System readiness: ${readiness.label}`}
          >
            <span className="readiness-dot" aria-hidden="true"></span>
            <span className="readiness-label">{readiness.label}</span>
          </div>
          {executionState?.mode && executionState.mode !== 'live' && (
            <span className="mode-badge">{executionState.mode.toUpperCase()}</span>
          )}
        </div>

        {/* Status Grid - items update independently */}
        <div className="status-grid" aria-live="polite">
          {/* Execution State */}
          <div className="status-item">
            <span className="status-item-label">Execution</span>
            <div className="status-item-value">
              {executionState ? (
                <span className={`status-chip ${executionState.armed ? 'armed' : 'disarmed'}`}>
                  {executionState.armed ? '✓ Armed' : '⚠ Disarmed'}
                </span>
              ) : (
                <span className="status-chip neutral">—</span>
              )}
              {executionState?.disarm_reason && (
                <InfoTooltip text={executionState.disarm_reason} />
              )}
            </div>
          </div>

          {/* Circuit Breaker */}
          <div className="status-item">
            <span className="status-item-label">Circuit Breaker</span>
            <div className="status-item-value">
              {circuitBreaker ? (
                <>
                  {circuitBreaker.in_cooldown ? (
                    <span className="status-chip cooldown">
                      ⏱ Cooldown
                      {circuitBreaker.cooldown_remaining_seconds && (
                        <span className="chip-sub">
                          {formatTimeRemaining(circuitBreaker.cooldown_remaining_seconds)}
                        </span>
                      )}
                    </span>
                  ) : circuitBreaker.active ? (
                    <span className="status-chip active">✓ Active</span>
                  ) : (
                    <span className="status-chip inactive">Off</span>
                  )}
                  {circuitBreaker.trips_today > 0 && (
                    <span className="trip-count">{circuitBreaker.trips_today} trips</span>
                  )}
                </>
              ) : (
                <span className="status-chip neutral">—</span>
              )}
            </div>
          </div>

          {/* Direction Restriction */}
          <div className="status-item">
            <span className="status-item-label">Direction</span>
            <div className="status-item-value">
              {directionInfo ? (
                <span
                  className="status-chip direction"
                  style={{ color: directionInfo.color }}
                >
                  {directionInfo.icon} {directionInfo.label}
                </span>
              ) : (
                <span className="status-chip neutral">—</span>
              )}
            </div>
          </div>

          {/* Session Window */}
          <div className="status-item">
            <span className="status-item-label">Session</span>
            <div className="status-item-value">
              {sessionLabel ? (
                <>
                  <span className="status-chip session">{sessionLabel}</span>
                  {sessionContext?.time_until_next_session_seconds && sessionContext.time_until_next_session_seconds > 0 && (
                    <span className="session-countdown">
                      Next: {formatTimeRemaining(sessionContext.time_until_next_session_seconds)}
                    </span>
                  )}
                </>
              ) : (
                <span className="status-chip neutral">—</span>
              )}
            </div>
          </div>

          {/* Error Rate */}
          <div className="status-item">
            <span className="status-item-label">Errors</span>
            <div className="status-item-value">
              {errorTrend ? (
                <span
                  className="status-chip errors"
                  style={{ color: errorTrend.color }}
                >
                  {errorTrend.icon} {errorTrend.label}
                </span>
              ) : (
                <span className="status-chip neutral">✓ None</span>
              )}
            </div>
          </div>

          {/* Rolling Win Rate (if circuit breaker tracks it) */}
          {circuitBreaker?.rolling_win_rate !== undefined && (
            <div className="status-item">
              <span className="status-item-label">Win Rate</span>
              <div className="status-item-value">
                <span className={`status-chip ${circuitBreaker.rolling_win_rate >= 0.5 ? 'positive' : 'negative'}`}>
                  {(circuitBreaker.rolling_win_rate * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Session P&L (if available) */}
        {sessionContext && sessionContext.session_trades > 0 && (
          <div className="session-summary">
            <span className="session-summary-label">Session:</span>
            <span className={`session-pnl ${sessionContext.session_pnl >= 0 ? 'positive' : 'negative'}`}>
              {sessionContext.session_pnl >= 0 ? '+' : ''}${sessionContext.session_pnl.toFixed(2)}
            </span>
            <span className="session-trades">
              {sessionContext.session_wins}W/{sessionContext.session_trades - sessionContext.session_wins}L
            </span>
          </div>
        )}
      </div>
    </DataPanel>
  )
}

export default memo(SystemStatusPanel)
