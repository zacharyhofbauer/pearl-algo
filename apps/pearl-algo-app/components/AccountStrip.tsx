'use client'

import React from 'react'

interface AccountStripProps {
  balance: number | null
  totalPnl: number | null
  dailyPnl: number | null
  trades: number | null
  winRate: number | null
  /** Tradovate equity (netLiq = cash + unrealized) */
  equity?: number | null
  /** Tradovate open (unrealized) P&L */
  openPnl?: number | null
}

function formatMoney(n: number | null): string {
  if (n === null || n === undefined) return '\u2014'
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n >= 0 ? `$${formatted}` : `-$${formatted}`
}

function formatPnL(n: number | null): string {
  if (n === null || n === undefined) return '\u2014'
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n >= 0 ? `+$${formatted}` : `-$${formatted}`
}

const AccountStrip = React.memo(function AccountStrip({ balance, totalPnl, dailyPnl, trades, winRate, equity, openPnl }: AccountStripProps) {
  const tintClass = dailyPnl !== null ? (dailyPnl >= 0 ? 'tint-positive' : 'tint-negative') : ''
  const displayBalance = equity ?? balance
  return (
    <div className={`account-strip ${tintClass}`}>
      <div className="account-strip-item">
        <span className="account-strip-label">Equity</span>
        <span className="account-strip-value">{formatMoney(displayBalance)}</span>
      </div>
      <div className="account-strip-item">
        <span className="account-strip-label">Today</span>
        <span className={`account-strip-value ${dailyPnl !== null ? (dailyPnl >= 0 ? 'positive' : 'negative') : ''}`}>
          {formatPnL(dailyPnl)}
        </span>
      </div>
      <div className="account-strip-item">
        <span className="account-strip-label">Total P&L</span>
        <span className={`account-strip-value ${totalPnl !== null ? (totalPnl >= 0 ? 'positive' : 'negative') : ''}`}>
          {formatPnL(totalPnl)}
        </span>
      </div>
      <div className="account-strip-item">
        <span className="account-strip-label">Trades</span>
        <span className="account-strip-value">{trades !== null ? trades.toLocaleString() : '\u2014'}</span>
      </div>
      <div className="account-strip-item">
        <span className="account-strip-label">Win Rate</span>
        <span className="account-strip-value">{winRate !== null ? `${winRate.toFixed(1)}%` : '\u2014'}</span>
      </div>
      {openPnl != null && openPnl !== 0 && (
        <div className="account-strip-item">
          <span className="account-strip-label">Open P&L</span>
          <span className={`account-strip-value ${openPnl >= 0 ? 'positive' : 'negative'}`}>
            {formatPnL(openPnl)}
          </span>
        </div>
      )}
    </div>
  )
})

export default AccountStrip
