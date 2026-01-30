'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'

interface PeriodStats {
  pnl: number
  trades: number
  wins: number
  losses: number
  win_rate: number
  streak?: number
  streak_type?: string
}

interface PerformancePanelProps {
  performance: {
    '24h': PeriodStats
    '72h': PeriodStats
    '30d': PeriodStats
  }
}

type Period = '24h' | '72h' | '30d'

export default function PerformancePanel({ performance }: PerformancePanelProps) {
  const [activePeriod, setActivePeriod] = useState<Period>('24h')

  const stats = performance[activePeriod]
  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  return (
    <DataPanel title="Performance" icon="📊">
      <div className="perf-tabs">
        {(['24h', '72h', '30d'] as Period[]).map((period) => (
          <button
            key={period}
            className={`perf-tab ${activePeriod === period ? 'active' : ''}`}
            onClick={() => setActivePeriod(period)}
          >
            {period}
          </button>
        ))}
      </div>

      <div className="stats-grid">
        <div className="stat-item">
          <span className="stat-item-label">P&L</span>
          <span className={`stat-item-value ${stats.pnl >= 0 ? 'positive' : 'negative'}`}>
            {formatPnL(stats.pnl)}
          </span>
        </div>

        <div className="stat-item">
          <span className="stat-item-label">Trades</span>
          <span className="stat-item-value">{stats.trades}</span>
        </div>

        <div className="stat-item">
          <span className="stat-item-label">Win Rate</span>
          <span className={`stat-item-value ${stats.win_rate >= 50 ? 'positive' : 'negative'}`}>
            {stats.win_rate.toFixed(1)}%
          </span>
        </div>

        <div className="stat-item">
          <span className="stat-item-label">W/L</span>
          <span className="stat-item-value">
            <span className="positive">{stats.wins}</span>
            <span className="stat-divider">/</span>
            <span className="negative">{stats.losses}</span>
          </span>
        </div>

        {activePeriod === '24h' && stats.streak !== undefined && stats.streak > 0 && (
          <div className="stat-item stat-item-full">
            <span className="stat-item-label">Streak</span>
            <span className={`stat-item-value ${stats.streak_type === 'win' ? 'positive' : 'negative'}`}>
              {stats.streak} {stats.streak_type === 'win' ? 'W' : 'L'}
            </span>
          </div>
        )}
      </div>
    </DataPanel>
  )
}
