'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import AccountSwitcher from './AccountSwitcher'
import { useAgentStore, useOperatorStore } from '@/stores'
import { derivePearlMode, deriveHeadline } from '@/types/pearl'

/** Resolve active account display_name from the store accounts config */
function useActiveAccountName(): string {
  const accounts = useAgentStore((s) => s.accounts)
  if (!accounts) return 'Pearl AI'
  if (typeof window === 'undefined') return 'Pearl AI'
  const param = new URLSearchParams(window.location.search).get('account')
  // param is null for ibkr_virtual (default), 'tv_paper' for prop firm, etc.
  const key = param || 'ibkr_virtual'
  return accounts[key]?.display_name || 'Pearl AI'
}

/** Chevron icon component for consistent rendering */
function ChevronIcon({ direction }: { direction: 'up' | 'down' }) {
  return (
    <svg
      className={`pearl-header-chevron ${direction}`}
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden="true"
    >
      <path
        d={direction === 'up' ? 'M2 8L6 4L10 8' : 'M2 4L6 8L10 4'}
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}

/** Truncate text with ellipsis */
function truncateText(text: string, maxLength: number): string {
  return text.length <= maxLength ? text : `${text.slice(0, maxLength)}…`
}

export default function PearlHeaderBar() {
  const agentState = useAgentStore((s) => s.agentState)
  const tickOperator = useOperatorStore((s) => s.tick)
  const accountName = useActiveAccountName()

  const [expanded, setExpanded] = useState(false)
  const [carouselIndex, setCarouselIndex] = useState(0)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const headerRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const hasAI = Boolean(agentState?.ai_status)
  const isConnected = Boolean(agentState?.running)

  // Use centralized helper to derive AI mode
  const aiMode = useMemo(() => {
    return derivePearlMode(agentState?.ai_status || null, agentState?.pearl_insights || null)
  }, [agentState?.ai_status, agentState?.pearl_insights])

  // Strip quotes helper
  const cleanText = (raw: string) => raw
    .replace(/"/g, '')
    .replace(/\u201c/g, '')
    .replace(/\u201d/g, '')
    .replace(/'/g, '')
    .replace(/\u2018/g, '')
    .replace(/\u2019/g, '')
    .replace(/`/g, '')
    .trim()

  // Show Pearl AI messages (latest from feed)
  const previewText = useMemo(() => {
    const feed = agentState?.pearl_feed || []
    if (feed.length > 0 && feed[0]?.content) {
      return truncateText(cleanText(feed[0].content), 55)
    }

    // Fallback to suggestion or headline
    const headline = deriveHeadline(
      agentState?.pearl_feed || [],
      agentState?.pearl_suggestion || null,
      agentState?.pearl_insights || null
    )
    return truncateText(cleanText(headline.text), 55)
  }, [agentState?.pearl_feed, agentState?.pearl_suggestion, agentState?.pearl_insights])

  // Toggle handler with keyboard support
  const handleToggle = useCallback(() => {
    setExpanded((v) => !v)
  }, [])

  // Keyboard handler for accessibility
  const handleKeyDown = useCallback((event: React.KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      handleToggle()
    }
  }, [handleToggle])

  // Close dropdown on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (!expanded) return
      const target = event.target as Node

      if (
        headerRef.current &&
        !headerRef.current.contains(target) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(target)
      ) {
        setExpanded(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [expanded])

  // Close dropdown on Escape
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && expanded) {
        setExpanded(false)
        // Return focus to the header bar
        headerRef.current?.focus()
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [expanded])

  // Operator unlock is time-limited; tick periodically to auto-lock.
  useEffect(() => {
    const id = window.setInterval(() => tickOperator(), 2000)
    return () => window.clearInterval(id)
  }, [tickOperator])

  // Market open/closed status from agent state
  const isMarketOpen = agentState?.futures_market_open ?? true

  // Status dot class based on connection and AI state
  const statusDotClass = useMemo(() => {
    if (!isMarketOpen) return 'market-closed'
    if (!hasAI && !isConnected) return ''
    if (aiMode === 'live') return 'connected live'
    if (aiMode === 'shadow') return 'connected shadow'
    if (aiMode !== 'off' || hasAI) return 'connected'
    return ''
  }, [hasAI, isConnected, aiMode, isMarketOpen])

  return (
    <div
      ref={headerRef}
      className={`pearl-header-bar ${expanded ? 'expanded' : ''} mode-${aiMode}`}
      onClick={handleToggle}
      onKeyDown={handleKeyDown}
      role="button"
      tabIndex={0}
      aria-expanded={expanded}
      aria-controls="pearl-dropdown"
      aria-label={`${accountName} — Pearl AI panel, ${expanded ? 'expanded' : 'collapsed'}. ${previewText}`}
    >
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
        {!isMarketOpen
          ? 'Market Closed'
          : previewText}
      </div>

      <span className="pearl-header-arrow" aria-hidden="true">
        <ChevronIcon direction={expanded ? 'up' : 'down'} />
      </span>

      <div
        ref={dropdownRef}
        id="pearl-dropdown"
        className="pearl-header-dropdown"
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => e.stopPropagation()}
        role="region"
        aria-label="Pearl AI Controls"
      >
        <div className="pearl-dropdown-panel">
          <p style={{ padding: '16px', color: 'var(--text-secondary)' }}>
            AI insights panel removed during restructure.
          </p>
        </div>
      </div>
    </div>
  )
}

