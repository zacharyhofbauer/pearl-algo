'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useCountUp } from '@/hooks/useCountUp'
import Sparkline from '@/components/Sparkline'

/** Recent exit/trade from /api/state recent_exits */
interface RecentExitItem {
  direction: string
  pnl: number
  exit_time: string
}

/** Tradovate challenge stats from /api/state */
interface TvStats {
  evalNumber: number
  balance: number
  equityCurve?: { time: number; value: number }[]
  recentExits?: RecentExitItem[]
}

/** IBKR archive summary from /api/archive/ibkr?mode=summary */
interface IbkrSummary {
  total_trades: number
  total_pnl: number
  days?: number
}

/** IBKR daily P&L from /api/archive/ibkr?mode=daily */
interface IbkrDailyItem {
  day: string
  pnl: number
  trades: number
  wins: number
}

function formatBalance(n: number): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(n)
}

function formatPnL(n: number): string {
  const s = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(n)
  return n >= 0 ? s : s
}

function timeAgo(iso: string): string {
  try {
    const d = new Date(iso)
    const s = Math.floor((Date.now() - d.getTime()) / 1000)
    if (s < 60) return 'just now'
    if (s < 3600) return `${Math.floor(s / 60)}m ago`
    if (s < 86400) return `${Math.floor(s / 3600)}h ago`
    return `${Math.floor(s / 86400)}d ago`
  } catch {
    return ''
  }
}

function getTvApiBase(): string {
  if (typeof window === 'undefined') return ''
  const isLocal = ['localhost', '127.0.0.1'].includes(window.location.hostname)
  return isLocal ? 'http://localhost:8001' : '/tv_paper'
}

/**
 * Landing page - Mission Control portfolio overview.
 * Links to /dashboard (Tradovate Paper live) and /archive/ibkr (IBKR Virtual historical).
 */
export default function LandingPage() {
  const [tvStats, setTvStats] = useState<TvStats | null>(null)
  const [ibkrStats, setIbkrStats] = useState<IbkrSummary | null>(null)
  const [ibkrDaily, setIbkrDaily] = useState<IbkrDailyItem[]>([])
  const [tvLoading, setTvLoading] = useState(true)
  const [ibkrLoading, setIbkrLoading] = useState(true)

  useEffect(() => {
    const base = getTvApiBase()
    fetch(`${base}/api/state`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error('Not ok'))))
      .then((data) => {
        const ch = data?.challenge
        if (ch && typeof ch.current_balance === 'number') {
          const curve = data?.equity_curve
          const ec = Array.isArray(curve) ? curve : []
          const exits = data?.recent_exits
          const re = Array.isArray(exits)
            ? exits.slice(0, 20).map((e: { direction?: string; pnl?: number; exit_time?: string }) => ({
                direction: e?.direction ?? 'long',
                pnl: e?.pnl ?? 0,
                exit_time: e?.exit_time ?? '',
              }))
            : []
          setTvStats({
            evalNumber: ch.attempt_number ?? 1,
            balance: ch.current_balance,
            equityCurve: ec.map((p: { time?: number; value?: number }) => ({ time: p?.time ?? 0, value: p?.value ?? 0 })),
            recentExits: re,
          })
        }
      })
      .catch(() => {})
      .finally(() => setTvLoading(false))
  }, [])

  useEffect(() => {
    Promise.all([
      fetch('/api/archive/ibkr?mode=summary').then((r) => (r.ok ? r.json() : Promise.reject(new Error('Not ok')))),
      fetch('/api/archive/ibkr?mode=daily').then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([data, daily]) => {
        if (data && typeof data.total_trades === 'number') {
          let days: number | undefined
          if (data.first_trade && data.last_trade) {
            const a = new Date(data.first_trade).getTime()
            const b = new Date(data.last_trade).getTime()
            days = Math.max(1, Math.ceil((b - a) / (24 * 60 * 60 * 1000)))
          }
          setIbkrStats({
            total_trades: data.total_trades,
            total_pnl: data.total_pnl ?? 0,
            days,
          })
        }
        setIbkrDaily(Array.isArray(daily) ? daily : [])
      })
      .catch(() => {})
      .finally(() => setIbkrLoading(false))
  }, [])

  const tvEval = tvStats ? `EVAL #${tvStats.evalNumber}` : 'EVAL #1'
  const tvBalanceVal = useCountUp(tvStats?.balance ?? null, { enabled: !tvLoading && tvStats != null })
  const tvBalance = tvStats ? `${formatBalance(tvBalanceVal)} balance` : '50K balance'
  const ibkrTradesVal = useCountUp(ibkrStats?.total_trades ?? null, { enabled: !ibkrLoading && ibkrStats != null })
  const ibkrTrades = ibkrStats ? `${formatBalance(ibkrTradesVal)} trades` : '1,573 trades'
  const ibkrPnLVal = useCountUp(ibkrStats?.total_pnl ?? null, { enabled: !ibkrLoading && ibkrStats != null })
  const ibkrPnL = ibkrStats ? `${formatPnL(ibkrPnLVal)} P&L` : '$23,248 P&L'
  const ibkrDaysVal = useCountUp(ibkrStats?.days ?? null, { enabled: !ibkrLoading && ibkrStats != null })
  const ibkrDays = ibkrStats?.days != null ? `${Math.round(ibkrDaysVal)} days` : '15 days'
  const loading = tvLoading || ibkrLoading

  return (
    <main className="landing-page">
      {tvStats?.recentExits && tvStats.recentExits.length > 0 && (
        <div className="landing-ticker-wrap" aria-label="Recent trades">
          <div className="landing-ticker-track">
            {[...tvStats.recentExits, ...tvStats.recentExits].map((t, i) => (
              <span key={i} className="landing-ticker-pill">
                <span className={`landing-ticker-dir ${t.direction}`}>{t.direction.toUpperCase()}</span>
                <span className={`landing-ticker-pnl ${t.pnl >= 0 ? 'positive' : 'negative'}`}>
                  {t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(0)}
                </span>
                <span className="landing-ticker-time">{timeAgo(t.exit_time)}</span>
              </span>
            ))}
          </div>
        </div>
      )}
      <div className="landing-cards">
        <Link
          href="/dashboard?account=tv_paper"
          className="landing-card landing-card-live"
          aria-description="Open the live Tradovate Paper dashboard with 50K Rapid Evaluation"
        >
          <div className="landing-card-header">
            <span className="landing-card-badge live">LIVE</span>
            <h2>Tradovate Paper</h2>
          </div>
          <p>Live paper trading on Tradovate demo — 50K Rapid Evaluation</p>
          <div className="landing-card-stats">
            <span>{loading && tvLoading ? <span className="landing-stat-skeleton" /> : tvEval}</span>
            <span>{loading && tvLoading ? <span className="landing-stat-skeleton" /> : tvBalance}</span>
          </div>
          {tvStats?.equityCurve && tvStats.equityCurve.length >= 2 && (
            <Sparkline
              data={tvStats.equityCurve.map((p) => p.value)}
              className="landing-sparkline"
            />
          )}
          <span className="landing-card-cta">Open Dashboard →</span>
        </Link>
        <Link
          href="/archive/ibkr"
          className="landing-card landing-card-archive"
          aria-description="Explore archived IBKR Virtual trading history"
        >
          <div className="landing-card-header">
            <span className="landing-card-badge archived">ARCHIVED</span>
            <h2>IBKR Virtual</h2>
          </div>
          <p>Inception test account — full history preserved</p>
          <div className="landing-card-stats">
            <span>{loading && ibkrLoading ? <span className="landing-stat-skeleton" /> : ibkrTrades}</span>
            <span>{loading && ibkrLoading ? <span className="landing-stat-skeleton" /> : ibkrPnL}</span>
            <span>{loading && ibkrLoading ? <span className="landing-stat-skeleton" /> : ibkrDays}</span>
          </div>
          {ibkrDaily.length >= 2 && (
            <Sparkline
              data={ibkrDaily.slice(-14).reduce<number[]>((acc, d) => [...acc, (acc[acc.length - 1] ?? 0) + d.pnl], [0])}
              className="landing-sparkline"
            />
          )}
          <span className="landing-card-cta">Explore History →</span>
        </Link>
      </div>
      <section className="landing-journey" aria-label="Trading journey timeline">
        <h3 className="landing-journey-title">Journey</h3>
        <ol className="landing-journey-track" role="list">
          <li className="landing-journey-milestone">
            <span className="landing-journey-date">Nov 25</span>
            <span className="landing-journey-label">Project born</span>
          </li>
          <li className="landing-journey-milestone">
            <span className="landing-journey-date">Dec 30</span>
            <span className="landing-journey-label">First trade</span>
          </li>
          <li className="landing-journey-milestone milestone-positive">
            <span className="landing-journey-date">Jan 29</span>
            <span className="landing-journey-label">+$7.2K breakout</span>
          </li>
          <li className="landing-journey-milestone milestone-positive">
            <span className="landing-journey-date">Feb 3</span>
            <span className="landing-journey-label">Peak +$9.6K</span>
          </li>
          <li className="landing-journey-milestone milestone-negative">
            <span className="landing-journey-date">Feb 5</span>
            <span className="landing-journey-label">-$12.9K lesson</span>
          </li>
          <li className="landing-journey-milestone">
            <span className="landing-journey-date">Feb 12</span>
            <span className="landing-journey-label">IBKR archived</span>
          </li>
          <li className="landing-journey-milestone current">
            <span className="landing-journey-date">Now</span>
            <span className="landing-journey-label">TV Paper eval</span>
          </li>
        </ol>
      </section>
    </main>
  )
}
