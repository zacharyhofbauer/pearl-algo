'use client'

import { useMemo, useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import type { DirectionBreakdown, Position, StatusBreakdown } from '@/stores'
import { apiFetch } from '@/lib/api'
import { useOperatorStore } from '@/stores'

export interface RecentTradeRow {
  signal_id?: string
  symbol?: string
  direction?: 'long' | 'short' | string
  position_size?: number | null
  entry_time?: string | null
  entry_price?: number | null
  exit_time?: string | null
  exit_price?: number | null
  pnl?: number | null
  exit_reason?: string | null
}

export interface PerformancePeriodSummary {
  pnl: number
  trades: number
  wins: number
  losses: number
  win_rate: number
}

export interface PerformanceSummary {
  as_of: string
  td: PerformancePeriodSummary
  yday: PerformancePeriodSummary
  wtd: PerformancePeriodSummary
  mtd: PerformancePeriodSummary
  ytd: PerformancePeriodSummary
  all: PerformancePeriodSummary
}

interface TradeDockPanelProps {
  positions: Position[]
  recentTrades: RecentTradeRow[]
  /** Fallback symbol if a row does not include one */
  symbol?: string
  /** Current market price (used for unrealized calc) */
  currentPrice?: number
  /** Aggregate unrealized P&L across open (virtual) trades (USD) */
  openUnrealizedPnL?: number | null
  /** Common performance summary periods */
  performanceSummary?: PerformanceSummary | null
  /** Optional analytics breakdowns (for TradingView-like trade stats) */
  directionBreakdown?: DirectionBreakdown | null
  statusBreakdown?: StatusBreakdown | null
  /** Default max rows before “Show all” toggle */
  maxOpenRows?: number
  maxRecentRows?: number
  /** Daily realized P&L (USD) for header summary */
  dailyPnL?: number
  /** Daily win count for header summary */
  dailyWins?: number
  /** Daily loss count for header summary */
  dailyLosses?: number
  /** Active positions count (if provided by agent state) */
  activeTradesCount?: number
}

type Tab = 'open' | 'recent'

function getUsdPerPoint(sym?: string | null): number | null {
  const s = (sym || '').toUpperCase().trim()
  // Common US index futures (most likely in this app)
  if (s === 'MNQ') return 2
  if (s === 'NQ') return 20
  if (s === 'MES') return 5
  if (s === 'ES') return 50
  if (s === 'MYM') return 0.5
  if (s === 'YM') return 5
  if (s === 'M2K') return 5
  if (s === 'RTY') return 50
  return null
}

function formatPrice(price?: number | null): string {
  if (price === null || price === undefined || Number.isNaN(price)) return '—'
  return price.toFixed(2)
}

function formatTime(ts?: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
}

function formatSigned(n: number, decimals = 2): string {
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(decimals)}`
}

function formatPnL(pnl?: number | null): string {
  if (pnl === null || pnl === undefined || Number.isNaN(pnl)) return '—'
  const sign = pnl >= 0 ? '+' : ''
  return `${sign}$${pnl.toFixed(2)}`
}

function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${mins}m`
}

function computeDurationSeconds(entryTime?: string | null, exitTime?: string | null): number | null {
  if (!entryTime || !exitTime) return null
  const a = new Date(entryTime).getTime()
  const b = new Date(exitTime).getTime()
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  return Math.max(0, Math.round((b - a) / 1000))
}

function formatExitReason(reason: string): { text: string; type: string } {
  if (!reason) return { text: '', type: '' }
  const lowerReason = reason.toLowerCase()

  if (lowerReason.includes('close_all') || lowerReason.includes('close all')) {
    return { text: 'Manual Close', type: 'manual' }
  }
  if (lowerReason.includes('stop') || lowerReason.includes('sl_')) {
    return { text: 'Stop Loss', type: 'stop' }
  }
  if (lowerReason.includes('target') || lowerReason.includes('tp_') || lowerReason.includes('profit')) {
    return { text: 'Target Hit', type: 'target' }
  }
  if (lowerReason.includes('trail')) {
    return { text: 'Trailing Stop', type: 'trail' }
  }
  if (lowerReason.includes('time') || lowerReason.includes('eod') || lowerReason.includes('session')) {
    return { text: 'Time Exit', type: 'time' }
  }

  return {
    text: reason.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    type: 'other',
  }
}

export default function TradeDockPanel({
  positions,
  recentTrades,
  symbol,
  currentPrice,
  openUnrealizedPnL,
  performanceSummary,
  directionBreakdown,
  statusBreakdown,
  maxOpenRows,
  maxRecentRows,
  dailyPnL,
  dailyWins,
  dailyLosses,
  activeTradesCount,
}: TradeDockPanelProps) {
  const [tab, setTab] = useState<Tab>('open')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showSummary, setShowSummary] = useState(true)
  const [showPerf, setShowPerf] = useState(true)
  const [showAllOpen, setShowAllOpen] = useState(false)
  const [showAllRecent, setShowAllRecent] = useState(false)
  const [confirmCloseAll, setConfirmCloseAll] = useState(false)
  const [confirmCloseId, setConfirmCloseId] = useState<string | null>(null)
  const [closeBusy, setCloseBusy] = useState(false)
  const [closeResult, setCloseResult] = useState<{ type: 'ok' | 'error'; message: string } | null>(null)

  const openLimit = maxOpenRows ?? 6
  const recentLimit = maxRecentRows ?? 8

  const openRows = useMemo(() => {
    const fallbackSymbol = symbol || '—'
    return (positions || [])
      .map((p) => ({
        ...p,
        symbol: p.symbol || fallbackSymbol,
      }))
      .sort((a, b) => {
        const at = a.entry_time ? (new Date(a.entry_time).getTime() || 0) : 0
        const bt = b.entry_time ? (new Date(b.entry_time).getTime() || 0) : 0
        return bt - at
      })
  }, [positions, symbol])

  const recentRows = useMemo(() => {
    const fallbackSymbol = symbol || '—'
    return (recentTrades || [])
      .map((t) => ({
        ...t,
        symbol: t.symbol || fallbackSymbol,
        position_size: t.position_size ?? null,
      }))
      .sort((a, b) => {
        const at = a.exit_time ? (new Date(a.exit_time).getTime() || 0) : 0
        const bt = b.exit_time ? (new Date(b.exit_time).getTime() || 0) : 0
        return bt - at
      })
  }, [recentTrades, symbol])

  const openCount = openRows.length
  const recentCount = recentRows.length

  const headerPosCount = typeof activeTradesCount === 'number' ? activeTradesCount : openCount

  const headerStats = (
    <div className="trade-dock-header-stats" aria-label="Daily summary">
      {typeof dailyPnL === 'number' && (
        <div className={`dock-stat pnl ${dailyPnL >= 0 ? 'positive' : 'negative'}`}>
          <span className="dock-stat-k">P&amp;L</span>
          <span className="dock-stat-v">{formatPnL(dailyPnL)}</span>
        </div>
      )}
      {(typeof dailyWins === 'number' || typeof dailyLosses === 'number') && (
        <div className="dock-stat wl">
          <span className="dock-stat-k">W/L</span>
          <span className="dock-stat-v">
            <span className="win">{typeof dailyWins === 'number' ? dailyWins : 0}</span>/
            <span className="loss">{typeof dailyLosses === 'number' ? dailyLosses : 0}</span>
          </span>
        </div>
      )}
      <div className="dock-stat pos">
        <span className="dock-stat-k">Pos</span>
        <span className="dock-stat-v">{headerPosCount} pos</span>
      </div>
    </div>
  )

  const displayOpen = showAllOpen ? openRows : openRows.slice(0, openLimit)
  const displayRecent = showAllRecent ? recentRows : recentRows.slice(0, recentLimit)

  const hasSummaryData = !!directionBreakdown || !!statusBreakdown

  const formatSummaryPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(0)}`
  }

  const exitReasonStats = useMemo(() => {
    return recentRows.reduce((acc, trade) => {
      const raw = (trade.exit_reason || '').toString()
      if (!raw) return acc
      const { text } = formatExitReason(raw)
      if (!acc[text]) {
        acc[text] = { wins: 0, total: 0, pnl: 0 }
      }
      acc[text].total++
      const pnl = typeof trade.pnl === 'number' ? trade.pnl : 0
      if (pnl > 0) acc[text].wins++
      acc[text].pnl += pnl
      return acc
    }, {} as Record<string, { wins: number; total: number; pnl: number }>)
  }, [recentRows])

  const sortedExitReasons = useMemo(() => {
    return Object.entries(exitReasonStats)
      .filter(([_, stats]) => stats.total >= 2)
      .sort((a, b) => b[1].total - a[1].total)
  }, [exitReasonStats])

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id))
  }

  const computeUnrealizedUsd = (p: Position): number | null => {
    if (currentPrice === null || currentPrice === undefined) return null
    const usdPerPoint = getUsdPerPoint(p.symbol || symbol || null)
    if (!usdPerPoint) return null
    const dir = p.direction === 'long' ? 1 : -1
    const qty = p.position_size ?? 1
    return (currentPrice - p.entry_price) * dir * qty * usdPerPoint
  }

  const operatorUnlocked = useOperatorStore((s) => s.isUnlocked)

  const requestCloseAll = async () => {
    if (closeBusy) return
    setCloseBusy(true)
    setCloseResult(null)
    try {
      const res = await apiFetch('/api/close-all-trades', { method: 'POST' })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data?.detail || `Close-all failed (${res.status})`)
      }
      setCloseResult({ type: 'ok', message: data?.message || 'Close-all requested.' })
      setConfirmCloseAll(false)
      setConfirmCloseId(null)
    } catch (e) {
      setCloseResult({ type: 'error', message: e instanceof Error ? e.message : 'Close-all failed' })
    } finally {
      setCloseBusy(false)
    }
  }

  const requestCloseTrade = async (signalId: string) => {
    if (closeBusy) return
    setCloseBusy(true)
    setCloseResult(null)
    try {
      const res = await apiFetch('/api/close-trade', {
        method: 'POST',
        body: JSON.stringify({ signal_id: signalId }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data?.detail || `Close failed (${res.status})`)
      }
      setCloseResult({ type: 'ok', message: data?.message || 'Close requested.' })
      setConfirmCloseId(null)
    } catch (e) {
      setCloseResult({ type: 'error', message: e instanceof Error ? e.message : 'Close failed' })
    } finally {
      setCloseBusy(false)
    }
  }

  return (
    <div className="trade-dock-wrapper">
      <DataPanel
        title="Trades"
        padding="none"
        className="trade-dock-panel"
        headerRight={headerStats}
      >
        <div className="trade-dock">
          <div className="trade-dock-tabs" role="tablist" aria-label="Trades">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'open'}
              className={`trade-dock-tab ${tab === 'open' ? 'active' : ''}`}
              onClick={() => {
                setTab('open')
                setExpandedId(null)
              }}
            >
              Open <span className="trade-dock-count">{openCount}</span>
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'recent'}
              className={`trade-dock-tab ${tab === 'recent' ? 'active' : ''}`}
              onClick={() => {
                setTab('recent')
                setExpandedId(null)
              }}
            >
              Recent <span className="trade-dock-count">{recentCount}</span>
            </button>

            <div className="trade-dock-spacer" />

            {currentPrice !== undefined && currentPrice !== null && (
              <div className="trade-dock-last">
                <span className="trade-dock-last-label">Last</span>
                <span className="trade-dock-last-value">{formatPrice(currentPrice)}</span>
              </div>
            )}
          </div>

          <div className="trade-dock-content">
            {performanceSummary && (
              <div className="trade-stats-summary-wrapper">
                <button
                  className="trade-stats-summary-toggle"
                  onClick={() => setShowPerf(!showPerf)}
                  type="button"
                >
                  <span className="trade-stats-summary-label">Performance</span>
                  <span className="trade-stats-summary-icon">{showPerf ? '▲' : '▼'}</span>
                </button>

                {showPerf && (
                  <div className="trade-perf-strip">
                    {([
                      ['Today', performanceSummary.td],
                      ['Yesterday', performanceSummary.yday],
                      ['Week', performanceSummary.wtd],
                      ['Month', performanceSummary.mtd],
                      ['Year', performanceSummary.ytd],
                      ['All Time', performanceSummary.all],
                    ] as Array<[string, PerformancePeriodSummary]>).map(([label, p]) => (
                      <div key={label} className="trade-perf-pill">
                        <div className="trade-perf-label">{label}</div>
                        <div className={`trade-perf-value ${p.pnl >= 0 ? 'positive' : 'negative'}`}>
                          {p.pnl >= 0 ? '+' : '-'}${Math.abs(p.pnl).toFixed(0)}
                        </div>
                        <div className="trade-perf-sub">
                          {p.trades} trades • {p.win_rate.toFixed(0)}%
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {tab === 'recent' && hasSummaryData && (
              <div className="trade-stats-summary-wrapper">
                <button
                  className="trade-stats-summary-toggle"
                  onClick={() => setShowSummary(!showSummary)}
                  type="button"
                >
                  <span className="trade-stats-summary-label">Trade Stats</span>
                  <span className="trade-stats-summary-icon">{showSummary ? '▲' : '▼'}</span>
                </button>

                {showSummary && (
                  <div className="trade-stats-summary">
                    {directionBreakdown && (
                      <div className="trade-stats-row">
                        <span className="trade-stats-label">Direction:</span>
                        <div className="trade-stats-values">
                          <span className="direction-long">
                            LONG: {directionBreakdown.long.count} ({formatSummaryPnL(directionBreakdown.long.pnl)})
                          </span>
                          <span className="direction-short">
                            SHORT: {directionBreakdown.short.count} ({formatSummaryPnL(directionBreakdown.short.pnl)})
                          </span>
                        </div>
                      </div>
                    )}

                    {statusBreakdown && (
                      <div className="trade-stats-row">
                        <span className="trade-stats-label">Status:</span>
                        <div className="trade-stats-values">
                          <span className="badge-entered">{statusBreakdown.entered} Active</span>
                          <span className="badge-exited">{statusBreakdown.exited} Closed</span>
                          {statusBreakdown.cancelled > 0 && (
                            <span className="badge-cancelled">{statusBreakdown.cancelled} Cancelled</span>
                          )}
                        </div>
                      </div>
                    )}

                    {sortedExitReasons.length > 0 && (
                      <div className="exit-reason-stats">
                        <span className="trade-stats-label">Win% by Exit:</span>
                        <div className="exit-reason-grid">
                          {sortedExitReasons.map(([reason, stats]) => {
                            const winRate = (stats.wins / stats.total) * 100
                            return (
                              <div key={reason} className="exit-reason-stat">
                                <span className="exit-reason-name">{reason}</span>
                                <span className={`exit-reason-winrate ${winRate >= 50 ? 'positive' : 'negative'}`}>
                                  {winRate.toFixed(0)}%
                                </span>
                                <span className="exit-reason-count">({stats.total})</span>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {tab === 'open' ? (
              openCount === 0 ? (
                <div className="trade-dock-empty">No open positions</div>
              ) : (
                <>
                  <div className="trade-dock-actions">
                    <div className="trade-dock-actions-left">
                      <span className="trade-dock-actions-label">Open</span>
                      <span className="trade-dock-actions-value">{openCount}</span>
                      {openUnrealizedPnL !== undefined && openUnrealizedPnL !== null && (
                        <span className={`trade-dock-actions-upnl ${openUnrealizedPnL >= 0 ? 'positive' : 'negative'}`}>
                          Unrealized: {openUnrealizedPnL >= 0 ? '+' : ''}${openUnrealizedPnL.toFixed(2)}
                        </span>
                      )}
                    </div>

                    <div className="trade-dock-actions-right">
                      {!confirmCloseAll ? (
                        <button
                          type="button"
                          className="trade-action-btn trade-action-btn-danger"
                          onClick={() => {
                            setConfirmCloseAll(true)
                            setConfirmCloseId(null)
                            setCloseResult(null)
                          }}
                          disabled={closeBusy || !operatorUnlocked}
                          title={!operatorUnlocked ? 'Read-only (operator locked)' : undefined}
                        >
                          Close All
                        </button>
                      ) : (
                        <div className="trade-action-confirm">
                          <button
                            type="button"
                            className="trade-action-btn trade-action-btn-danger"
                            onClick={requestCloseAll}
                            disabled={closeBusy || !operatorUnlocked}
                          >
                            {closeBusy ? 'Sending…' : 'Confirm'}
                          </button>
                          <button
                            type="button"
                            className="trade-action-btn trade-action-btn-neutral"
                            onClick={() => setConfirmCloseAll(false)}
                            disabled={closeBusy}
                          >
                            Cancel
                          </button>
                        </div>
                      )}
                    </div>
                  </div>

                  {closeResult && (
                    <div className={`trade-controls-result ${closeResult.type === 'ok' ? 'ok' : 'error'}`}>
                      {closeResult.message}
                    </div>
                  )}

                  <div className="recent-trades-list trade-dock-list" aria-label="Open positions">
                    {displayOpen.map((p) => {
                      const id = p.signal_id
                      const isExpanded = expandedId === id
                      const uUsd = computeUnrealizedUsd(p)

                      return (
                        <div key={id} className="recent-trade-wrapper">
                          <div
                            className={`recent-trade ${isExpanded ? 'expanded' : ''}`}
                            onClick={() => toggleExpand(id)}
                          >
                            <div className="trade-left">
                              <span className={`trade-direction-badge ${p.direction}`}>
                                {p.direction.toUpperCase()}
                              </span>
                              <div className="trade-info">
                                <span className="trade-time">
                                  {(p.symbol || symbol || '—')} • Opened {formatTime(p.entry_time || null)}
                                </span>
                                <span className="trade-prices">
                                  {formatPrice(p.entry_price)} → {formatPrice(currentPrice ?? null)}
                                </span>
                              </div>
                            </div>
                            <div className="trade-right">
                              <span className={`trade-pnl ${uUsd === null ? '' : uUsd >= 0 ? 'positive' : 'negative'}`}>
                                {uUsd === null ? '—' : `${uUsd >= 0 ? '+' : ''}$${Math.abs(uUsd).toFixed(2)}`}
                              </span>
                              <span className="trade-reason-badge reason-open">OPEN</span>
                            </div>
                            <span className="trade-expand-icon">{isExpanded ? '▲' : '▼'}</span>
                          </div>

                          {isExpanded && (
                            <div className="trade-details">
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Symbol</span>
                                <span className="trade-detail-value">{p.symbol || symbol || '—'}</span>
                              </div>
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Qty</span>
                                <span className="trade-detail-value">{p.position_size ?? '—'}</span>
                              </div>
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Entry</span>
                                <span className="trade-detail-value">
                                  {formatPrice(p.entry_price)} @ {formatTime(p.entry_time || null)}
                                </span>
                              </div>
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Last</span>
                                <span className="trade-detail-value">{formatPrice(currentPrice ?? null)}</span>
                              </div>
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Unrealized</span>
                                <span className={`trade-detail-value ${uUsd === null ? '' : uUsd >= 0 ? 'positive' : 'negative'}`}>
                                  {uUsd === null ? '—' : `${uUsd >= 0 ? '+' : ''}$${Math.abs(uUsd).toFixed(2)}`}
                                </span>
                              </div>
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">TP</span>
                                <span className="trade-detail-value">
                                  {formatPrice(p.take_profit ?? null)}
                                </span>
                              </div>
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">SL</span>
                                <span className="trade-detail-value">
                                  {formatPrice(p.stop_loss ?? null)}
                                </span>
                              </div>
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Signal ID</span>
                                <span className="trade-detail-value">{p.signal_id}</span>
                              </div>

                              <div className="trade-action-row">
                                {!confirmCloseId || confirmCloseId !== id ? (
                                  <button
                                    type="button"
                                    className="trade-action-btn trade-action-btn-danger"
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      setConfirmCloseId(id)
                                      setConfirmCloseAll(false)
                                      setCloseResult(null)
                                    }}
                                    disabled={closeBusy || !operatorUnlocked}
                                    title={!operatorUnlocked ? 'Read-only (operator locked)' : undefined}
                                  >
                                    Close Trade
                                  </button>
                                ) : (
                                  <div className="trade-action-confirm">
                                    <button
                                      type="button"
                                      className="trade-action-btn trade-action-btn-danger"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        requestCloseTrade(id)
                                      }}
                                      disabled={closeBusy || !operatorUnlocked}
                                    >
                                      {closeBusy ? 'Sending…' : 'Confirm'}
                                    </button>
                                    <button
                                      type="button"
                                      className="trade-action-btn trade-action-btn-neutral"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        setConfirmCloseId(null)
                                      }}
                                      disabled={closeBusy}
                                    >
                                      Cancel
                                    </button>
                                  </div>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>

                  {openCount > openLimit && (
                    <button
                      type="button"
                      className="trade-dock-showmore"
                      onClick={() => setShowAllOpen((v) => !v)}
                    >
                      {showAllOpen ? 'Show less' : `Show all (${openCount})`}
                    </button>
                  )}
                </>
              )
            ) : recentCount === 0 ? (
              <div className="trade-dock-empty">No recent trades</div>
            ) : (
              <>
                <div className="recent-trades-list trade-dock-list" aria-label="Recent trades">
                  {displayRecent.map((t, idx) => {
                    const id = t.signal_id || `${t.exit_time || 't'}-${idx}`
                    const isExpanded = expandedId === id
                    const dir: 'long' | 'short' =
                      (t.direction || '').toLowerCase() === 'short' ? 'short' : 'long'
                    const reasonRaw = (t.exit_reason || '').toString()
                    const reason = reasonRaw ? formatExitReason(reasonRaw) : null
                    const dur = computeDurationSeconds(t.entry_time ?? null, t.exit_time ?? null)

                    return (
                      <div key={id} className="recent-trade-wrapper">
                        <div
                          className={`recent-trade ${isExpanded ? 'expanded' : ''}`}
                          onClick={() => toggleExpand(id)}
                        >
                          <div className="trade-left">
                            <span className={`trade-direction-badge ${dir}`}>{dir.toUpperCase()}</span>
                            <div className="trade-info">
                              <span className="trade-time">
                                {(t.symbol || symbol || '—')} • {formatTime(t.exit_time ?? null)}
                              </span>
                              {(t.entry_price != null && t.exit_price != null) && (
                                <span className="trade-prices">
                                  {formatPrice(t.entry_price)} → {formatPrice(t.exit_price)}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="trade-right">
                            <span className={`trade-pnl ${t.pnl === null || t.pnl === undefined ? '' : t.pnl >= 0 ? 'positive' : 'negative'}`}>
                              {formatPnL(t.pnl)}
                            </span>
                            {reason && reason.text && (
                              <span className={`trade-reason-badge reason-${reason.type}`}>
                                {reason.text}
                              </span>
                            )}
                          </div>
                          <span className="trade-expand-icon">{isExpanded ? '▲' : '▼'}</span>
                        </div>

                        {isExpanded && (
                          <div className="trade-details">
                            <div className="trade-detail-row">
                              <span className="trade-detail-label">Symbol</span>
                              <span className="trade-detail-value">{t.symbol || symbol || '—'}</span>
                            </div>
                            <div className="trade-detail-row">
                              <span className="trade-detail-label">Qty</span>
                              <span className="trade-detail-value">{t.position_size ?? '—'}</span>
                            </div>
                            <div className="trade-detail-row">
                              <span className="trade-detail-label">Entry</span>
                              <span className="trade-detail-value">
                                {formatPrice(t.entry_price ?? null)} @ {formatTime(t.entry_time ?? null)}
                              </span>
                            </div>
                            <div className="trade-detail-row">
                              <span className="trade-detail-label">Exit</span>
                              <span className="trade-detail-value">
                                {formatPrice(t.exit_price ?? null)} @ {formatTime(t.exit_time ?? null)}
                              </span>
                            </div>
                            <div className="trade-detail-row">
                              <span className="trade-detail-label">Duration</span>
                              <span className="trade-detail-value">{formatDuration(dur)}</span>
                            </div>
                            <div className="trade-detail-row">
                              <span className="trade-detail-label">P&amp;L</span>
                              <span className={`trade-detail-value ${t.pnl === null || t.pnl === undefined ? '' : t.pnl >= 0 ? 'positive' : 'negative'}`}>
                                {formatPnL(t.pnl)}
                              </span>
                            </div>
                            {reasonRaw && (
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Reason</span>
                                <span className="trade-detail-value">{reasonRaw.replace(/_/g, ' ')}</span>
                              </div>
                            )}
                            {t.signal_id && (
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Signal ID</span>
                                <span className="trade-detail-value">{t.signal_id}</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>

                {recentCount > recentLimit && (
                  <button
                    type="button"
                    className="trade-dock-showmore"
                    onClick={() => setShowAllRecent((v) => !v)}
                  >
                    {showAllRecent ? 'Show less' : `Show all (${recentCount})`}
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      </DataPanel>
    </div>
  )
}

