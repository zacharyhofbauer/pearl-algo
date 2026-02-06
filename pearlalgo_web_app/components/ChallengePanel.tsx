'use client'

import { useEffect, useRef, useMemo } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { StatDisplay } from './ui'
import type { EquityCurvePoint, ChallengeStatus } from '@/stores'

interface ChallengePanelProps {
  challenge: ChallengeStatus | null
  equityCurve?: EquityCurvePoint[]
}

// Mini sparkline component for challenge equity - larger and more visible
function MiniSparkline({ data, isPositive }: { data: EquityCurvePoint[], isPositive: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || data.length < 2) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const width = canvas.width
    const height = canvas.height
    const padding = 3

    // Clear canvas
    ctx.clearRect(0, 0, width, height)

    // Get values
    const values = data.map(d => d.value)
    const minVal = Math.min(...values)
    const maxVal = Math.max(...values)
    const range = maxVal - minVal || 1

    // Scale function
    const scaleX = (i: number) => padding + (i / (values.length - 1)) * (width - padding * 2)
    const scaleY = (v: number) => height - padding - ((v - minVal) / range) * (height - padding * 2)

    // Draw line with gradient
    ctx.beginPath()
    ctx.strokeStyle = isPositive ? '#00e676' : '#ff5252'
    ctx.lineWidth = 2
    ctx.lineJoin = 'round'
    ctx.lineCap = 'round'

    values.forEach((val, i) => {
      const x = scaleX(i)
      const y = scaleY(val)
      if (i === 0) {
        ctx.moveTo(x, y)
      } else {
        ctx.lineTo(x, y)
      }
    })
    ctx.stroke()

    // Draw endpoint dot
    const lastX = scaleX(values.length - 1)
    const lastY = scaleY(values[values.length - 1])
    ctx.beginPath()
    ctx.fillStyle = isPositive ? '#00e676' : '#ff5252'
    ctx.arc(lastX, lastY, 3, 0, Math.PI * 2)
    ctx.fill()
  }, [data, isPositive])

  if (data.length < 2) return null

  return (
    <canvas
      ref={canvasRef}
      width={100}
      height={32}
      className="challenge-sparkline"
    />
  )
}

export default function ChallengePanel({ challenge, equityCurve }: ChallengePanelProps) {
  // Calculate peak balance - hooks must be called before any early returns
  const peakBalance = useMemo(() => {
    if (!challenge) return 0
    if (!equityCurve || equityCurve.length === 0) return challenge.current_balance
    return Math.max(...equityCurve.map(p => p.value))
  }, [equityCurve, challenge])

  if (!challenge || !challenge.enabled) {
    return null
  }

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  const getOutcomeStyle = () => {
    switch (challenge.outcome) {
      case 'pass':
        return 'outcome-pass'
      case 'fail':
        return 'outcome-fail'
      default:
        return 'outcome-active'
    }
  }

  const getOutcomeText = () => {
    switch (challenge.outcome) {
      case 'pass':
        return 'PASSED'
      case 'fail':
        return 'FAILED'
      default:
        return 'ACTIVE'
    }
  }

  // Calculate progress towards profit target
  const profitProgress = Math.max(0, Math.min(100, (challenge.pnl / challenge.profit_target) * 100))

  const gapFromPeak = peakBalance - challenge.current_balance

  const mffu = challenge.mffu
  const panelTitle = mffu ? `MFFU ${mffu.stage === 'evaluation' ? 'Eval' : mffu.stage === 'sim_funded' ? 'Sim' : 'Live'}` : 'Challenge'

  return (
    <DataPanel title={panelTitle} className="challenge-panel" variant="feature">
      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {/* Row 1: Balance + ACTIVE badge */}
        <div className="challenge-header">
          <div className="challenge-balance">
            <div className="challenge-balance-row">
              <span className="balance-amount">${challenge.current_balance.toLocaleString()}</span>
              {challenge.attempt_number && (
                <span className="challenge-attempt">#{challenge.attempt_number}</span>
              )}
              {mffu && (
                <span className="challenge-stage-badge" style={{
                  background: mffu.stage === 'evaluation' ? 'var(--color-accent, #7c4dff)' : 'var(--accent-green, #00e676)',
                  color: '#0a0a0a',
                  padding: '1px 5px',
                  borderRadius: '3px',
                  fontSize: '9px',
                  fontWeight: 700,
                  letterSpacing: '0.04em',
                  marginLeft: '4px',
                }}>
                  {mffu.stage === 'evaluation' ? 'EVAL' : mffu.stage === 'sim_funded' ? 'SIM' : 'LIVE'}
                </span>
              )}
            </div>
            <span className={`balance-pnl ${challenge.pnl >= 0 ? 'positive' : 'negative'}`}>
              {formatPnL(challenge.pnl)}
            </span>
            {gapFromPeak > 1 && (
              <span className="peak-gap-indicator">
                ↓${gapFromPeak.toFixed(0)} from peak
              </span>
            )}
          </div>
          <div className="challenge-header-right">
            {equityCurve && equityCurve.length > 1 && (
              <MiniSparkline data={equityCurve} isPositive={challenge.pnl >= 0} />
            )}
            <span className={`challenge-outcome ${getOutcomeStyle()}`}>
              {getOutcomeText()}
            </span>
          </div>
        </div>

        {/* Row 2: Drawdown Risk */}
        <div className="challenge-progress">
          <div className="progress-label">
            <span>Drawdown Risk</span>
            <span className={challenge.drawdown_risk_pct > 70 ? 'negative' : challenge.drawdown_risk_pct > 40 ? 'warning' : ''}>
              {challenge.drawdown_risk_pct.toFixed(1)}%
            </span>
          </div>
          <div className="progress-bar">
            <div className="progress-segments">
              {[...Array(10)].map((_, i) => (
                <div
                  key={i}
                  className={`progress-segment ${
                    (i + 1) * 10 <= challenge.drawdown_risk_pct
                      ? challenge.drawdown_risk_pct > 70
                        ? 'filled-danger'
                        : challenge.drawdown_risk_pct > 40
                        ? 'filled-warning'
                        : 'filled'
                      : ''
                  }`}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Row 3: Stats */}
        <div className="grid grid-cols-3 gap-sm">
          <StatDisplay
            label="Trades"
            value={challenge.trades}
            variant="compact"
          />
          <StatDisplay
            label="Win Rate"
            value={`${challenge.win_rate.toFixed(1)}%`}
            variant="compact"
            colorMode="financial"
            positive={challenge.win_rate >= 50}
            negative={challenge.win_rate < 50}
          />
          <StatDisplay
            label="Target"
            value={`$${challenge.profit_target.toLocaleString()}`}
            variant="compact"
            positive
          />
        </div>

        {/* Row 4: Progress to target */}
        {challenge.outcome === 'active' && challenge.pnl > 0 && (
          <div className="challenge-target-progress">
            <div className="target-progress-container">
              <div className="target-progress-bar">
                <div
                  className="target-progress-fill"
                  style={{ width: `${profitProgress}%` }}
                />
                <div className="milestone-markers">
                  <div className="milestone-marker" style={{ left: '25%' }} />
                  <div className="milestone-marker" style={{ left: '50%' }} />
                  <div className="milestone-marker" style={{ left: '75%' }} />
                </div>
              </div>
            </div>
            <span className="target-progress-label">{profitProgress.toFixed(0)}% to target</span>
          </div>
        )}

        {/* MFFU-specific info */}
        {mffu && (
          <div className="grid grid-cols-3 gap-sm">
            <StatDisplay
              label="DD Floor"
              value={mffu.current_drawdown_floor != null ? `$${mffu.current_drawdown_floor.toLocaleString()}` : '--'}
              variant="compact"
            />
            <StatDisplay
              label="Days"
              value={`${mffu.min_days?.days_traded ?? 0}/${mffu.min_days?.days_required ?? 2}`}
              variant="compact"
              positive={mffu.min_days?.met}
              negative={!mffu.min_days?.met}
              colorMode="financial"
            />
            <StatDisplay
              label="Consistency"
              value={mffu.consistency?.met ? 'OK' : `${mffu.consistency?.best_day_pct?.toFixed(0) ?? 0}%`}
              variant="compact"
              positive={mffu.consistency?.met}
              negative={!mffu.consistency?.met && (mffu.consistency?.best_day_pct ?? 0) > 50}
              colorMode="financial"
            />
          </div>
        )}
        {mffu?.drawdown_locked && (
          <div style={{
            fontSize: '10px',
            color: 'var(--accent-green, #00e676)',
            textAlign: 'center',
            opacity: 0.8,
          }}>
            DD Floor Locked at ${mffu.current_drawdown_floor?.toLocaleString()}
          </div>
        )}
      </div>
    </DataPanel>
  )
}
