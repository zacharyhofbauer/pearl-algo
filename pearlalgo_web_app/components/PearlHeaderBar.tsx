'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import PearlInsightsPanel from './PearlInsightsPanel'
import { useAgentStore, useOperatorStore } from '@/stores'
import { derivePearlMode, deriveHeadline } from '@/types/pearl'

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

  const [expanded, setExpanded] = useState(false)
  const [carouselIndex, setCarouselIndex] = useState(0)
  const [isTransitioning, setIsTransitioning] = useState(false)
  const headerRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const hasAI = Boolean(agentState?.pearl_ai_available || agentState?.ai_status)
  const isConnected = Boolean(agentState?.running)

  // Use centralized helper to derive AI mode
  const aiMode = useMemo(() => {
    return derivePearlMode(agentState?.ai_status || null, agentState?.pearl_insights || null)
  }, [agentState?.ai_status, agentState?.pearl_insights])

  // Data summary (default view)
  const dataSummary = useMemo(() => {
    if (!agentState) return 'Connecting…'

    const parts: string[] = []

    const pnl = agentState.daily_pnl || 0
    const pnlSign = pnl >= 0 ? '+' : ''
    parts.push(`${pnlSign}$${pnl.toFixed(0)}`)

    const w = agentState.daily_wins || 0
    const l = agentState.daily_losses || 0
    if (w + l > 0) parts.push(`${w}W/${l}L`)

    const active = agentState.active_trades_count || 0
    if (active > 0) parts.push(`${active} active`)

    const regime = agentState.market_regime
    if (regime && regime.regime && regime.regime !== 'unknown') {
      const label = regime.regime.replace('trending_', '').replace('_', ' ')
      parts.push(label.charAt(0).toUpperCase() + label.slice(1))
    }

    return parts.join(' · ') || 'Watching…'
  }, [agentState])

  // Flash Pearl AI messages briefly (5s) then return to data summary
  const [flashMessage, setFlashMessage] = useState<string | null>(null)
  const lastSeenFeedId = useRef<string | null>(null)
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    const feed = agentState?.pearl_feed || []
    if (feed.length === 0) return

    const latest = feed[0] // Most recent message
    if (!latest?.id || latest.id === lastSeenFeedId.current) return

    // New message arrived
    lastSeenFeedId.current = latest.id

    // Strip all quotation marks from message text (straight, curly, backtick)
    let text = (latest.content || '')
      .replace(/"/g, '')
      .replace(/\u201c/g, '')
      .replace(/\u201d/g, '')
      .replace(/'/g, '')
      .replace(/\u2018/g, '')
      .replace(/\u2019/g, '')
      .replace(/`/g, '')
      .trim()

    // Show type indicator
    const typeIcon = latest.type === 'narration' ? '💬' :
                     latest.type === 'insight' ? '💡' :
                     latest.type === 'alert' ? '⚠️' :
                     latest.type === 'response' ? '🤖' : '💬'

    setFlashMessage(`${typeIcon} ${truncateText(text, 50)}`)

    // Clear previous timer
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current)

    // Auto-dismiss after 5 seconds
    flashTimerRef.current = setTimeout(() => {
      setFlashMessage(null)
    }, 5000)
  }, [agentState?.pearl_feed])

  // Cleanup timer on unmount
  useEffect(() => {
    return () => { if (flashTimerRef.current) clearTimeout(flashTimerRef.current) }
  }, [])

  // Show flash message if active, otherwise show data summary
  const previewText = flashMessage || dataSummary
  const isFlashing = Boolean(flashMessage)

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

  // Status dot class based on connection and AI state
  const statusDotClass = useMemo(() => {
    if (!hasAI && !isConnected) return ''
    if (aiMode === 'live') return 'connected live'
    if (aiMode === 'shadow') return 'connected shadow'
    if (aiMode !== 'off' || hasAI) return 'connected'
    return ''
  }, [hasAI, isConnected, aiMode])

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
      aria-label={`Pearl AI panel, ${expanded ? 'expanded' : 'collapsed'}. ${previewText}`}
    >
      <div className="pearl-header-icon" aria-hidden="true">
        <Image src="/pearl-emoji.png" alt="" width={20} height={20} priority />
      </div>

      <span
        className={`pearl-header-status-dot ${statusDotClass}`}
        role="status"
        aria-label={hasAI ? `Pearl AI ${aiMode}` : 'Pearl AI disconnected'}
      />

      <div className={`pearl-header-preview ${isFlashing ? 'flash' : ''}`} aria-hidden="true">
        {previewText}
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
          <PearlInsightsPanel
            insights={agentState?.pearl_insights ?? null}
            suggestion={agentState?.pearl_suggestion ?? null}
            agentState={agentState ?? null}
            aiStatus={agentState?.ai_status ?? null}
            shadowCounters={agentState?.shadow_counters ?? null}
            mlFilterPerformance={agentState?.ml_filter_performance ?? null}
            chatAvailable={Boolean(agentState?.pearl_ai_available)}
            operatorLockEnabled={agentState?.operator_lock_enabled ?? null}
            pearlFeed={agentState?.pearl_feed ?? []}
            pearlAIHeartbeat={agentState?.pearl_ai_heartbeat ?? null}
            pearlAIDebug={agentState?.pearl_ai_debug ?? null}
            layout="dropdown"
            dropdownActive={expanded}
            initialChatOpen={false}
          />
        </div>
      </div>
    </div>
  )
}

