'use client'

import { useEffect, useRef } from 'react'
import { DataPanel } from './DataPanelsContainer'

interface EquityCurvePoint {
  time: number
  value: number
}

interface ChallengePanelProps {
  challenge: {
    enabled: boolean
    current_balance: number
    pnl: number
    trades: number
    wins: number
    win_rate: number
    drawdown_risk_pct: number
    outcome: 'active' | 'pass' | 'fail'
    profit_target: number
    max_drawdown: number
    attempt_number?: number
  } | null
  equityCurve?: EquityCurvePoint[]
}

// Mini sparkline component for challenge equity
function MiniSparkline({ data, isPositive }: { data: EquityCurvePoint[], isPositive: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || data.length < 2) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const width = canvas.width
    const height = canvas.height
    const padding = 2

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

    // Draw line
    ctx.beginPath()
    ctx.strokeStyle = isPositive ? '#00e676' : '#ff5252'
    ctx.lineWidth = 1.5
    ctx.lineJoin = 'round'

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
    ctx.arc(lastX, lastY, 2, 0, Math.PI * 2)
    ctx.fill()
  }, [data, isPositive])

  if (data.length < 2) return null

  return (
    <canvas
      ref={canvasRef}
      width={80}
      height={24}
      className="challenge-sparkline"
    />
  )
}

export default function ChallengePanel({ challenge, equityCurve }: ChallengePanelProps) {
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

  return (
    <DataPanel title="Challenge" icon="🎯" className="challenge-panel">
      <div className="challenge-header">
        <div className="challenge-balance">
          <div className="challenge-balance-row">
            <span className="balance-amount">${challenge.current_balance.toLocaleString()}</span>
            {challenge.attempt_number && (
              <span className="challenge-attempt">#{challenge.attempt_number}</span>
            )}
          </div>
          <span className={`balance-pnl ${challenge.pnl >= 0 ? 'positive' : 'negative'}`}>
            {formatPnL(challenge.pnl)}
          </span>
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

      <div className="challenge-stats">
        <div className="challenge-stat">
          <span className="challenge-stat-label">Trades</span>
          <span className="challenge-stat-value">{challenge.trades}</span>
        </div>
        <div className="challenge-stat">
          <span className="challenge-stat-label">Win Rate</span>
          <span className={`challenge-stat-value ${challenge.win_rate >= 50 ? 'positive' : 'negative'}`}>
            {challenge.win_rate.toFixed(1)}%
          </span>
        </div>
        <div className="challenge-stat">
          <span className="challenge-stat-label">Target</span>
          <span className="challenge-stat-value positive">${challenge.profit_target.toLocaleString()}</span>
        </div>
      </div>

      {challenge.outcome === 'active' && challenge.pnl > 0 && (
        <div className="challenge-target-progress">
          <div className="target-progress-bar">
            <div
              className="target-progress-fill"
              style={{ width: `${profitProgress}%` }}
            />
          </div>
          <span className="target-progress-label">{profitProgress.toFixed(0)}% to target</span>
        </div>
      )}
    </DataPanel>
  )
}
