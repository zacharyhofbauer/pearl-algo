'use client'

import { useState } from 'react'
import type { Position, RecentExit } from '@/stores'
import { apiFetch } from '@/lib/api'

interface OpenPositionsStripProps {
  positions: Position[]
  currentPrice?: number
  recentExits?: RecentExit[]
  onPositionClosed?: () => void
}

// Format time for display
const formatTime = (timestamp: string) => {
  const date = new Date(timestamp)
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export default function OpenPositionsStrip({
  positions,
  currentPrice,
  recentExits = [],
  onPositionClosed,
}: OpenPositionsStripProps) {
  const [closing, setClosing] = useState<string | null>(null)
  const [closingAll, setClosingAll] = useState(false)

  // Calculate unrealized P/L for a position
  const calcUnrealizedPnL = (pos: Position) => {
    if (!currentPrice) return null
    const diff = pos.direction === 'long'
      ? currentPrice - pos.entry_price
      : pos.entry_price - currentPrice
    // MNQ: $2 per point
    return diff * 2
  }

  // Close single position
  const closePosition = async (signalId: string) => {
    setClosing(signalId)
    try {
      const res = await apiFetch(`/api/positions/${signalId}/close`, {
        method: 'POST',
      })
      if (res.ok) {
        onPositionClosed?.()
      } else {
        console.error('Failed to close position:', res.status)
      }
    } catch (err) {
      console.error('Error closing position:', err)
    } finally {
      setClosing(null)
    }
  }

  // Close all positions
  const closeAllPositions = async () => {
    setClosingAll(true)
    try {
      const res = await apiFetch('/api/positions/close-all', {
        method: 'POST',
      })
      if (res.ok) {
        onPositionClosed?.()
      } else {
        console.error('Failed to close all positions:', res.status)
      }
    } catch (err) {
      console.error('Error closing all positions:', err)
    } finally {
      setClosingAll(false)
    }
  }

  // Calculate total unrealized P/L
  const totalUnrealized = positions.reduce((sum, pos) => {
    const pnl = calcUnrealizedPnL(pos)
    return sum + (pnl || 0)
  }, 0)

  // Get recent trades to show (limit to 5)
  const recentTrades = recentExits.slice(0, 5)

  return (
    <div className="positions-strip">
      {/* Open Positions Section */}
      <div className="positions-strip-header">
        <span className="positions-strip-label">
          {positions.length > 0 ? `Open (${positions.length})` : 'Positions'}
        </span>
        {positions.length > 0 && (
          <span className={`positions-strip-total ${totalUnrealized >= 0 ? 'profit' : 'loss'}`}>
            {totalUnrealized >= 0 ? '+' : ''}${totalUnrealized.toFixed(2)}
          </span>
        )}
        {positions.length > 1 && (
          <button
            className="positions-close-all-btn"
            onClick={closeAllPositions}
            disabled={closingAll}
            title="Close all positions"
          >
            {closingAll ? '...' : 'Close All'}
          </button>
        )}
        {positions.length === 1 && (
          <button
            className="positions-close-all-btn"
            onClick={() => closePosition(positions[0].signal_id)}
            disabled={closing === positions[0].signal_id}
            title="Close position"
          >
            {closing === positions[0].signal_id ? '...' : 'Close'}
          </button>
        )}
      </div>

      {/* Open Positions List */}
      {positions.length > 0 ? (
        <div className="positions-strip-list">
          {positions.map((pos) => {
            const unrealized = calcUnrealizedPnL(pos)
            const isClosing = closing === pos.signal_id

            return (
              <div
                key={pos.signal_id}
                className={`position-item ${pos.direction}`}
              >
                <span className={`position-direction ${pos.direction}`}>
                  {pos.direction === 'long' ? '↑L' : '↓S'}
                </span>
                <span className="position-entry">
                  {pos.entry_price.toFixed(2)}
                </span>
                {pos.stop_loss && (
                  <span className="position-sl" title="Stop Loss">
                    SL:{pos.stop_loss.toFixed(0)}
                  </span>
                )}
                {pos.take_profit && (
                  <span className="position-tp" title="Take Profit">
                    TP:{pos.take_profit.toFixed(0)}
                  </span>
                )}
                {unrealized !== null && (
                  <span className={`position-pnl ${unrealized >= 0 ? 'profit' : 'loss'}`}>
                    {unrealized >= 0 ? '+' : ''}${unrealized.toFixed(2)}
                  </span>
                )}
                <button
                  className="position-close-btn"
                  onClick={() => closePosition(pos.signal_id)}
                  disabled={isClosing}
                  title="Close position"
                >
                  {isClosing ? '...' : '×'}
                </button>
              </div>
            )
          })}
        </div>
      ) : (
        <div className="positions-strip-empty-msg">No open positions</div>
      )}

      {/* Recent Trades Section */}
      {recentTrades.length > 0 && (
        <div className="recent-trades-section">
          <div className="recent-trades-label">Recent</div>
          <div className="recent-trades-list">
            {recentTrades.map((trade, idx) => (
              <div
                key={trade.signal_id || idx}
                className={`recent-trade-item ${trade.pnl >= 0 ? 'win' : 'loss'}`}
              >
                <span className={`trade-direction ${trade.direction}`}>
                  {trade.direction === 'long' ? '↑' : '↓'}
                </span>
                <span className="trade-time">{formatTime(trade.exit_time)}</span>
                <span className={`trade-pnl ${trade.pnl >= 0 ? 'profit' : 'loss'}`}>
                  {trade.pnl >= 0 ? '+' : ''}${trade.pnl.toFixed(2)}
                </span>
                {trade.exit_reason && (
                  <span className="trade-reason">{trade.exit_reason.replace(/_/g, ' ')}</span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
