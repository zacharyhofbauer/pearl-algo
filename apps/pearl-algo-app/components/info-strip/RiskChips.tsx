'use client'

import React, { useMemo } from 'react'
import type { Position } from '@/stores/chartStore'
import type { RiskMetrics, CircuitBreakerStatus, ExecutionState } from '@/stores/agentStore'
import { getUsdPerPoint } from '@/lib/formatters'

interface RiskChipsProps {
  positions: Position[]
  riskMetrics: RiskMetrics | null
  circuitBreaker: CircuitBreakerStatus | null
  executionState: ExecutionState | null
  /** Active concurrent positions (from agent state, may differ from positions.length on race) */
  activePositions?: number
  /** Default symbol used to look up tick value if a position omits one */
  defaultSymbol?: string
}

interface DerivedRisk {
  openStopRiskUsd: number | null
  unknownPositions: number
  consecutiveStreak: number | null
  isLossStreak: boolean
  cooldownSeconds: number | null
  cooldownActive: boolean
}

function deriveRisk(
  positions: Position[],
  riskMetrics: RiskMetrics | null,
  circuitBreaker: CircuitBreakerStatus | null,
  defaultSymbol?: string
): DerivedRisk {
  let openStopRiskUsd: number | null = null
  let unknownPositions = 0

  if (Array.isArray(positions) && positions.length > 0) {
    let total = 0
    let any = false
    for (const p of positions) {
      const sym = p.symbol || defaultSymbol
      const usdPerPoint = getUsdPerPoint(sym)
      const size = Number(p.position_size ?? 0)
      if (
        usdPerPoint == null ||
        !Number.isFinite(p.entry_price) ||
        !Number.isFinite(p.stop_loss as number) ||
        !Number.isFinite(size) ||
        size <= 0
      ) {
        unknownPositions += 1
        continue
      }
      total += Math.abs((p.entry_price as number) - (p.stop_loss as number)) * size * usdPerPoint
      any = true
    }
    openStopRiskUsd = any ? total : null
  }

  const streak = riskMetrics?.current_streak ?? null
  const isLossStreak = typeof streak === 'number' && streak < 0
  const consecutiveStreak = typeof streak === 'number' ? Math.abs(streak) : null

  return {
    openStopRiskUsd,
    unknownPositions,
    consecutiveStreak,
    isLossStreak,
    cooldownSeconds: circuitBreaker?.cooldown_remaining_seconds ?? null,
    cooldownActive: !!circuitBreaker?.in_cooldown,
  }
}

function formatCooldown(seconds: number): string {
  if (seconds < 60) return `${Math.round(seconds)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return s > 0 ? `${m}m ${s}s` : `${m}m`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

function RiskChips({
  positions,
  riskMetrics,
  circuitBreaker,
  executionState,
  activePositions,
  defaultSymbol,
}: RiskChipsProps) {
  const risk = useMemo(
    () => deriveRisk(positions, riskMetrics, circuitBreaker, defaultSymbol),
    [positions, riskMetrics, circuitBreaker, defaultSymbol]
  )

  const peakRisk = riskMetrics?.max_stop_risk_exposure ?? null
  const peakDdPct = riskMetrics?.max_drawdown_pct ?? null
  const concurrent = activePositions ?? positions?.length ?? 0
  const concurrentPeak = riskMetrics?.max_concurrent_positions_peak ?? null

  // Severity flag for stop-risk chip: warn if >60% of session peak, error if >=session peak
  let stopRiskSeverity: 'normal' | 'warn' | 'error' = 'normal'
  if (risk.openStopRiskUsd != null && peakRisk != null && peakRisk > 0) {
    const ratio = risk.openStopRiskUsd / peakRisk
    if (ratio >= 1) stopRiskSeverity = 'error'
    else if (ratio >= 0.6) stopRiskSeverity = 'warn'
  }

  // Cooldown chip: explicit error tint if active
  const cooldownSeverity: 'normal' | 'error' = risk.cooldownActive ? 'error' : 'normal'

  // Streak chip: warn at 2 consecutive losses, error at 3+
  let streakSeverity: 'normal' | 'warn' | 'error' = 'normal'
  if (risk.isLossStreak && risk.consecutiveStreak != null) {
    if (risk.consecutiveStreak >= 3) streakSeverity = 'error'
    else if (risk.consecutiveStreak >= 2) streakSeverity = 'warn'
  }

  const armed = executionState?.armed === true
  const enabled = executionState?.enabled !== false

  return (
    <section className="info-strip-section info-strip-risk" aria-label="Live risk">
      <div className="info-strip-risk-grid">
        <div
          className={`info-strip-chip risk-chip-stop ${stopRiskSeverity !== 'normal' ? `chip-${stopRiskSeverity}` : ''}`}
          title={
            risk.unknownPositions > 0
              ? `${risk.unknownPositions} position(s) missing stop or symbol — excluded from total`
              : 'Sum of |entry − stop| × contracts × $/pt across open positions'
          }
        >
          <span className="info-strip-chip-label">Stop Risk</span>
          <span className="info-strip-chip-value">
            {risk.openStopRiskUsd != null
              ? `$${risk.openStopRiskUsd.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
              : '$0'}
          </span>
        </div>

        <div
          className="info-strip-chip risk-chip-peak"
          title="Today's high-water mark for concurrent stop risk"
        >
          <span className="info-strip-chip-label">Peak Risk</span>
          <span className="info-strip-chip-value">
            {peakRisk != null
              ? `$${peakRisk.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
              : '—'}
          </span>
        </div>

        <div
          className="info-strip-chip risk-chip-positions"
          title="Concurrent open positions vs today's peak"
        >
          <span className="info-strip-chip-label">Open</span>
          <span className="info-strip-chip-value">
            {concurrent}
            {concurrentPeak != null && concurrentPeak > 0 ? ` / ${concurrentPeak}` : ''}
          </span>
        </div>

        <div
          className={`info-strip-chip risk-chip-streak ${streakSeverity !== 'normal' ? `chip-${streakSeverity}` : ''}`}
          title={
            risk.consecutiveStreak == null
              ? 'No streak data'
              : risk.isLossStreak
                ? `${risk.consecutiveStreak} consecutive loss${risk.consecutiveStreak === 1 ? '' : 'es'}`
                : `${risk.consecutiveStreak} consecutive win${risk.consecutiveStreak === 1 ? '' : 's'}`
          }
        >
          <span className="info-strip-chip-label">Streak</span>
          <span className="info-strip-chip-value">
            {risk.consecutiveStreak == null
              ? '—'
              : risk.isLossStreak
                ? `−${risk.consecutiveStreak}`
                : `+${risk.consecutiveStreak}`}
          </span>
        </div>

        <div
          className={`info-strip-chip risk-chip-cooldown ${cooldownSeverity !== 'normal' ? `chip-${cooldownSeverity}` : ''}`}
          title={
            risk.cooldownActive
              ? circuitBreaker?.trip_reason
                ? `Cooldown active: ${circuitBreaker.trip_reason}`
                : 'Circuit breaker cooldown active'
              : 'Circuit breaker idle'
          }
        >
          <span className="info-strip-chip-label">CB</span>
          <span className="info-strip-chip-value">
            {risk.cooldownActive && risk.cooldownSeconds != null
              ? formatCooldown(risk.cooldownSeconds)
              : risk.cooldownActive
                ? 'ON'
                : 'idle'}
          </span>
        </div>

        <div
          className={`info-strip-chip risk-chip-exec ${
            !enabled ? 'chip-error' : !armed ? 'chip-warn' : 'chip-ok'
          }`}
          title={
            !enabled
              ? 'Execution disabled'
              : !armed
                ? `Disarmed${executionState?.disarm_reason ? `: ${executionState.disarm_reason}` : ''}`
                : `Armed (${executionState?.mode ?? 'live'})`
          }
        >
          <span className="info-strip-chip-label">Exec</span>
          <span className="info-strip-chip-value">
            {!enabled ? 'OFF' : !armed ? 'DISARM' : (executionState?.mode || 'LIVE').toUpperCase()}
          </span>
        </div>

        {peakDdPct != null && peakDdPct < 0 && (
          <div
            className="info-strip-chip risk-chip-dd"
            title="Maximum drawdown percentage in the tracking window"
          >
            <span className="info-strip-chip-label">Max DD</span>
            <span className="info-strip-chip-value negative">
              {(peakDdPct * 100).toFixed(1)}%
            </span>
          </div>
        )}
      </div>
    </section>
  )
}

// Re-export the local helper as a named export for cooldown formatting reuse.
export { formatCooldown }
export default React.memo(RiskChips)
