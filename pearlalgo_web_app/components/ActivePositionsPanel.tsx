'use client'

import { memo, useMemo } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { StatDisplay } from './ui'
import { formatDuration, formatTime as formatTimeUtil } from '@/lib/formatters'
import type { RecentExit } from '@/stores'

interface ActivePositionsPanelProps {
  activeTradesCount: number
  recentExits?: RecentExit[]
}

function ActivePositionsPanel({
  activeTradesCount,
  recentExits = [],
}: ActivePositionsPanelProps) {
  // Get the most recent trade if any (to show recent activity)
  const lastTrade = recentExits[0]

  // Calculate average trade duration from recent exits
  const avgDuration = useMemo(() => {
    if (recentExits.length === 0) return null
    const withDuration = recentExits.filter(e => e.duration_seconds)
    if (withDuration.length === 0) return null
    return withDuration.reduce((sum, e) => sum + (e.duration_seconds || 0), 0) / withDuration.length
  }, [recentExits])

  // Use centralized formatters
  const formatTime = (timestamp: string) => formatTimeUtil(timestamp, false)

  return (
    <DataPanel title="Open Positions" icon="📍" variant="status">
      <div className="grid grid-cols-2 gap-md">
        <StatDisplay
          label="Open Trades"
          value={activeTradesCount}
          colorMode="status"
          status={activeTradesCount > 0 ? 'ok' : 'inactive'}
          fullWidth={activeTradesCount === 0}
        />

        {activeTradesCount === 0 && (
          <div className="col-span-full active-positions-empty">
            <span className="empty-icon">🎯</span>
            <span className="empty-text">No active positions</span>
          </div>
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

      {/* Session Stats - only show avg duration if we have data */}
      {avgDuration !== null && (
        <div className="session-stats-row">
          <StatDisplay
            label="Avg Duration"
            value={formatDuration(avgDuration)}
            variant="compact"
            tooltip="Average trade holding time from recent exits"
          />
        </div>
      )}
    </DataPanel>
  )
}

export default memo(ActivePositionsPanel)
