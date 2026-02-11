'use client'

import { useEffect, useRef, useState, useCallback } from 'react'

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error'

interface WebSocketMessage {
  type: string
  data?: any
}

interface UseWebSocketOptions {
  /** WebSocket URL */
  url: string
  /** Reconnect on disconnect (default: true) */
  reconnect?: boolean
  /** Reconnect interval in ms (default: 3000) */
  reconnectInterval?: number
  /** Max reconnect attempts (default: 10) */
  maxReconnectAttempts?: number
  /** Ping interval in ms (default: 30000) */
  pingInterval?: number
  /** Callback for incoming messages */
  onMessage?: (message: WebSocketMessage) => void
  /** Callback for connection status changes */
  onStatusChange?: (status: WebSocketStatus) => void
}

interface UseWebSocketReturn {
  /** Current connection status */
  status: WebSocketStatus
  /** Last received message */
  lastMessage: WebSocketMessage | null
  /** Send a message */
  send: (data: string | object) => void
  /** Request a full refresh */
  refresh: () => void
  /** Manually reconnect */
  reconnect: () => void
  /** Close the connection */
  close: () => void
  /** Number of reconnect attempts */
  reconnectAttempts: number
}

export function useWebSocket(options: UseWebSocketOptions): UseWebSocketReturn {
  const {
    url,
    reconnect: shouldReconnect = true,
    reconnectInterval = 3000,
    maxReconnectAttempts = 10,
    pingInterval = 30000,
    onMessage,
    onStatusChange,
  } = options

  const [status, setStatus] = useState<WebSocketStatus>('disconnected')
  const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null)
  // Use a ref for reconnect attempts to avoid stale closures in onclose handler.
  // The state version is kept for the return value (UI consumption).
  const [reconnectAttempts, setReconnectAttempts] = useState(0)
  const reconnectAttemptsRef = useRef(0)

  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const mountedRef = useRef(true)

  const updateStatus = useCallback((newStatus: WebSocketStatus) => {
    if (!mountedRef.current) return
    setStatus(newStatus)
    onStatusChange?.(newStatus)
  }, [onStatusChange])

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

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    clearTimers()
    updateStatus('connecting')

    try {
      const ws = new WebSocket(url)
      wsRef.current = ws

      ws.onopen = () => {
        if (!mountedRef.current) return
        updateStatus('connected')
        reconnectAttemptsRef.current = 0
        setReconnectAttempts(0)

        // Send authentication message if API key is configured
        // This is more secure than passing key in URL (avoids browser history, logs)
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
        try {
          const message = JSON.parse(event.data) as WebSocketMessage
          setLastMessage(message)
          onMessage?.(message)
        } catch (e) {
          console.error('[WebSocket] Failed to parse message:', e)
        }
      }

      ws.onclose = () => {
        if (!mountedRef.current) return
        updateStatus('disconnected')
        clearTimers()

        // Use the ref (not state) to avoid stale closure issues
        if (shouldReconnect && reconnectAttemptsRef.current < maxReconnectAttempts) {
          reconnectTimeoutRef.current = setTimeout(() => {
            if (mountedRef.current) {
              reconnectAttemptsRef.current += 1
              setReconnectAttempts(reconnectAttemptsRef.current)
              connect()
            }
          }, reconnectInterval)
        }
      }

      ws.onerror = () => {
        if (!mountedRef.current) return
        updateStatus('error')
      }
    } catch (e) {
      console.error('[WebSocket] Connection error:', e)
      updateStatus('error')
    }
  }, [url, shouldReconnect, reconnectInterval, maxReconnectAttempts, pingInterval, clearTimers, updateStatus, onMessage])

  const send = useCallback((data: string | object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message = typeof data === 'string' ? data : JSON.stringify(data)
      wsRef.current.send(message)
    }
  }, [])

  const refresh = useCallback(() => {
    send('refresh')
  }, [send])

  const manualReconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0
    setReconnectAttempts(0)
    if (wsRef.current) {
      wsRef.current.close()
    }
    connect()
  }, [connect])

  const close = useCallback(() => {
    clearTimers()
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [clearTimers])

  // Connect on mount
  useEffect(() => {
    mountedRef.current = true
    connect()

    return () => {
      mountedRef.current = false
      clearTimers()
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, []) // Only run on mount/unmount

  return {
    status,
    lastMessage,
    send,
    refresh,
    reconnect: manualReconnect,
    close,
    reconnectAttempts,
  }
}

/**
 * Get the WebSocket URL based on the current environment.
 *
 * Note: API key is NOT included in the URL for security reasons.
 * Instead, authentication is handled via the first message after connection
 * using the 'auth' message type. This prevents API keys from appearing in:
 * - Browser history
 * - Server access logs
 * - Network proxy logs
 */
export function getWebSocketUrl(): string {
  if (typeof window === 'undefined') {
    return 'ws://localhost:8000/ws'
  }

  const hostname = window.location.hostname

  // Check URL params for API port override
  const urlParams = new URLSearchParams(window.location.search)
  const apiPort = urlParams.get('api_port')

  // Account-based switching: ?account=mffu uses /mffu/ws prefix on production
  const urlParams2 = new URLSearchParams(window.location.search)
  const account = urlParams2.get('account')
  const isLocal = ['localhost', '127.0.0.1'].includes(hostname)

  if (account === 'mffu') {
    if (isLocal) {
      return 'ws://localhost:8001/ws'
    }
    // Production: /mffu/ws routed by Cloudflare tunnel to port 8001
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${hostname}/mffu/ws`
  }

  if (apiPort) {
    if (isLocal) {
      return `ws://localhost:${apiPort}/ws`
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${hostname}:${apiPort}/ws`
  } else if (isLocal) {
    // Local development
    return 'ws://localhost:8000/ws'
  } else {
    // Production - use secure WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${hostname}/ws`
  }
}

/**
 * Get the API key for WebSocket authentication.
 * Returns empty string if not configured.
 */
export function getWebSocketApiKey(): string {
  return process.env.NEXT_PUBLIC_API_KEY || ''
}

export default useWebSocket
