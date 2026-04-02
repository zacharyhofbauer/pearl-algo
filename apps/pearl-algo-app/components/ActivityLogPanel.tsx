'use client'

import React, { useMemo } from 'react'
import type { RecentSignalEvent } from '@/components/TradeDockPanel'

interface ActivityLogPanelProps {
  recentSignals: RecentSignalEvent[]
}

function formatTime(ts: string | null | undefined): string {
  if (!ts) return '--:--'
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' })
  } catch {
    return '--:--'
  }
}

export default function ActivityLogPanel({ recentSignals }: ActivityLogPanelProps) {
  // Build activity entries from signals — show all entries/exits chronologically
  const entries = useMemo(() => {
    return recentSignals
      .filter((s) => s.status === 'entered' || s.status === 'active' || s.status === 'exited' || s.status === 'closed' || s.status === 'rejected' || s.status === 'skipped')
      .slice(0, 50)
  }, [recentSignals])

  if (entries.length === 0) {
    return <div className="logs-empty">No activity yet</div>
  }

  return (
    <>
      {entries.map((sig) => {
        const dir = (sig.direction || '?').toUpperCase()
        const isEntry = sig.status === 'entered' || sig.status === 'active'
        const isExit = sig.status === 'exited' || sig.status === 'closed'
        const isReject = sig.status === 'rejected' || sig.status === 'skipped'
        const price = sig.entry_price != null ? sig.entry_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'

        let typeLabel = 'ENTRY'
        let typeClass = 'entry'
        if (isExit) { typeLabel = 'EXIT'; typeClass = sig.pnl != null && sig.pnl < 0 ? 'exit-loss' : 'exit-win' }
        if (isReject) { typeLabel = 'SKIP'; typeClass = 'reject' }

        const pnlText = isExit && sig.pnl != null
          ? `P&L: ${sig.pnl >= 0 ? '+' : ''}$${sig.pnl.toFixed(2)}`
          : null

        const reason = isExit && sig.exit_reason ? `(${sig.exit_reason})` : null

        return (
          <div key={sig.signal_id + '-' + sig.status} className="activity-row">
            <span className="activity-time">{formatTime(sig.timestamp)}</span>
            <span className={`activity-type ${typeClass}`}>{typeLabel}</span>
            <span className="activity-detail">
              <span className={`activity-dir ${dir === 'LONG' ? 'long' : 'short'}`}>{dir}</span>
              {isExit && reason && <span className="activity-reason">{reason}</span>}
              {!isExit && <span className="activity-price">@ {price}</span>}
            </span>
            {pnlText && (
              <span className={`activity-pnl ${sig.pnl! >= 0 ? 'positive' : 'negative'}`}>
                {pnlText}
              </span>
            )}
          </div>
        )
      })}
    </>
  )
}
