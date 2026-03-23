'use client'

import React, { useMemo } from 'react'
import type { RecentSignalEvent } from '@/components/TradeDockPanel'

interface WatchlistPanelProps {
  symbol: string
  currentPrice: number | undefined
  priceChange: number
  priceChangePercent: number
  dailyPnL: number
  dailyWins: number
  dailyLosses: number
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

export default function WatchlistPanel({
  symbol,
  currentPrice,
  priceChange,
  priceChangePercent,
  dailyPnL,
  dailyWins,
  dailyLosses,
  recentSignals,
}: WatchlistPanelProps) {
  const changeDir = priceChange >= 0 ? 'up' : 'down'
  const pnlClass = dailyPnL >= 0 ? 'positive' : 'negative'
  const pnlSign = dailyPnL >= 0 ? '+' : ''
  const totalTrades = dailyWins + dailyLosses

  // Show last 10 signals
  const signals = recentSignals.slice(0, 10)

  // Trade log: last 5 exited/closed signals
  const closedTrades = useMemo(() => {
    return recentSignals
      .filter((s) => s.status === 'exited' || s.status === 'closed')
      .slice(0, 5)
  }, [recentSignals])

  return (
    <>
      {/* Symbol + Price */}
      <div className="watchlist-symbol-row">
        <div>
          <div className="watchlist-symbol-name">{symbol}</div>
          <div className={`watchlist-change ${changeDir}`}>
            {priceChange >= 0 ? '+' : ''}{priceChange.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ({priceChangePercent.toFixed(2)}%)
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div className="watchlist-price">
            {currentPrice !== undefined ? currentPrice.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
          </div>
          <div className={`watchlist-pnl ${pnlClass}`}>
            {pnlSign}${dailyPnL.toFixed(2)}
          </div>
        </div>
      </div>

      {/* Stats */}
      <div className="watchlist-stats">
        <span>W<span className="watchlist-stat-value">{dailyWins}</span></span>
        <span>L<span className="watchlist-stat-value">{dailyLosses}</span></span>
        <span>Trades<span className="watchlist-stat-value">{totalTrades}</span></span>
      </div>

      {/* Recent Signals */}
      <div className="watchlist-section-title">Recent Signals</div>
      {signals.length === 0 ? (
        <div className="logs-empty">No recent signals</div>
      ) : (
        signals.map((sig) => {
          const dir = sig.direction?.toLowerCase() || ''
          return (
            <div key={sig.signal_id} className="watchlist-signal-row">
              <span className="watchlist-signal-time">{formatTime(sig.timestamp)}</span>
              <span className={`watchlist-signal-dir ${dir === 'long' ? 'long' : dir === 'short' ? 'short' : ''}`}>
                {(sig.direction || '?').toUpperCase()}
              </span>
              <span className="watchlist-signal-price">
                {sig.entry_price != null ? sig.entry_price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
              </span>
              <span className="watchlist-signal-status">{sig.status}</span>
            </div>
          )
        })
      )}

      {/* Trade Log */}
      <div className="watchlist-section-title">Trade Log</div>
      {closedTrades.length === 0 ? (
        <div className="logs-empty">No closed trades</div>
      ) : (
        closedTrades.map((trade) => {
          const dir = trade.direction?.toLowerCase() || ''
          const pnl = trade.pnl ?? 0
          const pnlPositive = pnl >= 0
          return (
            <div key={trade.signal_id} className="watchlist-trade-row">
              <span className="watchlist-signal-time">{formatTime(trade.timestamp)}</span>
              <span className={`watchlist-signal-dir ${dir === 'long' ? 'long' : dir === 'short' ? 'short' : ''}`}>
                {(trade.direction || '?').toUpperCase()}
              </span>
              {trade.exit_reason && (
                <span className="watchlist-trade-reason" title={trade.exit_reason}>
                  {trade.exit_reason}
                </span>
              )}
              <span className={`watchlist-trade-pnl ${pnlPositive ? 'positive' : 'negative'}`}>
                {pnlPositive ? '+' : ''}${pnl.toFixed(2)}
              </span>
            </div>
          )
        })
      )}
    </>
  )
}
