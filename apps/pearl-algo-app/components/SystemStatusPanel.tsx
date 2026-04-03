'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { InfoTooltip } from './ui'
import type {
  ExecutionState,
  CircuitBreakerStatus,
  MarketRegime,
  SessionContext,
  ErrorSummary,
} from '@/stores'
import { apiFetch, apiFetchJson } from '@/lib/api'
import { useOperatorStore } from '@/stores'
import OperatorUnlockModal from '@/components/OperatorUnlockModal'
import { formatTimeRemaining } from '@/lib/formatters'

interface SystemStatusPanelProps {
  executionState: ExecutionState | null
  circuitBreaker: CircuitBreakerStatus | null
  marketRegime: MarketRegime | null
  sessionContext: SessionContext | null
  errorSummary: ErrorSummary | null
  isRunning: boolean
  isPaused: boolean
}

export default function SystemStatusPanel({
  executionState,
  circuitBreaker,
  marketRegime,
  sessionContext,
  errorSummary,
  isRunning,
  isPaused,
}: SystemStatusPanelProps) {
  const [confirmKill, setConfirmKill] = useState(false)
  const [killBusy, setKillBusy] = useState(false)
  const [killResult, setKillResult] = useState<{ type: 'idle' | 'ok' | 'error'; message: string } | null>(null)

  // Determine overall system readiness
  const getSystemReadiness = () => {
    if (!isRunning) return { status: 'offline', label: 'Offline', color: 'var(--accent-red)' }
    if (isPaused) return { status: 'paused', label: 'Paused', color: 'var(--accent-yellow)' }
    if (circuitBreaker?.in_cooldown) return { status: 'cooldown', label: 'Cooldown', color: 'var(--accent-yellow)' }
    if (executionState && !executionState.armed) return { status: 'disarmed', label: 'Disarmed', color: 'var(--accent-yellow)' }
    if (executionState?.armed) return { status: 'armed', label: 'Armed', color: 'var(--accent-green)' }
    return { status: 'ready', label: 'Ready', color: 'var(--accent-green)' }
  }

  const readiness = getSystemReadiness()

  // Get session display info
  const getSessionDisplay = () => {
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
  }

  // Get direction restriction display
  const getDirectionDisplay = () => {
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
  }

  const directionInfo = getDirectionDisplay()
  const sessionLabel = getSessionDisplay()

  // Get error trend indicator
  const getErrorTrend = () => {
    if (!errorSummary) return null
    const count = errorSummary.session_error_count
    if (count === 0) return { icon: '✓', label: 'No Errors', color: 'var(--accent-green)' }
    if (count < 5) return { icon: '→', label: `${count} Errors`, color: 'var(--accent-yellow)' }
    return { icon: '↑', label: `${count} Errors`, color: 'var(--accent-red)' }
  }

  const errorTrend = getErrorTrend()

  const canUseKillSwitch = useOperatorStore((s) => s.isUnlocked)
  const [showUnlockModal, setShowUnlockModal] = useState(false)

  const requestKillSwitch = async () => {
    setKillBusy(true)
    setKillResult(null)
    try {
      const res = await apiFetch('/api/kill-switch', { method: 'POST' })
      const raw = await res.text()
      let body: any = null
      try {
        body = raw ? JSON.parse(raw) : null
      } catch {
        body = null
      }

      if (!res.ok) {
        const detail =
          body?.detail?.message ||
          body?.detail ||
          body?.message ||
          (typeof raw === 'string' && raw.trim() ? raw.trim() : null) ||
          `HTTP ${res.status}`
        const msg = typeof detail === 'string' ? detail : `HTTP ${res.status}`
        throw new Error(msg)
      }

      setKillResult({ type: 'ok', message: body?.message || 'Kill switch requested.' })
      setConfirmKill(false)
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Kill switch request failed.'
      setKillResult({
        type: 'error',
        message,
      })
    } finally {
      setKillBusy(false)
    }
  }

  return (
    <DataPanel title="System Status" variant="status">
      <OperatorUnlockModal isOpen={showUnlockModal} onClose={() => setShowUnlockModal(false)} />
      <div className="system-status-panel">
        {/* Main Readiness Indicator */}
        <div className="status-readiness">
          <div
            className={`readiness-badge readiness-${readiness.status}`}
            style={{ '--badge-color': readiness.color } as React.CSSProperties}
          >
            <span className="readiness-dot"></span>
            <span className="readiness-label">{readiness.label}</span>
          </div>
          {executionState?.mode && executionState.mode !== 'live' && (
            <span className="mode-badge">{executionState.mode.toUpperCase()}</span>
          )}
        </div>

        {/* TradingView-style Status Rows */}
        <div className="tv-status-list">
          <div className="tv-status-row">
            <span className="tv-status-key">Execution</span>
            <span className="tv-status-value">
              {executionState ? (
                <>
                  <span className={`status-chip ${executionState.armed ? 'armed' : 'disarmed'}`}>
                    {executionState.armed ? '✓ Armed' : '⚠ Disarmed'}
                  </span>
                  {executionState?.disarm_reason && (
                    <InfoTooltip text={executionState.disarm_reason} />
                  )}
                </>
              ) : (
                <span className="status-chip neutral">—</span>
              )}
            </span>
          </div>

          <div className="tv-status-row">
            <span className="tv-status-key">Circuit Breaker</span>
            <span className="tv-status-value">
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
            </span>
          </div>

          <div className="tv-status-row">
            <span className="tv-status-key">Direction</span>
            <span className="tv-status-value">
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
            </span>
          </div>

          <div className="tv-status-row">
            <span className="tv-status-key">Session</span>
            <span className="tv-status-value">
              {sessionLabel ? (
                <>
                  <span className="status-chip session">{sessionLabel}</span>
                  {sessionContext?.time_until_next_session_seconds &&
                    sessionContext.time_until_next_session_seconds > 0 && (
                      <span className="session-countdown">
                        Next: {formatTimeRemaining(sessionContext.time_until_next_session_seconds)}
                      </span>
                    )}
                </>
              ) : (
                <span className="status-chip neutral">—</span>
              )}
            </span>
          </div>

          <div className="tv-status-row">
            <span className="tv-status-key">Errors</span>
            <span className="tv-status-value">
              {errorTrend ? (
                <span className="status-chip errors" style={{ color: errorTrend.color }}>
                  {errorTrend.icon} {errorTrend.label}
                </span>
              ) : (
                <span className="status-chip neutral">✓ None</span>
              )}
            </span>
          </div>
        </div>

        {/* Kill Switch */}
        <div className="kill-switch-panel">
          <div className="kill-switch-head">
            <div className="kill-switch-title-row">
              <span className="kill-switch-title">Kill Switch</span>
              <InfoTooltip text="Disarms execution, cancels open orders, flattens broker positions, and closes virtual trades." />
            </div>
            <span className="kill-switch-subtitle">Close all trades + cancel orders</span>
          </div>

          {!confirmKill ? (
            <button
              type="button"
              className="kill-switch-btn"
              onClick={() => { if (!canUseKillSwitch) { setShowUnlockModal(true); return } setConfirmKill(true) }}
              disabled={killBusy}
              title={!canUseKillSwitch ? 'Click to unlock' : undefined}
            >
              🛑 Kill Switch
            </button>
          ) : (
            <div className="kill-switch-confirm">
              <button
                type="button"
                className="kill-switch-btn kill-switch-confirm-btn"
                onClick={requestKillSwitch}
                disabled={!canUseKillSwitch || killBusy}
                aria-disabled={!canUseKillSwitch || killBusy}
              >
                {killBusy ? 'Sending…' : 'Confirm Kill'}
              </button>
              <button
                type="button"
                className="kill-switch-cancel-btn"
                onClick={() => setConfirmKill(false)}
                disabled={killBusy}
              >
                Cancel
              </button>
            </div>
          )}



          {killResult && (
            <div className={`kill-switch-result kill-switch-result-${killResult.type}`}>
              {killResult.message}
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