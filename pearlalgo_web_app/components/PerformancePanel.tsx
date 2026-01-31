'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { StatDisplay } from './ui'
import type { PerformanceStats } from '@/stores'

interface PerformancePanelProps {
  performance: PerformanceStats
  expectancy?: number  // From risk metrics
}

type Period = '24h' | '72h' | '30d'

export default function PerformancePanel({ performance, expectancy }: PerformancePanelProps) {
  const [activePeriod, setActivePeriod] = useState<Period>('24h')

  const stats = performance[activePeriod]
  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  // Determine WR color based on expectancy, not 50% threshold
  const getWinRatePositivity = (): { positive?: boolean; negative?: boolean } => {
    // If we have expectancy data, use that for coloring
    if (expectancy !== undefined) {
      if (expectancy > 0.5) return { positive: true }
      if (expectancy < -0.5) return { negative: true }
      return {}
    }
    // Fallback: use P&L for the period
    if (stats.pnl > 0) return { positive: true }
    if (stats.pnl < 0) return { negative: true }
    return {}
  }

  // Show tooltip if WR < 50% but still profitable
  const showWrTooltip = stats.win_rate < 50 && stats.pnl > 0

  return (
    <DataPanel title="Performance" icon="📊" variant="feature">
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

      <div className="grid grid-cols-2 gap-md">
        <StatDisplay
          label="P&L"
          value={formatPnL(stats.pnl)}
          colorMode="financial"
          positive={stats.pnl >= 0}
          negative={stats.pnl < 0}
        />

        <StatDisplay
          label="Trades"
          value={stats.trades}
        />

        <StatDisplay
          label="Win Rate"
          value={`${stats.win_rate.toFixed(1)}%`}
          colorMode="financial"
          tooltip={showWrTooltip ? "Profitable despite sub-50% WR due to R:R" : undefined}
          {...getWinRatePositivity()}
        />

        <StatDisplay
          label="W/L"
          value={
            <>
              <span className="stat-value-profit">{stats.wins}</span>
              <span className="stat-divider">/</span>
              <span className="stat-value-loss">{stats.losses}</span>
            </>
          }
        />

        {/* Streak display for all periods */}
        {stats.streak !== undefined && stats.streak > 0 && (() => {
          const streakCount = stats.streak || 0
          const streakType = stats.streak_type || 'win'
          const dotCount = Math.min(streakCount, 8)

          return (
            <div className="col-span-full">
              <div className="streak-display-enhanced">
                <div className="streak-header">
                  <span className="streak-label">Current Streak</span>
                  <span className={`streak-badge ${streakType === 'win' ? 'win' : 'loss'}`}>
                    {streakType === 'win' ? 'HOT' : 'COLD'}
                  </span>
                </div>
                <div className="streak-indicator-enhanced">
                  <div className={`streak-dots-row ${streakType === 'win' ? 'win' : 'loss'}`}>
                    {Array.from({ length: dotCount }).map((_, i) => (
                      <span
                        key={i}
                        className="streak-dot-enhanced"
                        style={{
                          opacity: 0.4 + (i / dotCount) * 0.6,
                          animationDelay: `${i * 0.1}s`
                        }}
                      />
                    ))}
                  </div>
                  <span className={`streak-count ${streakType === 'win' ? 'win' : 'loss'}`}>
                    {streakCount}
                    <span className="streak-type">{streakType === 'win' ? 'W' : 'L'}</span>
                  </span>
                </div>
                {streakCount >= 3 && (
                  <span className="streak-message">
                    {streakType === 'win'
                      ? streakCount >= 5 ? 'On fire!' : 'Keep it up!'
                      : streakCount >= 5 ? 'Stay disciplined' : 'Patience'}
                  </span>
                )}
              </div>
            </div>
          )
        })()}
      </div>
    </DataPanel>
  )
}
