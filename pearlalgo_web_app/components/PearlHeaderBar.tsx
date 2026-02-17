'use client'

import { useEffect, useMemo } from 'react'
import Image from 'next/image'
import AccountSwitcher from './AccountSwitcher'
import { useAgentStore, useOperatorStore } from '@/stores'
import { derivePearlMode, deriveHeadline } from '@/types/pearl'

function truncateText(text: string, maxLength: number): string {
  return text.length <= maxLength ? text : `${text.slice(0, maxLength)}\u2026`
}

function cleanText(raw: string): string {
  return raw
    .replace(/["\u201c\u201d'\u2018\u2019`]/g, '')
    .trim()
}

export default function PearlHeaderBar() {
  const agentState = useAgentStore((s) => s.agentState)
  const tickOperator = useOperatorStore((s) => s.tick)

  const hasAI = Boolean(agentState?.ai_status)
  const isConnected = Boolean(agentState?.running)
  const isMarketOpen = agentState?.futures_market_open ?? true

  const aiMode = useMemo(() => {
    return derivePearlMode(agentState?.ai_status || null, agentState?.pearl_insights || null)
  }, [agentState?.ai_status, agentState?.pearl_insights])

  const previewText = useMemo(() => {
    const feed = agentState?.pearl_feed || []
    if (feed.length > 0 && feed[0]?.content) {
      return truncateText(cleanText(feed[0].content), 55)
    }
    const headline = deriveHeadline(
      agentState?.pearl_feed || [],
      agentState?.pearl_suggestion || null,
      agentState?.pearl_insights || null
    )
    return truncateText(cleanText(headline.text), 55)
  }, [agentState?.pearl_feed, agentState?.pearl_suggestion, agentState?.pearl_insights])

  useEffect(() => {
    const id = window.setInterval(() => tickOperator(), 2000)
    return () => window.clearInterval(id)
  }, [tickOperator])

  const statusDotClass = useMemo(() => {
    if (!isMarketOpen) return 'market-closed'
    if (!hasAI && !isConnected) return ''
    if (aiMode === 'live') return 'connected live'
    if (aiMode === 'shadow') return 'connected shadow'
    if (aiMode !== 'off' || hasAI) return 'connected'
    return ''
  }, [hasAI, isConnected, aiMode, isMarketOpen])

  return (
    <div className={`pearl-header-bar mode-${aiMode}`} role="banner" aria-label="Pearl AI status">
      <div className="pearl-header-icon" aria-hidden="true">
        <Image src="/pearl-emoji.png" alt="" width={20} height={20} priority />
      </div>

      <AccountSwitcher />

      <span
        className={`pearl-header-status-dot ${statusDotClass}`}
        role="status"
        aria-label={!isMarketOpen ? 'Market closed' : hasAI ? `Pearl AI ${aiMode}` : 'Pearl AI disconnected'}
      />

      <div className="pearl-header-preview" aria-hidden="true">
        {!isMarketOpen ? 'Market Closed' : previewText}
      </div>
    </div>
  )
}
