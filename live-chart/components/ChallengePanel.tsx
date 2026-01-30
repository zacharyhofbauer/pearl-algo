'use client'

import { DataPanel } from './DataPanelsContainer'

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
  } | null
}

export default function ChallengePanel({ challenge }: ChallengePanelProps) {
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
          <span className="balance-amount">${challenge.current_balance.toLocaleString()}</span>
          <span className={`balance-pnl ${challenge.pnl >= 0 ? 'positive' : 'negative'}`}>
            {formatPnL(challenge.pnl)}
          </span>
        </div>
        <span className={`challenge-outcome ${getOutcomeStyle()}`}>
          {getOutcomeText()}
        </span>
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
