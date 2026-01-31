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
  const [reconnectAttempts, setReconnectAttempts] = useState(0)

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
        setReconnectAttempts(0)

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

        // Attempt reconnection
        if (shouldReconnect && reconnectAttempts < maxReconnectAttempts) {
          reconnectTimeoutRef.current = setTimeout(() => {
            if (mountedRef.current) {
              setReconnectAttempts((prev) => prev + 1)
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
  }, [url, shouldReconnect, reconnectInterval, maxReconnectAttempts, pingInterval, reconnectAttempts, clearTimers, updateStatus, onMessage])

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
 * Get the WebSocket URL based on the current environment
 *
 * Includes API key as query parameter when NEXT_PUBLIC_API_KEY is set
 */
export function getWebSocketUrl(): string {
  if (typeof window === 'undefined') {
    return 'ws://localhost:8000/ws'
  }

  const hostname = window.location.hostname
  const apiKey = process.env.NEXT_PUBLIC_API_KEY || ''

  // Check URL params for API port override
  const urlParams = new URLSearchParams(window.location.search)
  const apiPort = urlParams.get('api_port')

  let baseUrl: string
  if (apiPort) {
    baseUrl = `ws://localhost:${apiPort}/ws`
  } else if (['localhost', '127.0.0.1'].includes(hostname)) {
    // Local development
    baseUrl = 'ws://localhost:8000/ws'
  } else {
    // Production - use secure WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    baseUrl = `${protocol}//${hostname}/ws`
  }

  // Append API key if configured
  if (apiKey) {
    return `${baseUrl}?api_key=${encodeURIComponent(apiKey)}`
  }

  return baseUrl
}

export default useWebSocket
