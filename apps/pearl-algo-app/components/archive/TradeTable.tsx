'use client'

import { useState, useMemo } from 'react'

export interface TradeRow {
  trade_id: string
  signal_id: string
  direction: string
  entry_price: number
  exit_price: number
  stop_loss: number | null
  take_profit: number | null
  pnl: number
  is_win: number
  exit_reason: string
  entry_time: string
  exit_time: string
  hold_duration_minutes: number
  regime: string | null
}

interface TradeTableProps {
  trades: TradeRow[]
  onTradeClick?: (trade: TradeRow) => void
}

const PAGE_SIZE = 50

function formatPnL(n: number) {
  const sign = n >= 0 ? '+' : ''
  return `${sign}$${n.toFixed(2)}`
}

function formatTime(iso: string) {
  try {
    const d = new Date(iso)
    return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' })
  } catch {
    return iso
  }
}

function formatDuration(minutes: number): string {
  if (minutes < 1) return '<1m'
  if (minutes < 60) return `${Math.round(minutes)}m`
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

type DirFilter = 'all' | 'long' | 'short'
type WinFilter = 'all' | 'wins' | 'losses'

export default function TradeTable({ trades, onTradeClick }: TradeTableProps) {
  const [sortKey, setSortKey] = useState<keyof TradeRow>('exit_time')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const [dirFilter, setDirFilter] = useState<DirFilter>('all')
  const [winFilter, setWinFilter] = useState<WinFilter>('all')

  const filtered = useMemo(() => {
    let result = trades
    if (dirFilter !== 'all') result = result.filter((t) => t.direction === dirFilter)
    if (winFilter === 'wins') result = result.filter((t) => t.is_win === 1)
    else if (winFilter === 'losses') result = result.filter((t) => t.is_win === 0)
    return result
  }, [trades, dirFilter, winFilter])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const aVal = a[sortKey]
      const bVal = b[sortKey]
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDir === 'asc' ? aVal - bVal : bVal - aVal
      }
      const aStr = String(aVal ?? '')
      const bStr = String(bVal ?? '')
      return sortDir === 'asc' ? aStr.localeCompare(bStr) : bStr.localeCompare(aStr)
    })
  }, [filtered, sortKey, sortDir])

  const totalPages = Math.ceil(sorted.length / PAGE_SIZE)
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  const handleSort = (key: keyof TradeRow) => {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    else {
      setSortKey(key)
      setSortDir('desc')
    }
    setPage(0)
  }

  const handleFilterChange = () => setPage(0)

  const SortIcon = ({ keyName }: { keyName: keyof TradeRow }) => {
    if (sortKey !== keyName) return null
    const Arrow = sortDir === 'asc' ? (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" className="archive-sort-icon" aria-hidden>
        <path d="M5 2L8 6H2L5 2z" />
      </svg>
    ) : (
      <svg width="10" height="10" viewBox="0 0 10 10" fill="currentColor" className="archive-sort-icon" aria-hidden>
        <path d="M5 8L2 4h6L5 8z" />
      </svg>
    )
    return <span className="archive-sort-indicator">{Arrow}</span>
  }

  return (
    <div className="archive-table-section">
      <div className="archive-table-filters">
        <div className="archive-filter-group">
          {(['all', 'long', 'short'] as DirFilter[]).map((f) => (
            <button
              key={f}
              className={`archive-filter-btn ${dirFilter === f ? 'active' : ''} ${f !== 'all' ? `filter-${f}` : ''}`}
              onClick={() => { setDirFilter(f); handleFilterChange() }}
            >
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <div className="archive-filter-group">
          {(['all', 'wins', 'losses'] as WinFilter[]).map((f) => (
            <button
              key={f}
              className={`archive-filter-btn ${winFilter === f ? 'active' : ''}`}
              onClick={() => { setWinFilter(f); handleFilterChange() }}
            >
              {f === 'all' ? 'All' : f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <span className="archive-filter-count">{filtered.length.toLocaleString()} trades</span>
      </div>

      <div className="archive-trade-table-wrap">
        <table className="archive-trade-table">
          <thead>
            <tr>
              <th onClick={() => handleSort('direction')} className="sortable">Dir <SortIcon keyName="direction" /></th>
              <th onClick={() => handleSort('exit_time')} className="sortable">Time <SortIcon keyName="exit_time" /></th>
              <th onClick={() => handleSort('entry_price')} className="sortable">Entry <SortIcon keyName="entry_price" /></th>
              <th onClick={() => handleSort('exit_price')} className="sortable">Exit <SortIcon keyName="exit_price" /></th>
              <th onClick={() => handleSort('pnl')} className="sortable">P&L <SortIcon keyName="pnl" /></th>
              <th onClick={() => handleSort('hold_duration_minutes')} className="sortable">Hold <SortIcon keyName="hold_duration_minutes" /></th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((t, i) => (
              <tr
                key={t.trade_id}
                onClick={() => onTradeClick?.(t)}
                className={`${onTradeClick ? 'clickable' : ''} ${i % 2 === 1 ? 'alt-row' : ''}`}
              >
                <td><span className={`dir-badge ${t.direction}`}>{t.direction}</span></td>
                <td>{formatTime(t.exit_time)}</td>
                <td>{t.entry_price.toLocaleString()}</td>
                <td>{t.exit_price.toLocaleString()}</td>
                <td className={t.pnl >= 0 ? 'positive' : 'negative'}>{formatPnL(t.pnl)}</td>
                <td>{formatDuration(t.hold_duration_minutes)}</td>
                <td>{t.exit_reason?.replace(/_/g, ' ') ?? '\u2014'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="archive-pagination">
          <button
            className="archive-page-btn"
            disabled={page === 0}
            onClick={() => setPage((p) => p - 1)}
          >
            Prev
          </button>
          <span className="archive-page-info">
            Page {page + 1} of {totalPages}
          </span>
          <button
            className="archive-page-btn"
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
