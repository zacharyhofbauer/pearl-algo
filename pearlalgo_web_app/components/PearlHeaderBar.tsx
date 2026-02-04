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

export default function PearlHeaderBar() {
  const agentState = useAgentStore((s) => s.agentState)
  const tickOperator = useOperatorStore((s) => s.tick)

  const [expanded, setExpanded] = useState(false)
  const headerRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const hasAI = Boolean(agentState?.pearl_ai_available || agentState?.ai_status)
  const isConnected = Boolean(agentState?.running)

  // Use centralized helper to derive AI mode
  const aiMode = useMemo(() => {
    return derivePearlMode(agentState?.ai_status || null, agentState?.pearl_insights || null)
  }, [agentState?.ai_status, agentState?.pearl_insights])

  // Use centralized helper to derive headline/preview text
  const previewText = useMemo(() => {
    const headline = deriveHeadline(
      agentState?.pearl_feed || [],
      agentState?.pearl_suggestion || null,
      agentState?.pearl_insights || null
    )
    const base = headline.text
    const maxLength = 60
    return base.length <= maxLength ? base : `${base.slice(0, maxLength)}…`
  }, [agentState?.pearl_feed, agentState?.pearl_insights, agentState?.pearl_suggestion])

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
      className={`pearl-header-bar ${expanded ? 'expanded' : ''}`}
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

      <div className="pearl-header-preview" aria-hidden="true">
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

