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

function formatBalance(n: number): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(n)
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
 * Links to /dashboard (Tradovate Paper live).
 */
export default function LandingPage() {
  const [tvStats, setTvStats] = useState<TvStats | null>(null)
  const [tvLoading, setTvLoading] = useState(true)

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

  const tvEval = tvStats ? `EVAL #${tvStats.evalNumber}` : 'EVAL #1'
  const tvBalanceVal = useCountUp(tvStats?.balance ?? null, { enabled: !tvLoading && tvStats != null })
  const tvBalance = tvStats ? `${formatBalance(tvBalanceVal)} balance` : '50K balance'

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
            <span>{tvLoading ? <span className="landing-stat-skeleton" /> : tvEval}</span>
            <span>{tvLoading ? <span className="landing-stat-skeleton" /> : tvBalance}</span>
          </div>
          {tvStats?.equityCurve && tvStats.equityCurve.length >= 2 && (
            <Sparkline
              data={tvStats.equityCurve.map((p) => p.value)}
              className="landing-sparkline"
            />
          )}
          <span className="landing-card-cta">Open Dashboard →</span>
        </Link>
      </div>
    </main>
  )
}
