'use client'

import { DataPanel } from './DataPanelsContainer'
import { StatDisplay } from './ui'
import type { AgentState, RecentExit } from '@/stores'

interface ActivePositionsPanelProps {
  activeTradesCount: number
  /** Aggregate unrealized P&L across open (virtual) trades (USD) */
  unrealizedPnL?: number | null
  recentExits?: RecentExit[]
  dailyPnL?: number
}

export default function ActivePositionsPanel({
  activeTradesCount,
  unrealizedPnL = null,
  recentExits = [],
  dailyPnL = 0
}: ActivePositionsPanelProps) {
  // Get the most recent trade if any (to show recent activity)
  const lastTrade = recentExits[0]

  // Calculate average trade duration from recent exits
  const avgDuration = recentExits.length > 0
    ? recentExits
        .filter(e => e.duration_seconds)
        .reduce((sum, e) => sum + (e.duration_seconds || 0), 0) /
        Math.max(1, recentExits.filter(e => e.duration_seconds).length)
    : null

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${Math.round(seconds)}s`
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`
    return `${(seconds / 3600).toFixed(1)}h`
  }

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false
    })
  }

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  return (
    <DataPanel title="Active Positions" icon="📍" variant="status">
      <div className="grid grid-cols-2 gap-md">
        <StatDisplay
          label="Open Trades"
          value={activeTradesCount}
          colorMode="status"
          status={activeTradesCount > 0 ? 'ok' : 'inactive'}
          fullWidth={activeTradesCount === 0}
        />

        {activeTradesCount > 0 && (
          <StatDisplay
            label="Unrealized"
            value={unrealizedPnL === null || unrealizedPnL === undefined ? '—' : formatPnL(unrealizedPnL)}
            colorMode="financial"
            positive={typeof unrealizedPnL === 'number' && unrealizedPnL > 0}
            negative={typeof unrealizedPnL === 'number' && unrealizedPnL < 0}
          />
        )}

        {activeTradesCount === 0 && (
          <div className="col-span-full active-positions-empty">
            <span className="empty-icon">🎯</span>
            <span className="empty-text">No active positions</span>
          </div>
        )}

        {activeTradesCount > 0 && (
          <>
            <div className="col-span-full active-positions-note">
              <span className="note-icon">ℹ️</span>
              <span className="note-text">
                {activeTradesCount} open trade{activeTradesCount > 1 ? 's' : ''}. Full details in the Trades dock above.
              </span>
            </div>
          </>
        )}
      </div>

      {/* Recent Activity Section */}
      {lastTrade && (
        <div className="recent-activity-section">
          <div className="recent-activity-header">Last Closed</div>
          <div className="recent-activity-trade">
            <span className={`direction-badge ${lastTrade.direction}`}>
              {lastTrade.direction === 'long' ? '⬆' : '⬇'}
            </span>
            <span className="trade-time">{formatTime(lastTrade.exit_time)}</span>
            <span className={`trade-pnl ${lastTrade.pnl >= 0 ? 'profit' : 'loss'}`}>
              {lastTrade.pnl >= 0 ? '+' : ''}${lastTrade.pnl.toFixed(2)}
            </span>
          </div>
        </div>
      )}

      {/* Session Stats */}
      <div className="session-stats-row">
        <StatDisplay
          label="Day P&L"
          value={`${dailyPnL >= 0 ? '+' : ''}$${dailyPnL.toFixed(2)}`}
          variant="compact"
          colorMode="financial"
          positive={dailyPnL > 0}
          negative={dailyPnL < 0}
        />
        {avgDuration !== null && (
          <StatDisplay
            label="Avg Duration"
            value={formatDuration(avgDuration)}
            variant="compact"
            tooltip="Average trade holding time"
          />
        )}
      </div>
    </DataPanel>
  )
}
