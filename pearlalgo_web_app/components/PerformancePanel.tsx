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

        {activePeriod === '24h' && stats.streak !== undefined && stats.streak > 0 && (
          <div className="col-span-full">
            <div className="stat-display">
              <span className="stat-display-label">Streak</span>
              <div className="streak-indicator">
                <span className={`streak-dots ${stats.streak_type === 'win' ? 'win' : 'loss'}`}>
                  {Array.from({ length: Math.min(stats.streak, 5) }).map((_, i) => (
                    <span key={i} className="streak-dot">●</span>
                  ))}
                  {stats.streak > 5 && <span className="streak-more">+{stats.streak - 5}</span>}
                </span>
                <span className={`stat-display-value ${stats.streak_type === 'win' ? 'stat-value-profit' : 'stat-value-loss'}`}>
                  {stats.streak} {stats.streak_type === 'win' ? 'W' : 'L'}
                </span>
              </div>
            </div>
          </div>
        )}
      </div>
    </DataPanel>
  )
}
