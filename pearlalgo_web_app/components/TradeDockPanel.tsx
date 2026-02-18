'use client'

import React, { useMemo, useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import type { DirectionBreakdown, Position, StatusBreakdown, SignalRejections, LastSignalDecision } from '@/stores'
import { apiFetchJson } from '@/lib/api'
import { useOperatorStore } from '@/stores'
import {
  getUsdPerPoint,
  formatPrice,
  formatTime,
  formatSigned,
  formatRelativeTime,
  formatPnL,
  formatDuration,
  formatExitReason,
  computeDurationSeconds,
} from '@/lib/formatters'
import type { RiskMetrics, TradovateWorkingOrder, TradovateOrderStats } from '@/stores'

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
  tradovate_equity?: number
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
  /** Called after a close action succeeds to trigger an immediate data refetch */
  onRefresh?: () => void
  /** Risk metrics from agent state (Sharpe, Sortino, drawdown, streaks, etc.) */
  riskMetrics?: RiskMetrics | null
  /** Signal rejections in last 24h */
  signalRejections?: SignalRejections | null
  /** Last signal decision made by the agent */
  lastSignalDecision?: LastSignalDecision | null
  /** Tradovate working orders (SL, TP) */
  workingOrders?: TradovateWorkingOrder[]
  /** Tradovate order stats (filled, rejected, cancelled counts) */
  orderStats?: TradovateOrderStats | null
}

type Tab = 'positions' | 'history' | 'stats' | 'signals'

function TradeDockPanel({
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
  onRefresh,
  riskMetrics,
  signalRejections,
  lastSignalDecision,
  workingOrders,
  orderStats,
}: TradeDockPanelProps) {
  const [tab, setTab] = useState<Tab>('positions')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [showSummary, setShowSummary] = useState(true)
  const [showPerf, setShowPerf] = useState(true)
  const [showAllOpen, setShowAllOpen] = useState(false)
  const [showAllRecent, setShowAllRecent] = useState(false)
  const [confirmCloseAll, setConfirmCloseAll] = useState(false)
  const [confirmCloseId, setConfirmCloseId] = useState<string | null>(null)
  const [closeBusy, setCloseBusy] = useState(false)
  const [closeResult, setCloseResult] = useState<{ type: 'ok' | 'error'; message: string } | null>(null)
  const [showRiskMetrics, setShowRiskMetrics] = useState(true)

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
        <span className="dock-stat-k">POS</span>
        <span className="dock-stat-v">{headerPosCount}</span>
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
      const data = await apiFetchJson<{ message?: string }>('/api/close-all-trades', { method: 'POST' })
      setCloseResult({ type: 'ok', message: data?.message || 'Close-all requested.' })
      setConfirmCloseAll(false)
      setConfirmCloseId(null)
      // Trigger immediate refetch so positions list updates
      onRefresh?.()
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Close-all failed'
      setCloseResult({ type: 'error', message })
    } finally {
      setCloseBusy(false)
    }
  }

  const requestCloseTrade = async (signalId: string) => {
    if (closeBusy) return
    setCloseBusy(true)
    setCloseResult(null)
    try {
      const data = await apiFetchJson<{ message?: string }>('/api/close-trade', {
        method: 'POST',
        body: JSON.stringify({ signal_id: signalId }),
      })
      setCloseResult({ type: 'ok', message: data?.message || 'Close requested.' })
      setConfirmCloseId(null)
      // Trigger immediate refetch so the closed trade updates
      onRefresh?.()
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Close failed'
      setCloseResult({ type: 'error', message })
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
            {([
              { id: 'positions' as Tab, label: 'Positions', count: openCount },
              { id: 'history' as Tab, label: 'History', count: recentCount },
              { id: 'stats' as Tab, label: 'Stats' },
              { id: 'signals' as Tab, label: 'Signals' },
            ]).map(({ id, label, count }) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={tab === id}
                className={`trade-dock-tab ${tab === id ? 'active' : ''}`}
                onClick={() => { setTab(id); setExpandedId(null) }}
              >
                {label}{count !== undefined ? <span className="trade-dock-count">{count}</span> : null}
              </button>
            ))}

            <div className="trade-dock-spacer" />

            {currentPrice !== undefined && currentPrice !== null && (
              <div className="trade-dock-last">
                <span className="trade-dock-last-label">Last</span>
                <span className="trade-dock-last-value">{formatPrice(currentPrice)}</span>
              </div>
            )}
          </div>

          <div className="trade-dock-content">
            {/* ── Stats Tab ── */}
            {tab === 'stats' && (
              <>
            {performanceSummary && (
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
                          {p.trades} trades &bull; {p.win_rate.toFixed(0)}%
                        </div>
                      </div>
                    ))}
                  </div>
            )}

            {riskMetrics && (
              <div className="trade-stats-summary-wrapper">
                <button
                  className="trade-stats-summary-toggle"
                  onClick={() => setShowRiskMetrics(!showRiskMetrics)}
                  type="button"
                  aria-expanded={showRiskMetrics}
                >
                  <span className="trade-stats-summary-label">Risk Metrics</span>
                  <span className="trade-stats-summary-icon" aria-hidden="true">{showRiskMetrics ? '▲' : '▼'}</span>
                </button>

                {showRiskMetrics && (
                  <div className="trade-stats-summary" style={{ fontSize: '0.78rem' }}>
                    {/* Row 1: Ratios */}
                    <div className="trade-stats-row">
                      <span className="trade-stats-label">Sharpe:</span>
                      <span className="trade-stats-value">{riskMetrics.sharpe_ratio != null ? riskMetrics.sharpe_ratio : '—'}</span>
                      <span className="trade-stats-label" style={{ marginLeft: 8 }}>Sortino:</span>
                      <span className="trade-stats-value">{riskMetrics.sortino_ratio != null ? riskMetrics.sortino_ratio : '—'}</span>
                    </div>
                    <div className="trade-stats-row">
                      <span className="trade-stats-label">Profit Factor:</span>
                      <span className="trade-stats-value">{riskMetrics.profit_factor != null ? riskMetrics.profit_factor : '—'}</span>
                      <span className="trade-stats-label" style={{ marginLeft: 8 }}>Expectancy:</span>
                      <span className={`trade-stats-value ${(riskMetrics.expectancy || 0) >= 0 ? 'positive' : 'negative'}`}>
                        {riskMetrics.expectancy != null ? `$${riskMetrics.expectancy}` : '—'}
                      </span>
                    </div>
                    {/* Row 2: Trade quality */}
                    <div className="trade-stats-row">
                      <span className="trade-stats-label">Avg Win:</span>
                      <span className="trade-stats-value positive">{riskMetrics.avg_win != null ? `$${riskMetrics.avg_win}` : '—'}</span>
                      <span className="trade-stats-label" style={{ marginLeft: 8 }}>Avg Loss:</span>
                      <span className="trade-stats-value negative">{riskMetrics.avg_loss != null ? `$${riskMetrics.avg_loss}` : '—'}</span>
                    </div>
                    <div className="trade-stats-row">
                      <span className="trade-stats-label">Avg R:R:</span>
                      <span className="trade-stats-value">{riskMetrics.avg_rr != null ? riskMetrics.avg_rr : '—'}</span>
                      <span className="trade-stats-label" style={{ marginLeft: 8 }}>Best:</span>
                      <span className="trade-stats-value positive">{riskMetrics.largest_win != null ? `$${riskMetrics.largest_win}` : '—'}</span>
                      <span className="trade-stats-label" style={{ marginLeft: 8 }}>Worst:</span>
                      <span className="trade-stats-value negative">{riskMetrics.largest_loss != null ? `$${riskMetrics.largest_loss}` : '—'}</span>
                    </div>
                    {/* Row 3: Drawdown */}
                    <div className="trade-stats-row">
                      <span className="trade-stats-label">Max DD:</span>
                      <span className="trade-stats-value negative">${riskMetrics.max_drawdown ?? 0}</span>
                      <span className="trade-stats-label" style={{ marginLeft: 8 }}>DD %:</span>
                      <span className="trade-stats-value">{riskMetrics.max_drawdown_pct ?? 0}%</span>
                    </div>
                    {/* Row 4: Streaks */}
                    <div className="trade-stats-row">
                      <span className="trade-stats-label">Streak:</span>
                      <span className={`trade-stats-value ${(riskMetrics.current_streak || 0) >= 0 ? 'positive' : 'negative'}`}>
                        {riskMetrics.current_streak ?? 0}
                      </span>
                      <span className="trade-stats-label" style={{ marginLeft: 8 }}>Max W:</span>
                      <span className="trade-stats-value positive">{riskMetrics.max_consecutive_wins ?? 0}</span>
                      <span className="trade-stats-label" style={{ marginLeft: 8 }}>Max L:</span>
                      <span className="trade-stats-value negative">{riskMetrics.max_consecutive_losses ?? 0}</span>
                    </div>
                    {/* Freshness indicator */}
                    {performanceSummary?.as_of && (
                      <div className="trade-stats-row" style={{ opacity: 0.5 }}>
                        <span className="trade-stats-label">Data:</span>
                        <span className="trade-stats-value">{formatRelativeTime(performanceSummary.as_of)}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {hasSummaryData && (
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

            {!performanceSummary && !riskMetrics && !hasSummaryData && (
              <div className="trade-dock-empty">No stats data available</div>
            )}
              </>
            )}

            {/* ── Signals Tab ── */}
            {tab === 'signals' && (
              <div className="signals-tab-content">
                {signalRejections && (
                  <div className="signals-section">
                    <div className="signals-section-title">Signal Rejections (24h)</div>
                    {([
                      ['Direction Gating', signalRejections.direction_gating],
                      ['ML Filter', signalRejections.ml_filter],
                      ['Circuit Breaker', signalRejections.circuit_breaker],
                      ['Session Filter', signalRejections.session_filter],
                      ['Max Positions', signalRejections.max_positions],
                    ] as Array<[string, number]>).map(([label, count]) => (
                      <div key={label} className="signals-row">
                        <span className="signals-label">{label}</span>
                        <span className={`signals-value ${count > 0 ? 'negative' : ''}`}>{count}</span>
                      </div>
                    ))}
                  </div>
                )}

                {lastSignalDecision && (
                  <div className="signals-section">
                    <div className="signals-section-title">Last Signal Decision</div>
                    <div className="signals-row">
                      <span className="signals-label">Action</span>
                      <span className={`signals-value ${lastSignalDecision.action === 'execute' ? 'positive' : 'negative'}`}>
                        {lastSignalDecision.action === 'execute' ? 'EXECUTED' : 'SKIPPED'}
                      </span>
                    </div>
                    <div className="signals-row">
                      <span className="signals-label">Type</span>
                      <span className="signals-value">{lastSignalDecision.signal_type}</span>
                    </div>
                    <div className="signals-row">
                      <span className="signals-label">ML Prob</span>
                      <span className="signals-value">{(lastSignalDecision.ml_probability * 100).toFixed(1)}%</span>
                    </div>
                    <div className="signals-row">
                      <span className="signals-label">Reason</span>
                      <span className="signals-value">{lastSignalDecision.reason}</span>
                    </div>
                    {lastSignalDecision.timestamp && (
                      <div className="signals-row">
                        <span className="signals-label">Time</span>
                        <span className="signals-value">{formatRelativeTime(lastSignalDecision.timestamp)}</span>
                      </div>
                    )}
                  </div>
                )}

                {!signalRejections && !lastSignalDecision && (
                  <div className="trade-dock-empty">No signal data available</div>
                )}
              </div>
            )}

            {/* ── Positions Tab ── */}
            {tab === 'positions' ? (
              openCount === 0 && (!workingOrders || workingOrders.length === 0) ? (
                <div className="trade-dock-empty">No open positions</div>
              ) : openCount === 0 ? (
                <>
                  <div className="trade-dock-empty">No open positions</div>
                  {workingOrders && workingOrders.length > 0 && (
                    <div className="trade-dock-working-orders">
                      <div className="trade-dock-section-label">Working Orders</div>
                      {workingOrders.map((o, i) => (
                        <div key={o.id ?? i} className="working-order-row">
                          <span className={`working-order-type ${(o.order_type || '').toLowerCase().replace(/\s/g, '-')}`}>
                            {o.order_type || 'Order'}
                          </span>
                          <span className={`working-order-side ${(o.action || '').toLowerCase()}`}>
                            {o.action || '—'}
                          </span>
                          <span className="working-order-qty">{o.qty ?? '—'}</span>
                          <span className="working-order-price">
                            {o.stop_price ? formatPrice(o.stop_price) : o.price ? formatPrice(o.price) : '—'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
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
                            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleExpand(id) } }}
                            role="button"
                            tabIndex={0}
                            aria-expanded={isExpanded}
                            aria-label={`${p.direction.toUpperCase()} ${p.symbol || symbol || ''} opened at ${formatPrice(p.entry_price)}, unrealized ${uUsd === null ? 'unknown' : `$${Math.abs(uUsd).toFixed(2)}`}`}
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
                            <span className="trade-expand-icon" aria-hidden="true">{isExpanded ? '▲' : '▼'}</span>
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

                  {/* Working Orders (SL/TP from Tradovate) */}
                  {workingOrders && workingOrders.length > 0 && (
                    <div className="trade-dock-working-orders">
                      <div className="trade-dock-section-label">Working Orders</div>
                      {workingOrders.map((o, i) => (
                        <div key={o.id ?? i} className="working-order-row">
                          <span className={`working-order-type ${(o.order_type || '').toLowerCase().replace(/\s/g, '-')}`}>
                            {o.order_type || 'Order'}
                          </span>
                          <span className={`working-order-side ${(o.action || '').toLowerCase()}`}>
                            {o.action || '—'}
                          </span>
                          <span className="working-order-qty">{o.qty ?? '—'}</span>
                          <span className="working-order-price">
                            {o.stop_price ? formatPrice(o.stop_price) : o.price ? formatPrice(o.price) : '—'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              )
            ) : null}

            {/* Order Stats (filled/rejected/cancelled) */}
            {tab === 'positions' && orderStats && (orderStats.rejected > 0 || orderStats.cancelled > 0 || orderStats.filled > 0) && (
              <div className="trade-dock-order-stats">
                {orderStats.filled > 0 && (
                  <span className="order-stat-pill filled">Filled {orderStats.filled}</span>
                )}
                {orderStats.cancelled > 0 && (
                  <span className="order-stat-pill cancelled">Cancelled {orderStats.cancelled}</span>
                )}
                {orderStats.rejected > 0 && (
                  <span className="order-stat-pill rejected">Rejected {orderStats.rejected}</span>
                )}
              </div>
            )}

            {/* ── History Tab ── */}
            {tab === 'history' && (recentCount === 0 ? (
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
                          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleExpand(id) } }}
                          role="button"
                          tabIndex={0}
                          aria-expanded={isExpanded}
                          aria-label={`${dir.toUpperCase()} ${t.symbol || symbol || ''} exited at ${formatTime(t.exit_time ?? null)}, P&L ${formatPnL(t.pnl)}`}
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
                          <span className="trade-expand-icon" aria-hidden="true">{isExpanded ? '▲' : '▼'}</span>
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
            ))}
          </div>
        </div>
      </DataPanel>
    </div>
  )
}

export default React.memo(TradeDockPanel)