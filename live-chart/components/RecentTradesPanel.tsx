'use client'

import { DataPanel } from './DataPanelsContainer'

interface RecentExit {
  signal_id: string
  direction: string
  pnl: number
  exit_reason: string
  exit_time: string
}

interface RecentTradesPanelProps {
  recentExits: RecentExit[]
}

export default function RecentTradesPanel({ recentExits }: RecentTradesPanelProps) {
  if (!recentExits || recentExits.length === 0) {
    return (
      <DataPanel title="Recent Trades" icon="📋">
        <div className="no-trades">No recent trades</div>
      </DataPanel>
    )
  }

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  const formatTime = (timeStr: string) => {
    try {
      const date = new Date(timeStr)
      return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    } catch {
      return '--:--'
    }
  }

  const formatExitReason = (reason: string) => {
    if (!reason) return ''
    return reason
      .replace(/_/g, ' ')
      .replace(/\b\w/g, (c) => c.toUpperCase())
  }

  return (
    <DataPanel title="Recent Trades" icon="📋">
      <div className="recent-trades-list">
        {recentExits.map((exit, index) => (
          <div key={exit.signal_id || index} className="recent-trade">
            <div className="trade-left">
              <span className={`trade-direction-badge ${exit.direction}`}>
                {exit.direction.toUpperCase()}
              </span>
              <span className="trade-time">{formatTime(exit.exit_time)}</span>
            </div>
            <div className="trade-right">
              <span className={`trade-pnl ${exit.pnl >= 0 ? 'positive' : 'negative'}`}>
                {formatPnL(exit.pnl)}
              </span>
              {exit.exit_reason && (
                <span className="trade-reason">{formatExitReason(exit.exit_reason)}</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </DataPanel>
  )
}
