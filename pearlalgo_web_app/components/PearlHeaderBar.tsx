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

  // Build carousel items from feed messages (last 5, most recent first)
  const carouselItems = useMemo(() => {
    const items: string[] = []
    const maxLength = 55
    
    // Add the primary headline first
    const headline = deriveHeadline(
      agentState?.pearl_feed || [],
      agentState?.pearl_suggestion || null,
      agentState?.pearl_insights || null
    )
    items.push(truncateText(headline.text, maxLength))
    
    // Add recent feed messages (skip if same as headline)
    const feed = agentState?.pearl_feed || []
    for (let i = 0; i < Math.min(feed.length, 4); i++) {
      const msg = feed[i]
      if (msg?.content && msg.content !== headline.text) {
        items.push(truncateText(msg.content, maxLength))
      }
    }
    
    return items.length > 0 ? items : ['Watching for opportunities…']
  }, [agentState?.pearl_feed, agentState?.pearl_insights, agentState?.pearl_suggestion])

  // Carousel rotation (every 6 seconds, subtle)
  useEffect(() => {
    if (carouselItems.length <= 1 || expanded) return
    
    const interval = setInterval(() => {
      setIsTransitioning(true)
      setTimeout(() => {
        setCarouselIndex((prev) => (prev + 1) % carouselItems.length)
        setIsTransitioning(false)
      }, 300) // Fade out duration
    }, 6000) // Rotate every 6 seconds
    
    return () => clearInterval(interval)
  }, [carouselItems.length, expanded])

  // Reset carousel index when items change significantly
  useEffect(() => {
    if (carouselIndex >= carouselItems.length) {
      setCarouselIndex(0)
    }
  }, [carouselItems.length, carouselIndex])

  // Current preview text for display
  const previewText = carouselItems[carouselIndex] || carouselItems[0]

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

      <div className={`pearl-header-preview ${isTransitioning ? 'fading' : ''}`} aria-hidden="true">
        {previewText}
        {carouselItems.length > 1 && !expanded && (
          <span className="pearl-header-carousel-dots">
            {carouselItems.map((_, i) => (
              <span key={i} className={`carousel-dot ${i === carouselIndex ? 'active' : ''}`} />
            ))}
          </span>
        )}
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

