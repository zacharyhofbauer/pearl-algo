'use client'

import React, { useMemo, useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import type { DirectionBreakdown, Position, StatusBreakdown, SignalRejections } from '@/stores'
import { apiFetchJson } from '@/lib/api'
import { useOperatorStore } from '@/stores'
import OperatorUnlockModal from '@/components/OperatorUnlockModal'
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
import type { RiskMetrics, TradovateWorkingOrder, TradovateOrderStats, AnalyticsData } from '@/stores'

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

export interface PerformanceTradeSourceCounts {
  fill_matched: number
  estimated: number
  virtual_ibkr: number
  other: number
}

export interface PerformanceSummary {
  as_of: string
  td: PerformancePeriodSummary
  yday: PerformancePeriodSummary
  wtd: PerformancePeriodSummary
  mtd: PerformancePeriodSummary
  ytd: PerformancePeriodSummary
  all: PerformancePeriodSummary
  pnl_source?: string
  trade_source_counts?: PerformanceTradeSourceCounts
}

export interface RecentSignalEvent {
  signal_id: string
  status: string
  timestamp?: string | null
  direction?: 'long' | 'short' | string | null
  symbol?: string
  entry_price?: number | null
  stop_loss?: number | null
  take_profit?: number | null
  confidence?: number | null
  reason?: string | null
  exit_reason?: string | null
  pnl?: number | null
  signal_type?: string | null
  duplicate?: boolean
}

type CollapsedRecentSignalEvent = RecentSignalEvent & {
  raw_event_count: number
  duplicate_count: number
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
  /** Tradovate working orders (SL, TP) */
  workingOrders?: TradovateWorkingOrder[]
  /** Tradovate order stats (filled, rejected, cancelled counts) */
  orderStats?: TradovateOrderStats | null
  /** Recent signal lifecycle events (generated/entered/exited/etc) */
  recentSignals?: RecentSignalEvent[]
  /** Account equity for panel header */
  accountEquity?: number | null
  /** Account total P&L for panel header */
  accountTotalPnl?: number | null
  /** Account win rate for panel header */
  accountWinRate?: number | null
  /** Tradovate account ID (e.g. "DEMO6315448") */
  accountId?: string | null
  /** Tradovate environment (e.g. "demo" or "live") */
  accountEnv?: string | null
  /** Analytics breakdowns from agentState.analytics (session/hourly/duration) */
  analytics?: AnalyticsData | null
  /** Whether execution is armed (agentState.execution_state.armed). When
   * undefined we don't make a claim. When false, the positions empty-state
   * tells the user signals will not execute. */
  execArmed?: boolean
}

type Tab = 'positions' | 'history' | 'stats' | 'analytics' | 'signals'

/**
 * Analytics tab — surfaces agentState.analytics data computed by the backend.
 *
 * Renders three breakdowns side-by-side:
 *   1. Session performance (overnight / premarket / morning / midday / afternoon / close)
 *   2. Hourly heatmap (best & worst hours by P&L)
 *   3. Hold-duration buckets (quick / medium / long)
 *
 * This is a *display* of historical data, not a *gate* — per CLAUDE.md the user
 * prefers strategy decisions without hour/regime/direction vetoes.
 */
/**
 * Map a backend signal_type / entry_reason to a short badge label and a CSS
 * variant class. Handles common shapes (smc/fvg/vwap/orb/orb-extreme/etc) and
 * falls back to the raw token uppercased.
 */
function strategyBadge(signalType?: string | null): { label: string; variant: string } | null {
  if (!signalType) return null
  const lower = String(signalType).toLowerCase()
  if (lower.includes('smc') || lower.includes('fvg')) return { label: 'SMC', variant: 'cyan' }
  if (lower.includes('vwap')) return { label: 'VWAP', variant: 'yellow' }
  if (lower.includes('orb')) return { label: 'ORB', variant: 'green' }
  if (lower.includes('breakout')) return { label: 'BO', variant: 'cyan' }
  if (lower.includes('pullback')) return { label: 'PB', variant: 'purple' }
  if (lower.includes('reversal')) return { label: 'REV', variant: 'purple' }
  if (lower.includes('ema')) return { label: 'EMA', variant: 'cyan' }
  // Fallback: first 3 letters uppercase
  const token = lower.split(/[\s_-]/)[0] || lower
  return { label: token.slice(0, 4).toUpperCase(), variant: 'neutral' }
}

/**
 * Format an R-multiple value as "+2.3R" / "-0.8R" / "0R".
 */
function formatRMultiple(r?: number | null): string {
  if (r == null || !Number.isFinite(r)) return '—'
  if (r === 0) return '0R'
  const sign = r > 0 ? '+' : ''
  return `${sign}${r.toFixed(1)}R`
}

function AnalyticsTabContent({ analytics }: { analytics?: AnalyticsData | null }) {
  if (!analytics) {
    return <div className="trade-dock-empty">No analytics data yet — waiting for first session.</div>
  }

  const sessions = analytics.session_performance ?? []
  const best = analytics.best_hours ?? []
  const worst = analytics.worst_hours ?? []
  const durations = analytics.hold_duration ?? []

  const hasAny = sessions.length > 0 || best.length > 0 || worst.length > 0 || durations.length > 0
  if (!hasAny) {
    return <div className="trade-dock-empty">Analytics computed but empty — no completed trades in window.</div>
  }

  // Compute heatmap intensity from the absolute max P&L across best+worst.
  const allHours = [...best, ...worst]
  const maxAbsPnl = allHours.reduce((m, h) => Math.max(m, Math.abs(h.pnl ?? 0)), 0) || 1

  return (
    <div className="analytics-tab">
      {sessions.length > 0 && (
        <section className="analytics-section">
          <div className="analytics-section-title">Session Performance</div>
          <div className="analytics-session-grid">
            {sessions.map((s) => {
              const pnlPositive = (s.pnl ?? 0) >= 0
              return (
                <div key={s.id} className="analytics-session-pill">
                  <div className="analytics-session-name">{s.name}</div>
                  <div className={`analytics-session-pnl ${pnlPositive ? 'positive' : 'negative'}`}>
                    {formatPnL(s.pnl)}
                  </div>
                  <div className="analytics-session-meta">
                    {(s.wins ?? 0) + (s.losses ?? 0)} trades · {((s.win_rate ?? 0) * 100).toFixed(0)}%
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}

      {(best.length > 0 || worst.length > 0) && (
        <section className="analytics-section">
          <div className="analytics-section-title">Hour of Day</div>
          <div className="analytics-hour-columns">
            <div className="analytics-hour-col">
              <div className="analytics-subhead positive">Best Hours</div>
              {best.map((h) => {
                const intensity = Math.min(1, Math.abs(h.pnl ?? 0) / maxAbsPnl)
                return (
                  <div
                    key={`b-${h.hour}`}
                    className="analytics-hour-row"
                    style={{ background: `rgba(var(--accent-green-rgb), ${(0.08 + intensity * 0.32).toFixed(2)})` }}
                  >
                    <span className="analytics-hour-label">{h.hour_label}</span>
                    <span className="analytics-hour-pnl positive">{formatPnL(h.pnl)}</span>
                    <span className="analytics-hour-meta">{h.trades}t · {((h.win_rate ?? 0) * 100).toFixed(0)}%</span>
                  </div>
                )
              })}
              {best.length === 0 && <div className="analytics-hour-empty">—</div>}
            </div>
            <div className="analytics-hour-col">
              <div className="analytics-subhead negative">Worst Hours</div>
              {worst.map((h) => {
                const intensity = Math.min(1, Math.abs(h.pnl ?? 0) / maxAbsPnl)
                return (
                  <div
                    key={`w-${h.hour}`}
                    className="analytics-hour-row"
                    style={{ background: `rgba(var(--accent-red-rgb), ${(0.08 + intensity * 0.32).toFixed(2)})` }}
                  >
                    <span className="analytics-hour-label">{h.hour_label}</span>
                    <span className="analytics-hour-pnl negative">{formatPnL(h.pnl)}</span>
                    <span className="analytics-hour-meta">{h.trades}t · {((h.win_rate ?? 0) * 100).toFixed(0)}%</span>
                  </div>
                )
              })}
              {worst.length === 0 && <div className="analytics-hour-empty">—</div>}
            </div>
          </div>
        </section>
      )}

      {durations.length > 0 && (
        <section className="analytics-section">
          <div className="analytics-section-title">Hold Duration</div>
          <div className="analytics-duration-grid">
            {durations.map((d) => {
              const pnlPositive = (d.pnl ?? 0) >= 0
              const total = (d.wins ?? 0) + (d.losses ?? 0)
              return (
                <div key={d.id} className="analytics-duration-pill">
                  <div className="analytics-duration-name">{d.name}</div>
                  <div className={`analytics-duration-pnl ${pnlPositive ? 'positive' : 'negative'}`}>
                    {formatPnL(d.pnl)}
                  </div>
                  <div className="analytics-duration-meta">
                    {total} trades · {((d.win_rate ?? 0) * 100).toFixed(0)}%
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      )}
    </div>
  )
}

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
  workingOrders,
  orderStats,
  recentSignals,
  accountEquity,
  accountTotalPnl,
  accountWinRate,
  accountId,
  accountEnv,
  analytics,
  execArmed,
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

  // Index recent signal events by signal_id so we can enrich both open and
  // closed trade rows with stop_loss / signal_type / take_profit that aren't
  // on the underlying row itself.
  const signalsById = useMemo(() => {
    const map = new Map<string, RecentSignalEvent>()
    for (const s of recentSignals || []) {
      if (s?.signal_id) map.set(s.signal_id, s)
    }
    return map
  }, [recentSignals])

  const openRows = useMemo(() => {
    const fallbackSymbol = symbol || '—'
    return (positions || [])
      .map((p) => {
        const sig = p.signal_id ? signalsById.get(p.signal_id) : undefined
        return {
          ...p,
          symbol: p.symbol || fallbackSymbol,
          // Enrichment from matching signal lifecycle event
          signal_type: sig?.signal_type ?? null,
        }
      })
      .sort((a, b) => {
        const at = a.entry_time ? (new Date(a.entry_time).getTime() || 0) : 0
        const bt = b.entry_time ? (new Date(b.entry_time).getTime() || 0) : 0
        return bt - at
      })
  }, [positions, symbol, signalsById])

  const recentRows = useMemo(() => {
    const fallbackSymbol = symbol || '—'
    return (recentTrades || [])
      .map((t) => {
        const sig = t.signal_id ? signalsById.get(t.signal_id) : undefined
        // R-multiple: realized P&L (USD) divided by per-contract risk (USD).
        // Per-contract risk = |entry − stop| × $/pt × contracts (then we
        // collapse contracts in the denominator so 1 contract @ 2R == 5
        // contracts @ 2R for the multiple).
        let rMultiple: number | null = null
        const entry = t.entry_price ?? sig?.entry_price ?? null
        const stop = sig?.stop_loss ?? null
        const usdPerPt = getUsdPerPoint(t.symbol || sig?.symbol || symbol)
        const size = Number(t.position_size ?? 0)
        if (
          typeof t.pnl === 'number' &&
          entry != null &&
          stop != null &&
          usdPerPt != null &&
          size > 0
        ) {
          const riskPerContract = Math.abs(entry - stop) * usdPerPt
          const totalRisk = riskPerContract * size
          if (totalRisk > 0) rMultiple = t.pnl / totalRisk
        }
        return {
          ...t,
          symbol: t.symbol || fallbackSymbol,
          position_size: t.position_size ?? null,
          // Enrichment
          stop_loss: stop,
          signal_type: sig?.signal_type ?? null,
          r_multiple: rMultiple,
        }
      })
      .sort((a, b) => {
        const at = a.exit_time ? (new Date(a.exit_time).getTime() || 0) : 0
        const bt = b.exit_time ? (new Date(b.exit_time).getTime() || 0) : 0
        return bt - at
      })
  }, [recentTrades, symbol, signalsById])

  const openCount = openRows.length
  const recentCount = recentRows.length

  const headerPosCount = typeof activeTradesCount === 'number' ? activeTradesCount : openCount
  const totalOpenContracts = useMemo(
    () => openRows.reduce((sum, p) => sum + Math.max(0, Number(p.position_size ?? 0)), 0),
    [openRows]
  )

  const fmtMoney = (n: number | null | undefined) => {
    if (n == null) return '\u2014'
    const abs = Math.abs(n)
    return (n >= 0 ? '$' : '-$') + abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  const fmtSignedMoney = (n: number | null | undefined) => {
    if (n == null) return '\u2014'
    const abs = Math.abs(n)
    const formatted = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    return n >= 0 ? `+$${formatted}` : `-$${formatted}`
  }

  // Day shown here for quick scan adjacent to W/L. EquityCurveStrip still holds
  // the authoritative Day Net with sparkline + implied fees. `dailyPnL` is
  // sourced from `agentState.daily_pnl`, which api/server.py sets to
  // `tradovate.realized_pnl` whenever the broker is connected.
  const headerStats = (
    <div className="trade-dock-header-stats" aria-label="Account summary">
      {accountEquity != null && (
        <div className="dock-stat equity">
          <span className="dock-stat-k">Equity</span>
          <span className="dock-stat-v">{fmtMoney(accountEquity)}</span>
        </div>
      )}
      {typeof dailyPnL === 'number' && (
        <div className={`dock-stat pnl ${dailyPnL >= 0 ? 'positive' : 'negative'}`}>
          <span className="dock-stat-k">Day</span>
          <span className="dock-stat-v">{fmtSignedMoney(dailyPnL)}</span>
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
    </div>
  )

  const displayOpen = showAllOpen ? openRows : openRows.slice(0, openLimit)
  const displayRecent = showAllRecent ? recentRows : recentRows.slice(0, recentLimit)
  const displayWorkingOrders = useMemo(() => workingOrders || [], [workingOrders])
  const groupedWorkingOrders = useMemo(() => {
    const groups = new Map<string, TradovateWorkingOrder[]>()
    let fallbackIx = 0
    for (const o of displayWorkingOrders) {
      const id = Number(o.id || 0)
      const oco = Number(o.oco_id || 0)
      const parent = Number(o.parent_id || 0)
      let key = ''
      if (id > 0 && oco > 0) {
        const lo = Math.min(id, oco)
        const hi = Math.max(id, oco)
        key = `oco:${lo}:${hi}`
      } else if (oco > 0) {
        key = `oco:${oco}:${o.contract_id || ''}:${(o.action || '').toLowerCase()}`
      } else if (parent > 0) {
        key = `parent:${parent}:${o.contract_id || ''}:${(o.action || '').toLowerCase()}`
      } else {
        key = `fallback:${o.contract_id || ''}:${(o.action || '').toLowerCase()}:${fallbackIx}`
        fallbackIx += 1
      }
      const bucket = groups.get(key)
      if (bucket) bucket.push(o)
      else groups.set(key, [o])
    }

    return Array.from(groups.values()).map((bucket) => {
      const first = bucket[0]
      const orderType = (first.order_type || '').trim()
      const hasOcoLink = !!(first.oco_id || first.parent_id)
      const displayType = orderType || (hasOcoLink ? 'Protective OCO' : 'Order')
      const qty = bucket.reduce((m, row) => Math.max(m, Number(row.qty || 0)), 0)
      const priced = bucket.find((row) => row.stop_price != null || row.price != null)
      return {
        ...first,
        order_type: displayType,
        qty: qty > 0 ? qty : first.qty,
        stop_price: priced?.stop_price ?? first.stop_price,
        price: priced?.price ?? first.price,
        _row_count: bucket.length,
      }
    })
  }, [displayWorkingOrders])
  const collapsedRecentSignals = useMemo<CollapsedRecentSignalEvent[]>(() => {
    // FIX 2026-04-23 (follow-up #2 / #5): the live signal generator
    // creates a fresh signal_id every 15s bar-close for the SAME logical
    // setup, so per-signal_id dedup isn't enough. /api/signals now
    // content-collapses (direction + entry_price + SL + TP + signal_type)
    // and ships raw_event_count + duplicate_count — prefer those when
    // present. Fall back to per-signal_id collapse for any consumer
    // bypassing the new endpoint.
    const rows = recentSignals || []
    const hasServerCollapse = rows.some((r) => typeof (r as CollapsedRecentSignalEvent).raw_event_count === 'number')
    if (hasServerCollapse) {
      return rows
        .map((r) => {
          const collapsed = r as CollapsedRecentSignalEvent
          return {
            ...collapsed,
            raw_event_count: collapsed.raw_event_count ?? 1,
            duplicate_count: collapsed.duplicate_count ?? 0,
          }
        })
        .sort((a, b) => {
          const at = a.timestamp ? (new Date(a.timestamp).getTime() || 0) : 0
          const bt = b.timestamp ? (new Date(b.timestamp).getTime() || 0) : 0
          return bt - at
        })
    }

    const byId = new Map<string, CollapsedRecentSignalEvent>()
    const orderedEvents = [...rows].sort((a, b) => {
      const at = a.timestamp ? (new Date(a.timestamp).getTime() || 0) : 0
      const bt = b.timestamp ? (new Date(b.timestamp).getTime() || 0) : 0
      return at - bt
    })

    for (const event of orderedEvents) {
      const signalId = event?.signal_id
      if (!signalId) continue

      const existing = byId.get(signalId)
      if (!existing) {
        byId.set(signalId, {
          ...event,
          raw_event_count: 1,
          duplicate_count: 0,
        })
        continue
      }

      byId.set(signalId, {
        ...existing,
        ...event,
        raw_event_count: existing.raw_event_count + 1,
        duplicate_count: existing.duplicate_count + 1,
      })
    }

    return Array.from(byId.values()).sort((a, b) => {
      const at = a.timestamp ? (new Date(a.timestamp).getTime() || 0) : 0
      const bt = b.timestamp ? (new Date(b.timestamp).getTime() || 0) : 0
      return bt - at
    })
  }, [recentSignals])

  const SIGNALS_DEFAULT_LIMIT = 20
  const [showAllSignals, setShowAllSignals] = useState(false)
  const displayRecentSignals = showAllSignals
    ? collapsedRecentSignals
    : collapsedRecentSignals.slice(0, SIGNALS_DEFAULT_LIMIT)
  const hasMoreSignals = collapsedRecentSignals.length > SIGNALS_DEFAULT_LIMIT
  const suppressedSignalEvents = useMemo(
    () => displayRecentSignals.reduce((sum, event) => sum + event.duplicate_count, 0),
    [displayRecentSignals]
  )

  const performanceSourceNote = useMemo(() => {
    const counts = performanceSummary?.trade_source_counts
    if (!counts) return null

    const pluralize = (count: number, singular: string, plural: string) =>
      `${count} ${count === 1 ? singular : plural}`

    if ((counts.estimated ?? 0) > 0) {
      return `Historical stats still include ${pluralize(counts.estimated, 'estimated trade', 'estimated trades')}. Run the fill backfill before trusting totals.`
    }

    if ((counts.virtual_ibkr ?? 0) > 0 && (counts.fill_matched ?? 0) > 0) {
      return `Mixed history: ${pluralize(counts.fill_matched, 'fill-matched trade', 'fill-matched trades')} and ${pluralize(counts.virtual_ibkr, 'virtual IBKR trade', 'virtual IBKR trades')}.`
    }

    if ((counts.virtual_ibkr ?? 0) > 0) {
      return `Stats are based on ${pluralize(counts.virtual_ibkr, 'virtual IBKR trade', 'virtual IBKR trades')}.`
    }

    if ((counts.other ?? 0) > 0) {
      return `Stats include ${pluralize(counts.other, 'trade with unknown provenance', 'trades with unknown provenance')}.`
    }

    return null
  }, [performanceSummary])

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
  const [showUnlockModal, setShowUnlockModal] = useState(false)

  // Gate helper: if locked, show unlock modal; if unlocked, call the action.
  const withOperatorUnlock = (action: () => void) => () => {
    if (!operatorUnlocked) { setShowUnlockModal(true); return }
    action()
  }

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
        title={accountId || 'Tradovate'}
        iconSrc="/tradovate-icon.png"
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
              { id: 'analytics' as Tab, label: 'Analytics' },
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
          </div>

          <div className="trade-dock-content">
            {/* ── Stats Tab ── */}
            {tab === 'stats' && (
              <>
            {performanceSourceNote && (
                  <div className="trade-stats-summary" role="note">
                    <div className="trade-stats-row">
                      <span className="trade-stats-label">Stats Source:</span>
                      <span className="trade-stats-value">{performanceSourceNote}</span>
                    </div>
                  </div>
            )}
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
              <div className="trade-dock-empty">Stats populate after the first closed trade of the session.</div>
            )}
              </>
            )}

            {/* ── Analytics Tab ── */}
            {tab === 'analytics' && (
              <AnalyticsTabContent analytics={analytics} />
            )}

            {/* ── Signals Tab ── */}
            {tab === 'signals' && (
              <div className="signals-tab-content">
                {displayRecentSignals.length > 0 && (
                  <div className="signals-section">
                    <div className="signals-section-title">Recent Signal Activity</div>
                    {suppressedSignalEvents > 0 && (
                      <div className="trade-stats-summary" role="note">
                        <div className="trade-stats-row">
                          <span className="trade-stats-label">Display:</span>
                          <span className="trade-stats-value">
                            Collapsed {suppressedSignalEvents} duplicate event{suppressedSignalEvents === 1 ? '' : 's'}; latest status shown per signal.
                          </span>
                        </div>
                      </div>
                    )}
                    <div className="recent-trades-list trade-dock-list" aria-label="Recent signal activity">
                      {displayRecentSignals.map((s, idx) => {
                        const id = s.signal_id || `signal-${idx}`
                        const status = String(s.status || 'unknown').toUpperCase()
                        const direction = String(s.direction || '').toUpperCase()
                        const reason = (s.reason || s.exit_reason || '').toString()
                        const hasPnl = typeof s.pnl === 'number'
                        return (
                          <div key={`${id}-${idx}`} className="recent-trade">
                            <div className="trade-left">
                              <span className={`trade-direction-badge ${String(s.direction || '').toLowerCase() === 'short' ? 'short' : 'long'}`}>
                                {direction || '—'}
                              </span>
                              <div className="trade-info">
                                <span className="trade-time">
                                  {(s.symbol || symbol || '—')} • {status} • {formatRelativeTime(s.timestamp || null)}
                                </span>
                                <span className="trade-prices">
                                  {formatPrice(s.entry_price ?? null)}
                                  {s.stop_loss != null || s.take_profit != null ? ` | SL ${formatPrice(s.stop_loss ?? null)} | TP ${formatPrice(s.take_profit ?? null)}` : ''}
                                </span>
                                {reason ? (
                                  <span className="trade-time">
                                    {reason.length > 120 ? `${reason.slice(0, 120)}...` : reason}
                                  </span>
                                ) : null}
                                {s.raw_event_count > 1 ? (
                                  <span className="trade-time">
                                    Fired {s.raw_event_count} times; showing latest status.
                                  </span>
                                ) : null}
                              </div>
                            </div>
                            <div className="trade-right">
                              {s.raw_event_count > 1 ? (
                                <span
                                  className="trade-r-chip"
                                  title={`This setup fired ${s.raw_event_count} times; ${s.duplicate_count} re-fires collapsed.`}
                                >
                                  {s.raw_event_count}×
                                </span>
                              ) : null}
                              {hasPnl ? (
                                <span className={`trade-pnl ${(s.pnl as number) >= 0 ? 'positive' : 'negative'}`}>
                                  {formatPnL(s.pnl)}
                                </span>
                              ) : (
                                <span className="trade-pnl">—</span>
                              )}
                            </div>
                          </div>
                        )
                      })}
                    </div>
                    {hasMoreSignals && (
                      <button
                        type="button"
                        className="trade-dock-showmore"
                        onClick={() => setShowAllSignals((v) => !v)}
                      >
                        {showAllSignals
                          ? 'Show less'
                          : `Show all (${collapsedRecentSignals.length})`}
                      </button>
                    )}
                  </div>
                )}

                {signalRejections && (
                  <div className="signals-section">
                    <div className="signals-section-title">Signal Rejections (24h)</div>
                    {([
                      ['Direction Gating', signalRejections.direction_gating],
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

                {!signalRejections && displayRecentSignals.length === 0 && (
                  <div className="trade-dock-empty">No signal activity yet — strategy is scanning each bar close.</div>
                )}
              </div>
            )}

            {/* ── Positions Tab ── */}
            {tab === 'positions' ? (
              openCount === 0 && displayWorkingOrders.length === 0 ? (
                <div className="trade-dock-empty">
                  {execArmed === false
                    ? 'No open positions — execution disarmed, signals will not place orders.'
                    : execArmed === true
                      ? 'No open positions — system armed and watching the tape.'
                      : 'No open positions.'}
                </div>
              ) : openCount === 0 ? (
                <>
                  <div className="trade-dock-empty">
                    {execArmed === false
                      ? 'No open positions — execution disarmed, signals will not place orders.'
                      : 'No open positions — system armed and watching the tape.'}
                  </div>
                  {groupedWorkingOrders.length > 0 && (
                    <div className="trade-dock-working-orders">
                      <div className="trade-dock-section-label">Working Orders ({groupedWorkingOrders.length})</div>
                      {groupedWorkingOrders.map((o, i) => (
                        <div key={o.id ?? i} className="working-order-row">
                          <span className={`working-order-type ${(o.order_type || '').toLowerCase().replace(/\s/g, '-')}`}>
                            {o.order_type || 'Order'}{(o as unknown as { _row_count?: number })._row_count && (o as unknown as { _row_count?: number })._row_count! > 1 ? ` x${(o as unknown as { _row_count?: number })._row_count}` : ''}
                          </span>
                          <span className={`working-order-side ${(o.action || '').toLowerCase()}`}>
                            {o.action || '—'}
                          </span>
                          <span className="working-order-qty">{o.qty ?? '—'}</span>
                          <span className="working-order-price">
                            {o.stop_price ? formatPrice(o.stop_price) : o.price ? formatPrice(o.price) : (o.oco_id || o.parent_id) ? 'Broker working' : '—'}
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
                          onClick={withOperatorUnlock(() => {
                            setConfirmCloseAll(true)
                            setConfirmCloseId(null)
                            setCloseResult(null)
                          })}
                          disabled={closeBusy}
                          title={!operatorUnlocked ? 'Click to unlock' : undefined}
                        >
                          {!operatorUnlocked ? '🔒 Close All' : 'Close All'}
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
                  {openCount > 0 && displayWorkingOrders.length === 0 && openRows.every(p => !p.stop_loss && !p.take_profit) && (
                    <div className="trade-controls-result error">
                      Open position has no visible working protective orders (SL/TP). Verify protection in Tradovate.
                    </div>
                  )}

                  <div className="recent-trades-list trade-dock-list" aria-label="Open positions">
                    {displayOpen.map((p) => {
                      const id = p.signal_id
                      const isExpanded = expandedId === id
                      const uUsd = computeUnrealizedUsd(p)
                      const strat = strategyBadge(p.signal_type)
                      const ageSec = computeDurationSeconds(p.entry_time ?? null, new Date().toISOString())
                      const usdPerPt = getUsdPerPoint(p.symbol || symbol)
                      // Distance to stop / target in $ (per total position)
                      let stopDistUsd: number | null = null
                      let tpDistUsd: number | null = null
                      let plannedR: number | null = null
                      if (
                        usdPerPt != null &&
                        p.position_size != null &&
                        p.position_size > 0
                      ) {
                        if (p.stop_loss != null) {
                          stopDistUsd =
                            Math.abs(p.entry_price - p.stop_loss) * usdPerPt * p.position_size
                        }
                        if (p.take_profit != null) {
                          tpDistUsd =
                            Math.abs(p.take_profit - p.entry_price) * usdPerPt * p.position_size
                        }
                        if (stopDistUsd != null && stopDistUsd > 0 && tpDistUsd != null) {
                          plannedR = tpDistUsd / stopDistUsd
                        }
                      }

                      const tooltip = [
                        p.signal_type ? `Strategy: ${p.signal_type}` : null,
                        ageSec != null && ageSec > 0 ? `In trade: ${formatDuration(ageSec)}` : null,
                        plannedR != null ? `Planned R:R: 1:${plannedR.toFixed(1)}` : null,
                        stopDistUsd != null ? `Risk to stop: $${stopDistUsd.toFixed(0)}` : null,
                        tpDistUsd != null ? `Reward to target: $${tpDistUsd.toFixed(0)}` : null,
                      ]
                        .filter(Boolean)
                        .join('\n')

                      return (
                        <div key={id} className="recent-trade-wrapper">
                          <div
                            className={`recent-trade ${isExpanded ? 'expanded' : ''}`}
                            onClick={() => toggleExpand(id)}
                            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleExpand(id) } }}
                            role="button"
                            tabIndex={0}
                            aria-expanded={isExpanded}
                            aria-label={`${p.direction.toUpperCase()} ${p.symbol || symbol || ''} opened at ${formatPrice(p.entry_price)}, unrealized ${uUsd === null ? 'unknown' : `$${Math.abs(uUsd).toFixed(2)}`}${ageSec ? `, in trade ${formatDuration(ageSec)}` : ''}`}
                            title={tooltip || undefined}
                          >
                            <div className="trade-left">
                              <span className={`trade-direction-badge ${p.direction}`}>
                                {p.direction.toUpperCase()}
                              </span>
                              {strat && (
                                <span
                                  className={`trade-strategy-badge strategy-${strat.variant}`}
                                  title={p.signal_type ?? ''}
                                >
                                  {strat.label}
                                </span>
                              )}
                              <div className="trade-info">
                                <span className="trade-time">
                                  {(p.symbol || symbol || '—')} • Opened {formatTime(p.entry_time || null)}
                                  {ageSec != null && ageSec > 0 ? ` • ${formatDuration(ageSec)}` : ''}
                                </span>
                                <span className="trade-prices">
                                  {formatPrice(p.entry_price)} → {formatPrice(currentPrice ?? null)}
                                </span>
                              </div>
                            </div>
                            <div className="trade-right">
                              {plannedR != null && (
                                <span
                                  className="trade-r-chip planned"
                                  title="Planned reward-to-risk ratio (target / stop distance)"
                                >
                                  1:{plannedR.toFixed(1)}
                                </span>
                              )}
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
                                      if (!operatorUnlocked) { setShowUnlockModal(true); return }
                                      setConfirmCloseId(id)
                                      setConfirmCloseAll(false)
                                      setCloseResult(null)
                                    }}
                                    disabled={closeBusy}
                                    title={!operatorUnlocked ? 'Click to unlock' : undefined}
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
                  {groupedWorkingOrders.length > 0 && (
                    <div className="trade-dock-working-orders">
                      <div className="trade-dock-section-label">Working Orders ({groupedWorkingOrders.length})</div>
                      {groupedWorkingOrders.map((o, i) => (
                        <div key={o.id ?? i} className="working-order-row">
                          <span className={`working-order-type ${(o.order_type || '').toLowerCase().replace(/\s/g, '-')}`}>
                            {o.order_type || 'Order'}{(o as unknown as { _row_count?: number })._row_count && (o as unknown as { _row_count?: number })._row_count! > 1 ? ` x${(o as unknown as { _row_count?: number })._row_count}` : ''}
                          </span>
                          <span className={`working-order-side ${(o.action || '').toLowerCase()}`}>
                            {o.action || '—'}
                          </span>
                          <span className="working-order-qty">{o.qty ?? '—'}</span>
                          <span className="working-order-price">
                            {o.stop_price ? formatPrice(o.stop_price) : o.price ? formatPrice(o.price) : (o.oco_id || o.parent_id) ? 'Broker working' : '—'}
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
              <div className="trade-dock-empty">No closed trades yet today — come back after the first exit.</div>
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
                    const strat = strategyBadge(t.signal_type)
                    const rText = formatRMultiple(t.r_multiple)
                    const rPositive = (t.r_multiple ?? 0) >= 0

                    return (
                      <div key={id} className="recent-trade-wrapper">
                        <div
                          className={`recent-trade ${isExpanded ? 'expanded' : ''}`}
                          onClick={() => toggleExpand(id)}
                          onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleExpand(id) } }}
                          role="button"
                          tabIndex={0}
                          aria-expanded={isExpanded}
                          aria-label={`${dir.toUpperCase()} ${t.symbol || symbol || ''} exited at ${formatTime(t.exit_time ?? null)}, P&L ${formatPnL(t.pnl)}${t.r_multiple != null ? `, ${rText}` : ''}`}
                        >
                          <div className="trade-left">
                            <span className={`trade-direction-badge ${dir}`}>{dir.toUpperCase()}</span>
                            {strat && (
                              <span
                                className={`trade-strategy-badge strategy-${strat.variant}`}
                                title={t.signal_type ?? ''}
                              >
                                {strat.label}
                              </span>
                            )}
                            <div className="trade-info">
                              <span className="trade-time">
                                {(t.symbol || symbol || '—')} • {formatTime(t.exit_time ?? null)}
                                {dur != null && dur > 0 ? ` • ${formatDuration(dur)}` : ''}
                              </span>
                              {(t.entry_price != null && t.exit_price != null) && (
                                <span className="trade-prices">
                                  {formatPrice(t.entry_price)} → {formatPrice(t.exit_price)}
                                </span>
                              )}
                            </div>
                          </div>
                          <div className="trade-right">
                            {t.r_multiple != null && (
                              <span
                                className={`trade-r-chip ${rPositive ? 'positive' : 'negative'}`}
                                title="Realized P&L divided by initial risk (|entry−stop| × $/pt × contracts)"
                              >
                                {rText}
                              </span>
                            )}
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
                            {t.signal_type && (
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Strategy</span>
                                <span className="trade-detail-value">{t.signal_type}</span>
                              </div>
                            )}
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
                            {t.stop_loss != null && (
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">Stop</span>
                                <span className="trade-detail-value">{formatPrice(t.stop_loss)}</span>
                              </div>
                            )}
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
                            {t.r_multiple != null && (
                              <div className="trade-detail-row">
                                <span className="trade-detail-label">R-Multiple</span>
                                <span className={`trade-detail-value ${rPositive ? 'positive' : 'negative'}`}>
                                  {rText}
                                </span>
                              </div>
                            )}
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
