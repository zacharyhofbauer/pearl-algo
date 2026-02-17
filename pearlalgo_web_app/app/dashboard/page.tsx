'use client'

import { useEffect } from 'react'
import { useSearchParams } from 'next/navigation'
import DashboardPageInner from './DashboardPageInner'

/**
 * Dashboard page - Live trading view (Tradovate Paper).
 * Redirects to ?account=tv_paper if not set, so API/WS always target the live account.
 */
export default function DashboardPage() {
  const searchParams = useSearchParams()

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!searchParams?.has('account')) {
      const url = new URL(window.location.href)
      url.searchParams.set('account', 'tv_paper')
      window.location.replace(url.toString())
    }
  }, [searchParams])

  // Brief loading state while redirecting
  if (typeof window !== 'undefined' && !searchParams?.has('account')) {
    return (
      <div className="account-gate-loading" role="status" aria-label="Loading dashboard">
        <div className="account-gate-loading-spinner" />
        <span className="account-gate-loading-text">Loading…</span>
      </div>
    )
  }

  return <DashboardPageInner />
}
