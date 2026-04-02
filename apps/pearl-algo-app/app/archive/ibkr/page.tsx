'use client'

import { useEffect, useState, useCallback } from 'react'
import Link from 'next/link'
import StatsCards from '@/components/archive/StatsCards'
import DirectionBreakdown from '@/components/archive/DirectionBreakdown'
import ExitReasonBar from '@/components/archive/ExitReasonBar'
import EquityCurve from '@/components/archive/EquityCurve'
import DailyPnLChart from '@/components/archive/DailyPnLChart'
import TradeTable, { type TradeRow } from '@/components/archive/TradeTable'
import TradeDetail from '@/components/archive/TradeDetail'

interface Summary {
  total_trades: number
  wins: number
  total_pnl: number
  win_rate: number
  first_trade: string
  last_trade: string
}

interface DayData {
  day: string
  trades: number
  pnl: number
  wins: number
}

interface EquityPoint {
  time: string
  pnl: number
  cumulative_pnl: number
}

interface DirectionStats {
  trades: number
  wins: number
  total_pnl: number
  avg_pnl: number
  avg_hold: number
  win_rate: number
}

interface ExitReason {
  reason: string
  count: number
}

interface StatsData {
  directions: Record<string, DirectionStats>
  exit_reasons: ExitReason[]
  avg_hold_minutes: number
  expectancy: number
  profit_factor: number
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
  } catch {
    return iso
  }
}

function formatPnL(n: number): string {
  const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return n >= 0 ? `+$${s}` : `-$${s}`
}

export default function ArchiveIbkrPage() {
  const [summary, setSummary] = useState<Summary | null>(null)
  const [daily, setDaily] = useState<DayData[]>([])
  const [equity, setEquity] = useState<EquityPoint[]>([])
  const [trades, setTrades] = useState<TradeRow[]>([])
  const [stats, setStats] = useState<StatsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedTrade, setSelectedTrade] = useState<TradeRow | null>(null)

  useEffect(() => {
    const fetchAll = async () => {
      try {
        const [sRes, dRes, eRes, tRes, stRes] = await Promise.all([
          fetch('/api/archive/ibkr?mode=summary'),
          fetch('/api/archive/ibkr?mode=daily'),
          fetch('/api/archive/ibkr?mode=equity'),
          fetch('/api/archive/ibkr/trades?limit=2000'),
          fetch('/api/archive/ibkr?mode=stats'),
        ])
        if (!sRes.ok) throw new Error('Failed to load archive data')
        const s = await sRes.json()
        if (s.error) throw new Error(s.error)
        setSummary(s)
        setDaily(await dRes.json().then((d: unknown) => (Array.isArray(d) ? d : [])))
        setEquity(await eRes.json().then((d: unknown) => (Array.isArray(d) ? d : [])))
        setTrades(await tRes.json().then((d: unknown) => (Array.isArray(d) ? d : [])))
        const st = await stRes.json()
        if (st && !st.error) setStats(st)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load')
      } finally {
        setLoading(false)
      }
    }
    fetchAll()
  }, [])

  const bestDayData = daily.length
    ? daily.reduce((best, d) => (d.pnl > best.pnl ? d : best), daily[0])
    : null
  const worstDayData = daily.length
    ? daily.reduce((worst, d) => (d.pnl < worst.pnl ? d : worst), daily[0])
    : null
  const tradingDays = daily.length

  const handleTradeClick = useCallback((trade: TradeRow) => {
    setSelectedTrade(trade)
  }, [])

  const handleCloseDetail = useCallback(() => {
    setSelectedTrade(null)
  }, [])

  if (loading) {
    return (
      <main className="archive-page">
        <div className="archive-hero">
          <div className="archive-hero-top">
            <div className="archive-skeleton" style={{ width: 200, height: 32 }} />
            <div className="archive-skeleton" style={{ width: 80, height: 20 }} />
          </div>
          <div className="archive-skeleton" style={{ width: 180, height: 48 }} />
          <div className="archive-skeleton" style={{ width: 260, height: 16 }} />
        </div>
        <div className="archive-stats-grid">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="archive-stat-card">
              <div className="archive-skeleton" style={{ width: 60, height: 10 }} />
              <div className="archive-skeleton" style={{ width: 80, height: 20 }} />
            </div>
          ))}
        </div>
        <div className="archive-skeleton-chart" />
        <div className="archive-skeleton-chart" style={{ height: 180 }} />
      </main>
    )
  }

  if (error) {
    return (
      <main className="archive-page">
        <div className="archive-hero">
          <div className="archive-hero-top">
            <h1>IBKR Virtual</h1>
            <span className="archive-badge">ARCHIVED</span>
          </div>
        </div>
        <div className="archive-error">{error}</div>
        <p className="archive-hint">Ensure the archive data exists at data/archive/ibkr_virtual/</p>
        <Link href="/" className="archive-back-link">Back to Home</Link>
      </main>
    )
  }

  return (
    <main className="archive-page">
      {/* Hero Header */}
      <div className="archive-hero">
        <div className="archive-hero-top">
          <h1>IBKR Virtual</h1>
          <span className="archive-badge">ARCHIVED</span>
        </div>
        {summary && (
          <>
            <span className={`archive-hero-pnl ${summary.total_pnl >= 0 ? 'positive' : 'negative'}`}>
              {formatPnL(summary.total_pnl)}
            </span>
            <p className="archive-hero-subtitle">
              {summary.total_trades.toLocaleString()} trades over {tradingDays} trading days
              <span className="archive-hero-dates">
                {formatDate(summary.first_trade)} — {formatDate(summary.last_trade)}
              </span>
            </p>
          </>
        )}
      </div>

      {/* Stats Grid */}
      {summary && (
        <StatsCards
          totalPnl={summary.total_pnl}
          totalTrades={summary.total_trades}
          winRate={summary.win_rate}
          bestDay={bestDayData?.pnl}
          bestDayDate={bestDayData?.day}
          worstDay={worstDayData?.pnl}
          worstDayDate={worstDayData?.day}
          profitFactor={stats?.profit_factor}
          expectancy={stats?.expectancy}
          avgHoldMinutes={stats?.avg_hold_minutes}
        />
      )}

      {/* Direction Breakdown + Exit Reasons */}
      {stats && (
        <div className="archive-analytics-row">
          <section className="archive-section archive-analytics-panel">
            <h2 className="archive-section-title">Direction Breakdown</h2>
            <DirectionBreakdown directions={stats.directions} />
          </section>
          <section className="archive-section archive-analytics-panel">
            <h2 className="archive-section-title">Exit Reasons</h2>
            <ExitReasonBar reasons={stats.exit_reasons} total={summary?.total_trades ?? 0} />
          </section>
        </div>
      )}

      {/* Charts */}
      <section className="archive-section">
        <h2 className="archive-section-title">Equity Curve</h2>
        <EquityCurve data={equity} height={280} />
      </section>

      <section className="archive-section">
        <h2 className="archive-section-title">Daily P&L</h2>
        <DailyPnLChart data={daily} height={200} />
      </section>

      {/* Trade Table */}
      <section className="archive-section">
        <h2 className="archive-section-title">All Trades</h2>
        <TradeTable trades={trades} onTradeClick={handleTradeClick} />
      </section>

      {/* Trade Detail Slide-Over */}
      {selectedTrade && (
        <TradeDetail trade={selectedTrade} onClose={handleCloseDetail} />
      )}
    </main>
  )
}
