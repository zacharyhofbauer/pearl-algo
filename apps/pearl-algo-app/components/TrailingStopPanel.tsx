'use client'

import React, { useMemo, useState } from 'react'
import { useAgentStore, selectTrailingStop, useOperatorStore, useUIStore } from '@/stores'
import type { TrailingStopPosition } from '@/stores'
import { formatPrice } from '@/lib/formatters'
import { apiFetch } from '@/lib/api'
import OperatorUnlockModal from '@/components/OperatorUnlockModal'
import TrailingStopOverrideModal from '@/components/TrailingStopOverrideModal'

interface TrailingStopRowProps {
  signalId: string
  state: TrailingStopPosition
}

function phaseLabel(phase: string): { text: string; variant: 'inactive' | 'armed' | 'trailing' | 'unknown' } {
  const lower = (phase || '').toLowerCase()
  if (lower.includes('trail')) return { text: 'Trailing', variant: 'trailing' }
  if (lower.includes('activ') || lower.includes('arm')) return { text: 'Armed', variant: 'armed' }
  if (lower.includes('inactive') || lower === '') return { text: 'Inactive', variant: 'inactive' }
  return { text: phase, variant: 'unknown' }
}

const TrailingStopRow = React.memo(function TrailingStopRow({ signalId, state }: TrailingStopRowProps) {
  const dir = (state.direction || '').toLowerCase()
  const isLong = dir === 'long'
  const phase = phaseLabel(state.current_phase)

  // For longs: best_price is the highest seen, stop trails up.
  // For shorts: best_price is the lowest seen, stop trails down.
  // "Locked $" = signed distance from entry that the trailing stop has secured.
  const lockedPoints = isLong
    ? state.current_stop - state.entry_price
    : state.entry_price - state.current_stop
  const drift = isLong
    ? state.best_price - state.entry_price
    : state.entry_price - state.best_price

  const lockedPositive = lockedPoints > 0

  return (
    <div className="trailing-row">
      <div className="trailing-row-head">
        <span className={`trade-direction-badge ${isLong ? 'long' : 'short'}`}>{(dir || '?').toUpperCase()}</span>
        <span className="trailing-row-id" title={signalId}>
          {signalId.length > 12 ? `…${signalId.slice(-10)}` : signalId}
        </span>
        <span className={`trailing-phase-chip phase-${phase.variant}`}>{phase.text}</span>
      </div>
      <div className="trailing-row-grid">
        <div className="trailing-cell">
          <span className="trailing-cell-label">Entry</span>
          <span className="trailing-cell-value">{formatPrice(state.entry_price)}</span>
        </div>
        <div className="trailing-cell">
          <span className="trailing-cell-label">Best</span>
          <span className="trailing-cell-value">{formatPrice(state.best_price)}</span>
        </div>
        <div className="trailing-cell">
          <span className="trailing-cell-label">Stop</span>
          <span className="trailing-cell-value">{formatPrice(state.current_stop)}</span>
        </div>
        <div className="trailing-cell">
          <span className="trailing-cell-label">Run</span>
          <span className="trailing-cell-value">
            {drift >= 0 ? `+${drift.toFixed(2)}` : drift.toFixed(2)}
          </span>
        </div>
        <div className="trailing-cell">
          <span className="trailing-cell-label">Locked</span>
          <span className={`trailing-cell-value ${lockedPositive ? 'positive' : 'negative'}`}>
            {lockedPoints >= 0 ? `+${lockedPoints.toFixed(2)}` : lockedPoints.toFixed(2)}
          </span>
        </div>
      </div>
    </div>
  )
})

/**
 * TrailingStopPanel — read-only display of the regime-adaptive trailing stop
 * state for every tracked position, plus the active manual override (if any).
 *
 * Reads agentState.trailing_stop directly. Backend keeps this fresh on every
 * loop tick via state_builder._get_trailing_stop_state(). No fetching here.
 *
 * NOTE: Does NOT expose override controls. Mutations to trailing-stop
 * parameters affect live trading and require explicit operator approval —
 * track the modal as a follow-up.
 */
function TrailingStopPanel() {
  const trailing = useAgentStore(selectTrailingStop)
  const isUnlocked = useOperatorStore((s) => s.isUnlocked)
  const addNotification = useUIStore((s) => s.addNotification)
  const [showUnlockModal, setShowUnlockModal] = useState(false)
  const [showOverrideModal, setShowOverrideModal] = useState(false)
  const [clearBusy, setClearBusy] = useState(false)
  const [confirmClear, setConfirmClear] = useState(false)

  const positions = useMemo(() => {
    if (!trailing?.positions) return []
    return Object.entries(trailing.positions).map(([signalId, state]) => ({ signalId, state }))
  }, [trailing])

  // Open override modal — but if we're not unlocked yet, prompt for the
  // passphrase first and reopen automatically once the operator store flips.
  const requestOverride = () => {
    if (!isUnlocked) {
      setShowUnlockModal(true)
      return
    }
    setShowOverrideModal(true)
  }

  // Two-tap clear so a stray click can't wipe an active override.
  const requestClear = async () => {
    if (!isUnlocked) {
      setShowUnlockModal(true)
      return
    }
    if (!confirmClear) {
      setConfirmClear(true)
      // Reset the confirmation prompt after a few seconds if the user walks away.
      setTimeout(() => setConfirmClear(false), 4000)
      return
    }
    setClearBusy(true)
    try {
      const res = await apiFetch('/api/trailing-stop/override', { method: 'DELETE' })
      const text = await res.text()
      let payload: { ok?: boolean; message?: string; detail?: unknown } = {}
      try {
        payload = text ? JSON.parse(text) : {}
      } catch {
        // tolerate non-JSON
      }
      if (!res.ok) {
        const detail =
          (typeof payload.detail === 'string' && payload.detail) ||
          payload.message ||
          (text && text.trim()) ||
          `HTTP ${res.status}`
        throw new Error(detail)
      }
      addNotification({
        type: 'success',
        title: 'Trailing override cleared',
        message: payload.message || 'Reverting to default trail parameters.',
      })
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Clear request failed'
      addNotification({ type: 'error', title: 'Clear override failed', message })
    } finally {
      setClearBusy(false)
      setConfirmClear(false)
    }
  }

  // ── Modal mounts (always rendered so unlock + override stay isolated) ──
  const modals = (
    <>
      <OperatorUnlockModal
        isOpen={showUnlockModal}
        onClose={() => setShowUnlockModal(false)}
        onUnlocked={() => setShowOverrideModal(true)}
      />
      <TrailingStopOverrideModal
        isOpen={showOverrideModal}
        onClose={() => setShowOverrideModal(false)}
        defaultTrailMult={trailing?.active_override?.trail_atr_multiplier}
        defaultActivationMult={trailing?.active_override?.activation_atr_multiplier}
      />
    </>
  )

  if (!trailing) {
    return (
      <div className="trailing-panel">
        <div className="trailing-empty">Trailing stop data not yet available.</div>
        {modals}
      </div>
    )
  }

  if (!trailing.enabled) {
    return (
      <div className="trailing-panel">
        <div className="trailing-empty">
          Trailing stops disabled in config. Enable via
          <code className="trailing-empty-code"> trailing_stop.enabled: true</code>
          in <code className="trailing-empty-code">config/live/tradovate_paper.yaml</code>.
        </div>
        {modals}
      </div>
    )
  }

  const ov = trailing.active_override

  return (
    <div className="trailing-panel">
      <header className="trailing-header">
        <span className="trailing-header-status">
          <span className="trailing-status-dot is-on" aria-hidden />
          ENABLED
          {trailing.regime_adaptive && (
            <span className="trailing-header-flag" title="Trailing distance auto-scales by market regime">
              REGIME-ADAPTIVE
            </span>
          )}
        </span>
        <span className="trailing-header-actions">
          <span className="trailing-header-count">
            {positions.length} position{positions.length === 1 ? '' : 's'}
          </span>
          <button
            type="button"
            className="trailing-header-btn"
            onClick={requestOverride}
            title={isUnlocked ? 'Apply manual override' : 'Click to unlock and apply override'}
          >
            {isUnlocked ? 'Override' : '🔒 Override'}
          </button>
        </span>
      </header>

      {ov && (
        <section className="trailing-override" role="note" aria-label="Active override">
          <div className="trailing-override-head">
            <span className="trailing-override-tag">OVERRIDE</span>
            <span className="trailing-override-source">{ov.source}</span>
            {typeof ov.expires_in_minutes === 'number' && ov.expires_in_minutes > 0 && (
              <span className="trailing-override-expiry">
                expires in {ov.expires_in_minutes.toFixed(0)}m
              </span>
            )}
            <button
              type="button"
              className={`trailing-override-clear ${confirmClear ? 'is-confirming' : ''}`}
              onClick={requestClear}
              disabled={clearBusy}
              title={
                !isUnlocked
                  ? 'Click to unlock and clear override'
                  : confirmClear
                    ? 'Click again to confirm'
                    : 'Clear override and revert to defaults'
              }
            >
              {clearBusy
                ? 'Clearing…'
                : confirmClear
                  ? 'Confirm Clear'
                  : isUnlocked
                    ? 'Clear'
                    : '🔒 Clear'}
            </button>
          </div>
          <div className="trailing-override-grid">
            <div className="trailing-cell">
              <span className="trailing-cell-label">Trail × ATR</span>
              <span className="trailing-cell-value">{ov.trail_atr_multiplier.toFixed(2)}</span>
            </div>
            <div className="trailing-cell">
              <span className="trailing-cell-label">Activate × ATR</span>
              <span className="trailing-cell-value">{ov.activation_atr_multiplier.toFixed(2)}</span>
            </div>
            {ov.force_phase && (
              <div className="trailing-cell">
                <span className="trailing-cell-label">Force phase</span>
                <span className="trailing-cell-value">{ov.force_phase}</span>
              </div>
            )}
          </div>
          {ov.reason && <div className="trailing-override-reason">{ov.reason}</div>}
        </section>
      )}

      {positions.length === 0 ? (
        <div className="trailing-empty">No positions currently tracked.</div>
      ) : (
        <div className="trailing-list">
          {positions.map(({ signalId, state }) => (
            <TrailingStopRow key={signalId} signalId={signalId} state={state} />
          ))}
        </div>
      )}
      {modals}
    </div>
  )
}

export default React.memo(TrailingStopPanel)
