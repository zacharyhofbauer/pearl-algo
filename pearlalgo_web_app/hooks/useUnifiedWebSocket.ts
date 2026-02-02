'use client'

/**
 * Unified WebSocket Hook (I3.4)
 *
 * Consolidates Pearl AI feed and Dashboard data WebSockets into a single connection
 * with message type routing. This prevents race conditions and provides a single
 * source of truth for connection status.
 *
 * Message Types:
 * - 'state_update', 'initial_state', 'full_refresh': Dashboard state updates
 * - 'pearl_message': Pearl AI narrations, insights, alerts
 * - 'pearl_suggestion': Pearl AI suggestions
 * - 'chat_response': Response to chat messages sent via WebSocket
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { useAgentStore } from '@/stores'
import { usePearlStore, type PearlMessage } from '@/stores'

export type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

interface UnifiedMessage {
  type: string
  data?: any
  // Pearl-specific fields
  content?: string
  priority?: string
  message_type?: string
  timestamp?: string
}

interface UseUnifiedWebSocketOptions {
  /** WebSocket URL for dashboard data */
  dashboardUrl: string
  /** WebSocket URL for Pearl feed (optional - uses dashboardUrl if not provided) */
  pearlUrl?: string
  /** Enable Pearl feed subscription */
  enablePearlFeed?: boolean
  /** Auto-reconnect on disconnect */
  reconnect?: boolean
  /** Reconnect interval in ms */
  reconnectInterval?: number
  /** Max reconnect attempts */
  maxReconnectAttempts?: number
  /** Ping interval in ms */
  pingInterval?: number
}

interface UseUnifiedWebSocketReturn {
  /** Connection status */
  status: ConnectionStatus
  /** Send a message to the server */
  send: (data: string | object) => void
  /** Send a chat message (Pearl AI) */
  sendChat: (message: string) => void
  /** Request full refresh of dashboard data */
  refresh: () => void
  /** Manually reconnect */
  reconnect: () => void
  /** Close the connection */
  close: () => void
  /** Number of reconnect attempts */
  reconnectAttempts: number
  /** Is Pearl feed enabled and connected */
  isPearlConnected: boolean
}

export function useUnifiedWebSocket(options: UseUnifiedWebSocketOptions): UseUnifiedWebSocketReturn {
  const {
    dashboardUrl,
    pearlUrl,
    enablePearlFeed = true,
    reconnect: shouldReconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 10,
    pingInterval = 30000,
  } = options

  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [reconnectAttempts, setReconnectAttempts] = useState(0)
  const [isPearlConnected, setIsPearlConnected] = useState(false)

  // Store references
  const updateFromWebSocket = useAgentStore((s) => s.updateFromWebSocket)
  const setAgentState = useAgentStore((s) => s.setAgentState)

  const {
    addMessage,
    setIsConnected: setPearlConnected,
  } = usePearlStore()

  // WebSocket refs
  const dashboardWsRef = useRef<WebSocket | null>(null)
  const pearlWsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const mountedRef = useRef(true)

  const clearTimers = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (pingIntervalRef.current) {
      clearInterval(pingIntervalRef.current)
      pingIntervalRef.current = null
    }
  }, [])

  // Handle dashboard WebSocket messages
  const handleDashboardMessage = useCallback((message: UnifiedMessage) => {
    if (!mountedRef.current) return

    switch (message.type) {
      case 'initial_state':
      case 'state_update':
      case 'full_refresh':
        if (message.data) {
          updateFromWebSocket(message.data)
        }
        break

      case 'error':
        console.error('[UnifiedWS] Server error:', message.data)
        break

      default:
        // Unknown message type - log for debugging
        console.debug('[UnifiedWS] Unknown message type:', message.type)
    }
  }, [updateFromWebSocket])

  // Handle Pearl WebSocket messages
  const handlePearlMessage = useCallback((message: UnifiedMessage) => {
    if (!mountedRef.current) return

    // Pearl feed messages (narrations, insights, alerts)
    if (message.content || message.type === 'pearl_message') {
      const pearlMsg: PearlMessage = {
        id: `pearl-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
        role: 'assistant',
        content: message.content || message.data?.content || '',
        timestamp: new Date(message.timestamp || Date.now()),
        type: (message.message_type || message.data?.type || 'insight') as PearlMessage['type'],
        priority: (message.priority || message.data?.priority || 'normal') as PearlMessage['priority'],
      }
      addMessage(pearlMsg)
    }

    // Chat responses
    if (message.type === 'chat_response') {
      const chatMsg: PearlMessage = {
        id: `chat-${Date.now()}`,
        role: 'assistant',
        content: message.content || message.data?.content || '',
        timestamp: new Date(message.timestamp || Date.now()),
        type: 'response',
      }
      addMessage(chatMsg)
    }
  }, [addMessage])

  // Connect to dashboard WebSocket
  const connectDashboard = useCallback(() => {
    if (dashboardWsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    setStatus('connecting')

    try {
      const ws = new WebSocket(dashboardUrl)
      dashboardWsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        setStatus('connected')
        setReconnectAttempts(0)

        // Send auth if configured
        const apiKey = process.env.NEXT_PUBLIC_API_KEY
        if (apiKey) {
          ws.send(JSON.stringify({ type: 'auth', api_key: apiKey }))
        }

        // Start ping interval
        pingIntervalRef.current = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping')
          }
        }, pingInterval)
      }

      ws.onmessage = (event) => {
        if (!mountedRef.current) return
        if (event.data === 'pong') return

        try {
          const message = JSON.parse(event.data) as UnifiedMessage
          handleDashboardMessage(message)
        } catch (e) {
          console.error('[UnifiedWS] Failed to parse dashboard message:', e)
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setStatus('disconnected')
        clearTimers()

        if (shouldReconnect && reconnectAttempts < maxReconnectAttempts) {
          reconnectTimeoutRef.current = setTimeout(() => {
            if (mountedRef.current) {
              setReconnectAttempts((prev) => prev + 1)
              connectDashboard()
            }
          }, reconnectInterval)
        }
      }

      ws.onerror = () => {
        if (!mountedRef.current) return
        setStatus('error')
      }
    } catch (e) {
      console.error('[UnifiedWS] Dashboard connection error:', e)
      setStatus('error')
    }
  }, [dashboardUrl, shouldReconnect, reconnectInterval, maxReconnectAttempts, pingInterval, reconnectAttempts, clearTimers, handleDashboardMessage])

  // Connect to Pearl WebSocket (if enabled and different URL)
  const connectPearl = useCallback(() => {
    if (!enablePearlFeed) return
    if (pearlWsRef.current?.readyState === WebSocket.OPEN) return

    const url = pearlUrl || `${dashboardUrl.replace('/ws', '/api/pearl/feed/ws')}`

    try {
      const ws = new WebSocket(url)
      pearlWsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        setIsPearlConnected(true)
        setPearlConnected(true)
      }

      ws.onmessage = (event) => {
        if (!mountedRef.current) return
        if (event.data === 'pong' || event.data === 'ping') {
          if (event.data === 'ping') {
            ws.send('pong')
          }
          return
        }

        try {
          const message = JSON.parse(event.data) as UnifiedMessage
          handlePearlMessage(message)
        } catch (e) {
          console.error('[UnifiedWS] Failed to parse Pearl message:', e)
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        setIsPearlConnected(false)
        setPearlConnected(false)

        // Attempt reconnect for Pearl feed
        if (shouldReconnect && mountedRef.current) {
          setTimeout(() => {
            if (mountedRef.current) {
              connectPearl()
            }
          }, reconnectInterval * 2) // Slower reconnect for Pearl
        }
      }

      ws.onerror = () => {
        if (!mountedRef.current) return
        setIsPearlConnected(false)
        setPearlConnected(false)
      }
    } catch (e) {
      console.error('[UnifiedWS] Pearl connection error:', e)
    }
  }, [dashboardUrl, pearlUrl, enablePearlFeed, shouldReconnect, reconnectInterval, handlePearlMessage, setPearlConnected])

  // Send message to dashboard WebSocket
  const send = useCallback((data: string | object) => {
    if (dashboardWsRef.current?.readyState === WebSocket.OPEN) {
      const message = typeof data === 'string' ? data : JSON.stringify(data)
      dashboardWsRef.current.send(message)
    }
  }, [])

  // Send chat message via Pearl WebSocket
  const sendChat = useCallback((message: string) => {
    if (pearlWsRef.current?.readyState === WebSocket.OPEN) {
      pearlWsRef.current.send(`chat:${message}`)
    } else {
      console.warn('[UnifiedWS] Pearl WebSocket not connected, cannot send chat')
    }
  }, [])

  // Request full refresh
  const refresh = useCallback(() => {
    send('refresh')
  }, [send])

  // Manual reconnect
  const manualReconnect = useCallback(() => {
    setReconnectAttempts(0)
    clearTimers()

    if (dashboardWsRef.current) {
      dashboardWsRef.current.close()
    }
    if (pearlWsRef.current) {
      pearlWsRef.current.close()
    }

    connectDashboard()
    connectPearl()
  }, [clearTimers, connectDashboard, connectPearl])

  // Close all connections
  const close = useCallback(() => {
    clearTimers()

    if (dashboardWsRef.current) {
      dashboardWsRef.current.close()
      dashboardWsRef.current = null
    }
    if (pearlWsRef.current) {
      pearlWsRef.current.close()
      pearlWsRef.current = null
    }

    setIsPearlConnected(false)
    setPearlConnected(false)
  }, [clearTimers, setPearlConnected])

  // Connect on mount
  useEffect(() => {
    mountedRef.current = true
    connectDashboard()
    connectPearl()

    return () => {
      mountedRef.current = false
      clearTimers()

      if (dashboardWsRef.current) {
        dashboardWsRef.current.close()
        dashboardWsRef.current = null
      }
      if (pearlWsRef.current) {
        pearlWsRef.current.close()
        pearlWsRef.current = null
      }
    }
  }, []) // Only run on mount/unmount

  return {
    status,
    send,
    sendChat,
    refresh,
    reconnect: manualReconnect,
    close,
    reconnectAttempts,
    isPearlConnected,
  }
}

/**
 * Get the unified WebSocket URLs.
 */
export function getUnifiedWebSocketUrls(): { dashboard: string; pearl: string } {
  if (typeof window === 'undefined') {
    return {
      dashboard: 'ws://localhost:8000/ws',
      pearl: 'ws://localhost:8000/api/pearl/feed/ws',
    }
  }

  const hostname = window.location.hostname
  const urlParams = new URLSearchParams(window.location.search)
  const apiPort = urlParams.get('api_port')

  let baseUrl: string
  if (apiPort) {
    baseUrl = `ws://localhost:${apiPort}`
  } else if (['localhost', '127.0.0.1'].includes(hostname)) {
    baseUrl = 'ws://localhost:8000'
  } else {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    baseUrl = `${protocol}//${hostname}`
  }

  return {
    dashboard: `${baseUrl}/ws`,
    pearl: `${baseUrl}/api/pearl/feed/ws`,
  }
}

export default useUnifiedWebSocket
