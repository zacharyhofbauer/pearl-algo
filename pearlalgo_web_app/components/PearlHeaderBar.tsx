'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import PearlInsightsPanel from './PearlInsightsPanel'
import { apiFetch } from '@/lib/api'
import { useAgentStore } from '@/stores'

export default function PearlHeaderBar() {
  const agentState = useAgentStore((s) => s.agentState)

  const [expanded, setExpanded] = useState(false)
  const headerRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  const hasAI = Boolean(agentState?.ai_status)

  const previewText = useMemo(() => {
    const suggestion =
      agentState?.pearl_suggestion?.message ||
      agentState?.pearl_insights?.current_suggestion?.message ||
      agentState?.pearl_insights?.shadow_metrics?.active_suggestion?.message ||
      null

    const base = suggestion || 'Pearl AI ready'
    const maxLength = 60
    return base.length <= maxLength ? base : `${base.slice(0, maxLength)}...`
  }, [agentState?.pearl_insights, agentState?.pearl_suggestion])

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
      }
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [expanded])

  const handleAcceptSuggestion = async () => {
    try {
      const action =
        agentState?.pearl_suggestion?.accept_action ||
        agentState?.pearl_insights?.shadow_metrics?.active_suggestion?.action
      if (action) {
        await apiFetch('/api/pearl-suggestion/accept', {
          method: 'POST',
          body: JSON.stringify({ action }),
        })
      }
    } catch (e) {
      console.error('Failed to accept Pearl insight:', e)
    }
  }

  const handleDismissSuggestion = async () => {
    try {
      const key =
        agentState?.pearl_suggestion?.cooldown_key ||
        agentState?.pearl_insights?.shadow_metrics?.active_suggestion?.id
      if (key) {
        await apiFetch('/api/pearl-suggestion/dismiss', {
          method: 'POST',
          body: JSON.stringify({ cooldown_key: key }),
        })
      }
    } catch (e) {
      console.error('Failed to dismiss Pearl insight:', e)
    }
  }

  return (
    <div
      ref={headerRef}
      className={`pearl-header-bar ${expanded ? 'expanded' : ''}`}
      onClick={() => setExpanded((v) => !v)}
    >
      <div className="pearl-header-icon">
        <Image src="/pearl-emoji.png" alt="Pearl AI" width={20} height={20} priority />
      </div>

      <span className={`pearl-header-status-dot ${hasAI ? 'connected' : ''}`} />

      <div className="pearl-header-preview">{previewText}</div>

      <span className="pearl-header-arrow">{expanded ? '▲' : '▼'}</span>

      <div
        ref={dropdownRef}
        className="pearl-header-dropdown"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pearl-dropdown-panel">
          <PearlInsightsPanel
            insights={agentState?.pearl_insights ?? null}
            suggestion={agentState?.pearl_suggestion ?? null}
            aiStatus={agentState?.ai_status ?? null}
            shadowCounters={agentState?.shadow_counters ?? null}
            mlFilterPerformance={agentState?.ml_filter_performance ?? null}
            onAccept={handleAcceptSuggestion}
            onDismiss={handleDismissSuggestion}
            initialChatOpen={true}
          />
        </div>
      </div>
    </div>
  )
}

