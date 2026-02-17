'use client'

import { useEffect } from 'react'
import type { TradeRow } from './TradeTable'

interface Props {
  trade: TradeRow
  onClose: () => void
}

function formatPnL(n: number): string {
  const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n >= 0 ? `+$${s}` : `-$${s}`
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('en-US', {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', second: '2-digit',
    })
  } catch {
    return iso
  }
}

function formatDuration(minutes: number): string {
  if (minutes < 1) return `${Math.round(minutes * 60)}s`
  if (minutes < 60) return `${Math.round(minutes)}m`
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

const REASON_EXPLAIN: Record<string, string> = {
  take_profit: 'Price hit the take-profit target.',
  stop_loss: 'Price hit the stop-loss level.',
  close_all_requested: 'A close-all command was issued.',
  daily_auto_flat: 'Auto-flattened at end of trading day.',
  weekend_flatten: 'Auto-flattened before weekend close.',
  manual_close_requested: 'Manually closed by operator.',
}

export default function TradeDetail({ trade, onClose }: Props) {
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [onClose])

  const spread = Math.abs(trade.exit_price - trade.entry_price)

  return (
    <>
      <div className="trade-detail-backdrop" onClick={onClose} />
      <aside className="trade-detail-panel" role="dialog" aria-label="Trade detail">
        <div className="trade-detail-header">
          <span className={`dir-badge ${trade.direction}`}>{trade.direction.toUpperCase()}</span>
          <span className={`trade-detail-pnl ${trade.pnl >= 0 ? 'positive' : 'negative'}`}>
            {formatPnL(trade.pnl)}
          </span>
          <button className="trade-detail-close" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>

        <div className="trade-detail-body">
          <div className="trade-detail-row">
            <span className="trade-detail-label">Entry</span>
            <span className="trade-detail-value">{formatTime(trade.entry_time)}</span>
          </div>
          <div className="trade-detail-row">
            <span className="trade-detail-label">Exit</span>
            <span className="trade-detail-value">{formatTime(trade.exit_time)}</span>
          </div>
          <div className="trade-detail-row">
            <span className="trade-detail-label">Duration</span>
            <span className="trade-detail-value">{formatDuration(trade.hold_duration_minutes)}</span>
          </div>

          <div className="trade-detail-divider" />

          <div className="trade-detail-row">
            <span className="trade-detail-label">Entry Price</span>
            <span className="trade-detail-value">{trade.entry_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
          </div>
          <div className="trade-detail-row">
            <span className="trade-detail-label">Exit Price</span>
            <span className="trade-detail-value">{trade.exit_price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
          </div>
          <div className="trade-detail-row">
            <span className="trade-detail-label">Spread</span>
            <span className="trade-detail-value">{spread.toFixed(2)} pts</span>
          </div>

          <div className="trade-detail-divider" />

          <div className="trade-detail-row">
            <span className="trade-detail-label">Exit Reason</span>
            <span className="trade-detail-value">{trade.exit_reason?.replace(/_/g, ' ') ?? '—'}</span>
          </div>
          {trade.exit_reason && REASON_EXPLAIN[trade.exit_reason] && (
            <p className="trade-detail-explain">{REASON_EXPLAIN[trade.exit_reason]}</p>
          )}

          {trade.regime && (
            <div className="trade-detail-row">
              <span className="trade-detail-label">Regime</span>
              <span className="trade-detail-value">{trade.regime}</span>
            </div>
          )}
        </div>
      </aside>
    </>
  )
}
