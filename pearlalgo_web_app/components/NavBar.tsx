'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import Image from 'next/image'
import { usePathname } from 'next/navigation'
import { useAgentStore, useChartStore } from '@/stores'
import { derivePearlMode, deriveHeadline } from '@/types/pearl'
import { formatMarketCountdown } from '@/lib/formatters'

function truncateText(text: string, maxLength: number): string {
  return text.length <= maxLength ? text : `${text.slice(0, maxLength)}\u2026`
}

function cleanText(raw: string): string {
  return raw.replace(/["\u201c\u201d'\u2018\u2019`]/g, '').trim()
}

export default function NavBar() {
  const pathname = usePathname()
  const agentState = useAgentStore((s) => s.agentState)
  const marketStatus = useChartStore((s) => s.marketStatus)

  const isHome = pathname === '/' || pathname === ''
  const isDashboard = pathname?.startsWith('/dashboard')
  const isArchive = pathname?.startsWith('/archive')

  const dashboardContext = useMemo(() => {
    if (!isDashboard || !agentState) return null
    const hasAI = Boolean(agentState.ai_status)
    const isConnected = Boolean(agentState.running)
    const isMarketOpen = agentState.futures_market_open ?? true

    const aiMode = derivePearlMode(agentState.ai_status || null, agentState.pearl_insights || null)
    const headline = deriveHeadline(
      agentState.pearl_feed || [],
      agentState.pearl_suggestion || null,
      agentState.pearl_insights || null
    )
    const previewText = truncateText(cleanText(headline.text), 42)

    let statusDotClass = ''
    if (!isMarketOpen) statusDotClass = 'market-closed'
    else if (hasAI || isConnected) {
      if (aiMode === 'live') statusDotClass = 'live'
      else if (aiMode === 'shadow') statusDotClass = 'shadow'
      else statusDotClass = 'connected'
    }

    let closedText = 'Market Closed'
    if (!isMarketOpen && marketStatus?.next_open) {
      const countdown = formatMarketCountdown(marketStatus.next_open)
      if (countdown) closedText = countdown
    }

    return {
      symbol: agentState.config?.symbol || 'MNQ',
      statusDotClass,
      previewText: !isMarketOpen ? closedText : previewText,
    }
  }, [isDashboard, agentState, marketStatus])

  return (
    <nav className="nav-bar" role="navigation" aria-label="Main">
      <div className="nav-bar-inner">
        <Link
          href="/"
          className={`nav-bar-brand ${isHome ? 'active' : ''}`}
          aria-label="PEARL Home"
          aria-current={isHome ? 'page' : undefined}
        >
          <Image src="/logo.png" alt="" width={24} height={24} className="nav-bar-logo" />
          <span className="nav-bar-name">PEARL</span>
        </Link>
        <div className="nav-bar-links">
          <Link
            href="/dashboard?account=tv_paper"
            className={`nav-bar-link ${isDashboard ? 'active' : ''}`}
            aria-current={isDashboard ? 'page' : undefined}
          >
            Dashboard
          </Link>
          <Link
            href="/archive/ibkr"
            className={`nav-bar-link ${isArchive ? 'active' : ''}`}
            aria-current={isArchive ? 'page' : undefined}
          >
            Archive
          </Link>
          {dashboardContext && (
            <div className="nav-dashboard-context" aria-label="Dashboard status">
              <span className="nav-context-symbol">{dashboardContext.symbol}</span>
              <span
                className={`nav-context-dot ${dashboardContext.statusDotClass}`}
                role="status"
                aria-label={dashboardContext.previewText}
              />
              <span className="nav-context-preview">{dashboardContext.previewText}</span>
            </div>
          )}
        </div>
      </div>
    </nav>
  )
}
