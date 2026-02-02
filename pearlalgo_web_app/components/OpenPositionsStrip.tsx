'use client'

import { useState } from 'react'
import type { Position, RecentExit } from '@/stores'
import { useAdminStore } from '@/stores'
import { apiFetch } from '@/lib/api'
import { calculateUnrealizedPnL } from '@/lib/position'

interface OpenPositionsStripProps {
  positions: Position[]
  currentPrice?: number
  recentExits?: RecentExit[]
  onPositionClosed?: () => void
}

export default function OpenPositionsStrip({
  positions,
  currentPrice,
  recentExits = [],
  onPositionClosed,
}: OpenPositionsStripProps) {
  const [closing, setClosing] = useState<string | null>(null)
  const [closingAll, setClosingAll] = useState(false)
  const { requireAuth } = useAdminStore()

  // Close single position (internal, after auth)
  const doClosePosition = async (signalId: string) => {
    setClosing(signalId)
    try {
      const res = await apiFetch(`/api/positions/${signalId}/close`, {
        method: 'POST',
      })
      if (res.ok) {
        onPositionClosed?.()
      }
    } catch {
      // Position close failed
    } finally {
      setClosing(null)
    }
  }

  // Close all positions (internal, after auth)
  const doCloseAllPositions = async () => {
    setClosingAll(true)
    try {
      const res = await apiFetch('/api/positions/close-all', {
        method: 'POST',
      })
      if (res.ok) {
        onPositionClosed?.()
      }
    } catch {
      // Close all positions failed
    } finally {
      setClosingAll(false)
    }
  }

  // Auth-protected close handlers
  const closePosition = (signalId: string) => {
    requireAuth(() => doClosePosition(signalId))
  }

  const closeAllPositions = () => {
    requireAuth(() => doCloseAllPositions())
  }

  // Calculate total unrealized P/L
  const totalUnrealized = positions.reduce((sum, pos) => {
    const pnl = calculateUnrealizedPnL(pos, currentPrice)
    return sum + (pnl || 0)
  }, 0)

  // Get recent trades (limit to 3 for compact view)
  const recentTrades = recentExits.slice(0, 3)

  // No positions - show minimal strip
  if (positions.length === 0) {
    return (
      <div className="positions-strip compact">
        <span className="positions-strip-label">Positions: 0</span>
        {recentTrades.length > 0 && (
          <div className="recent-inline">
            {recentTrades.map((t, i) => (
              <span key={t.signal_id || i} className={`recent-chip ${t.pnl >= 0 ? 'win' : 'loss'}`}>
                {t.direction === 'long' ? '↑' : '↓'}
                {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(0)}
              </span>
            ))}
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="positions-strip compact">
      {/* Header with count, total P/L, close all */}
      <div className="positions-strip-header">
        <span className="positions-strip-label">Open ({positions.length})</span>
        <span className={`positions-strip-total ${totalUnrealized >= 0 ? 'profit' : 'loss'}`}>
          {totalUnrealized >= 0 ? '+' : ''}${totalUnrealized.toFixed(0)}
        </span>
        {positions.length > 0 && (
          <button
            className="positions-close-all-btn"
            onClick={positions.length === 1 ? () => closePosition(positions[0].signal_id) : closeAllPositions}
            disabled={closingAll || closing !== null}
          >
            {closingAll || closing ? '...' : positions.length === 1 ? '×' : 'Close All'}
          </button>
        )}
      </div>

      {/* Compact positions list */}
      <div className="positions-compact-list">
        {positions.map((pos) => {
          const pnl = calculateUnrealizedPnL(pos, currentPrice)
          return (
            <span
              key={pos.signal_id}
              className={`position-chip ${pos.direction}`}
              title={`Entry: ${pos.entry_price.toFixed(2)}${pos.stop_loss ? ` SL: ${pos.stop_loss.toFixed(0)}` : ''}${pos.take_profit ? ` TP: ${pos.take_profit.toFixed(0)}` : ''}`}
            >
              <span className="chip-dir">{pos.direction === 'long' ? '↑' : '↓'}</span>
              <span className="chip-entry">{pos.entry_price.toFixed(0)}</span>
              {pnl !== null && (
                <span className={`chip-pnl ${pnl >= 0 ? 'profit' : 'loss'}`}>
                  {pnl >= 0 ? '+' : ''}{pnl.toFixed(0)}
                </span>
              )}
            </span>
          )
        })}
      </div>

      {/* Recent trades inline */}
      {recentTrades.length > 0 && (
        <div className="recent-inline">
          <span className="recent-label">Recent:</span>
          {recentTrades.map((t, i) => (
            <span key={t.signal_id || i} className={`recent-chip ${t.pnl >= 0 ? 'win' : 'loss'}`}>
              {t.direction === 'long' ? '↑' : '↓'}
              {t.pnl >= 0 ? '+' : ''}{t.pnl.toFixed(0)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
