'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import type { PeriodStats, PerformanceStats } from '@/stores'

interface PerformancePanelProps {
  performance: PerformanceStats
  expectancy?: number  // From risk metrics
}

type Period = '24h' | '72h' | '30d'

// Info tooltip component
function InfoTooltip({ text }: { text: string }) {
  return (
    <span className="tooltip-wrapper">
      <span className="info-icon">?</span>
      <span className="tooltip-content">{text}</span>
    </span>
  )
}

export default function PerformancePanel({ performance, expectancy }: PerformancePanelProps) {
  const [activePeriod, setActivePeriod] = useState<Period>('24h')

  const stats = performance[activePeriod]
  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  // Determine WR color based on expectancy, not 50% threshold
  const getWinRateClass = () => {
    // If we have expectancy data, use that for coloring
    if (expectancy !== undefined) {
      if (expectancy > 0.5) return 'wr-profitable'
      if (expectancy < -0.5) return 'wr-unprofitable'
      return 'wr-neutral'
    }
    // Fallback: use P&L for the period
    if (stats.pnl > 0) return 'wr-profitable'
    if (stats.pnl < 0) return 'wr-unprofitable'
    return 'wr-neutral'
  }

  // Show tooltip if WR < 50% but still profitable
  const showWrTooltip = stats.win_rate < 50 && stats.pnl > 0

  return (
    <DataPanel title="Performance" icon="📊">
      <div className="perf-tabs">
        {(['24h', '72h', '30d'] as Period[]).map((period) => (
          <button
            key={period}
            className={`perf-tab ${activePeriod === period ? 'active' : ''}`}
            onClick={() => setActivePeriod(period)}
          >
            {period.toLowerCase()}
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
          <span className="stat-item-label">
            Win Rate
            {showWrTooltip && <InfoTooltip text="Profitable despite sub-50% WR due to R:R" />}
          </span>
          <span className={`stat-item-value ${getWinRateClass()}`}>
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
            <div className="streak-indicator">
              <span className={`streak-dots ${stats.streak_type === 'win' ? 'win' : 'loss'}`}>
                {Array.from({ length: Math.min(stats.streak, 5) }).map((_, i) => (
                  <span key={i} className="streak-dot">●</span>
                ))}
                {stats.streak > 5 && <span className="streak-more">+{stats.streak - 5}</span>}
              </span>
              <span className={`stat-item-value ${stats.streak_type === 'win' ? 'positive' : 'negative'}`}>
                {stats.streak} {stats.streak_type === 'win' ? 'W' : 'L'}
              </span>
            </div>
          </div>
        )}
      </div>
    </DataPanel>
  )
}
