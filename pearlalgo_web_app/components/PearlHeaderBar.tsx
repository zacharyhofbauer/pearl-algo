'use client'

import { useEffect, useRef } from 'react'
import Image from 'next/image'
import { usePearlStore, useAgentStore, useAdminStore, type PearlMessage } from '@/stores'
import PearlDropdownPanel from './PearlDropdownPanel'
import { apiFetch } from '@/lib/api'

export default function PearlHeaderBar() {
  const {
    isConnected,
    isHeaderExpanded,
    setIsConnected,
    toggleHeaderExpanded,
    setHeaderExpanded,
    addMessage,
    setTradingContext,
    getLatestMessage,
  } = usePearlStore()

  // Get agent state for panel props - access the nested agentState property
  const agentState = useAgentStore((state) => state.agentState)

  const headerRef = useRef<HTMLDivElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

  // Get latest message for preview
  const latestMessage = getLatestMessage()

  // Truncate message for preview
  const getPreviewText = () => {
    if (!latestMessage) return 'Pearl AI ready'
    const maxLength = 60
    const text = latestMessage.content
    if (text.length <= maxLength) return text
    return text.substring(0, maxLength) + '...'
  }

  // Handle click outside to close dropdown
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (!isHeaderExpanded) return

      const target = event.target as Node

      // Check if click is outside both header and dropdown
      if (
        headerRef.current &&
        !headerRef.current.contains(target) &&
        dropdownRef.current &&
        !dropdownRef.current.contains(target)
      ) {
        setHeaderExpanded(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isHeaderExpanded, setHeaderExpanded])

  // Handle escape key to close dropdown
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && isHeaderExpanded) {
        setHeaderExpanded(false)
      }
    }

    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isHeaderExpanded, setHeaderExpanded])

  // WebSocket connection for real-time feed
  useEffect(() => {
    if (typeof window === 'undefined') return

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/pearl/feed/ws`

    const connect = () => {
      try {
        const ws = new WebSocket(wsUrl)

        ws.onopen = () => {
          setIsConnected(true)
          console.log('Pearl AI WebSocket connected')
        }

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)

            if (data.type === 'chat_response') {
              const msg: PearlMessage = {
                id: `pearl-${Date.now()}`,
                role: 'assistant',
                content: data.content,
                timestamp: new Date(data.timestamp),
                type: 'response',
              }
              addMessage(msg)
            } else if (data.content) {
              const msg: PearlMessage = {
                id: data.id || `feed-${Date.now()}`,
                role: 'assistant',
                content: data.content,
                timestamp: new Date(data.timestamp),
                type: data.type || 'narration',
                priority: data.priority || 'normal',
              }
              addMessage(msg)
            }
          } catch {
            if (event.data === 'ping') {
              ws.send('pong')
            }
          }
        }

        ws.onclose = () => {
          setIsConnected(false)
          console.log('Pearl AI WebSocket disconnected')
          setTimeout(connect, 3000)
        }

        ws.onerror = (error) => {
          console.error('Pearl AI WebSocket error:', error)
        }

        wsRef.current = ws
      } catch (e) {
        console.error('Failed to create WebSocket:', e)
      }
    }

    connect()

    return () => {
      wsRef.current?.close()
    }
  }, [setIsConnected, addMessage])

  // Fetch trading context periodically
  useEffect(() => {
    const fetchContext = async () => {
      try {
        const response = await fetch('/api/pearl/context')
        if (response.ok) {
          const data = await response.json()
          setTradingContext(data)
        }
      } catch (error) {
        console.debug('Could not fetch trading context:', error)
      }
    }

    // Fetch immediately and then every 10 seconds
    fetchContext()
    const interval = setInterval(fetchContext, 10000)

    return () => clearInterval(interval)
  }, [setTradingContext])

  // Handle suggestion accept/dismiss
  const handleAcceptSuggestion = async () => {
    try {
      const action = agentState?.pearl_suggestion?.accept_action ||
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
      const key = agentState?.pearl_suggestion?.cooldown_key ||
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

  // Admin auth
  const { requireAuth, isAuthenticated } = useAdminStore()

  const handleHeaderClick = (e: React.MouseEvent) => {
    // Don't toggle if clicking on interactive elements inside the dropdown
    const target = e.target as HTMLElement
    if (target.closest('.pearl-dropdown-panel')) return

    // If trying to expand and not authenticated, require auth
    if (!isHeaderExpanded) {
      requireAuth(() => {
        toggleHeaderExpanded()
      })
    } else {
      // Always allow closing
      toggleHeaderExpanded()
    }
  }

  return (
    <div
      ref={headerRef}
      className={`pearl-header-bar ${isHeaderExpanded ? 'expanded' : ''}`}
      onClick={handleHeaderClick}
    >
      {/* Pearl Icon */}
      <div className="pearl-header-icon">
        <Image
          src="/pearl-emoji.png"
          alt="Pearl AI"
          width={20}
          height={20}
          priority
        />
      </div>

      {/* Connection Status Dot */}
      <span className={`pearl-header-status-dot ${isConnected ? 'connected' : ''}`} />

      {/* Message Preview */}
      <div className="pearl-header-preview">
        {getPreviewText()}
      </div>

      {/* Expand/Collapse Arrow */}
      <span className="pearl-header-arrow">
        {isHeaderExpanded ? '\u25B2' : '\u25BC'}
      </span>

      {/* Dropdown Panel */}
      <div
        ref={dropdownRef}
        className="pearl-header-dropdown"
        onClick={(e) => e.stopPropagation()}
      >
        <PearlDropdownPanel
          insights={agentState?.pearl_insights ?? null}
          suggestion={agentState?.pearl_suggestion ?? null}
          aiStatus={agentState?.ai_status}
          shadowCounters={agentState?.shadow_counters}
          mlFilterPerformance={agentState?.ml_filter_performance}
          onAccept={handleAcceptSuggestion}
          onDismiss={handleDismissSuggestion}
        />
      </div>
    </div>
  )
}
