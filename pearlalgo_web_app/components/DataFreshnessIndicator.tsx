'use client'

import { useState, useEffect, useCallback } from 'react'
import type { WebSocketStatus } from '@/hooks/useWebSocket'

interface DataFreshnessIndicatorProps {
  lastUpdate: Date | null
  wsStatus: WebSocketStatus
  dataSource: 'live' | 'cached' | 'unknown'
  isLoading: boolean
  staleThresholdSeconds?: number
  onRefresh?: () => void
}

export default function DataFreshnessIndicator({
  lastUpdate,
  wsStatus,
  dataSource,
  isLoading,
  staleThresholdSeconds = 60,
  onRefresh,
}: DataFreshnessIndicatorProps) {
  const [secondsAgo, setSecondsAgo] = useState<number>(0)
  const [pulseKey, setPulseKey] = useState<number>(0)

  // Update seconds ago every second
  useEffect(() => {
    const updateAge = () => {
      if (lastUpdate) {
        const diff = Math.floor((Date.now() - lastUpdate.getTime()) / 1000)
        setSecondsAgo(diff)
      }
    }
    updateAge()
    const interval = setInterval(updateAge, 1000)
    return () => clearInterval(interval)
  }, [lastUpdate])

  // Trigger pulse animation on new data
  useEffect(() => {
    if (lastUpdate) {
      setPulseKey((k) => k + 1)
    }
  }, [lastUpdate])

  const isStale = secondsAgo > staleThresholdSeconds
  const isWarning = secondsAgo > staleThresholdSeconds / 2 && secondsAgo <= staleThresholdSeconds

  // Format time ago
  const formatTimeAgo = (seconds: number): string => {
    if (seconds < 5) return 'just now'
    if (seconds < 60) return `${seconds}s ago`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s ago`
    return `${Math.floor(seconds / 3600)}h ago`
  }

  // Get status color class
  const getStatusClass = (): string => {
    if (isLoading) return 'loading'
    if (isStale) return 'stale'
    if (isWarning) return 'warning'
    return 'fresh'
  }

  // Get WebSocket status display
  const getWsDisplay = () => {
    switch (wsStatus) {
      case 'connected':
        return { icon: '⚡', label: 'WS', className: 'ws-connected' }
      case 'connecting':
        return { icon: '🔄', label: 'WS', className: 'ws-connecting' }
      case 'disconnected':
        return { icon: '📡', label: 'Poll', className: 'ws-disconnected' }
      case 'error':
        return { icon: '❌', label: 'Err', className: 'ws-error' }
      default:
        return { icon: '❓', label: '?', className: 'ws-unknown' }
    }
  }

  // Get data source display
  const getSourceDisplay = () => {
    switch (dataSource) {
      case 'live':
        return { label: 'LIVE', className: 'source-live' }
      case 'cached':
        return { label: 'CACHED', className: 'source-cached' }
      default:
        return { label: '?', className: 'source-unknown' }
    }
  }

  const wsDisplay = getWsDisplay()
  const sourceDisplay = getSourceDisplay()
  const statusClass = getStatusClass()

  return (
    <div className={`data-freshness-indicator ${statusClass}`}>
      {/* Heartbeat Pulse */}
      <div className="freshness-heartbeat" key={pulseKey}>
        <span className={`heartbeat-dot ${isLoading ? 'loading' : ''}`}></span>
      </div>

      {/* Time Since Update */}
      <div className="freshness-time">
        <span className="time-label">Updated</span>
        <span className={`time-value ${statusClass}`}>
          {lastUpdate ? formatTimeAgo(secondsAgo) : 'never'}
        </span>
      </div>

      {/* Data Source Badge */}
      <div className={`freshness-source ${sourceDisplay.className}`}>
        {sourceDisplay.label}
      </div>

      {/* WebSocket Status */}
      <div className={`freshness-ws ${wsDisplay.className}`} title={`WebSocket: ${wsStatus}`}>
        <span className="ws-icon">{wsDisplay.icon}</span>
        <span className="ws-label">{wsDisplay.label}</span>
      </div>

      {/* Refresh Button */}
      {onRefresh && (
        <button
          className={`freshness-refresh ${isLoading ? 'spinning' : ''}`}
          onClick={onRefresh}
          disabled={isLoading}
          title="Force refresh"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
        </button>
      )}

      {/* Loading Spinner Overlay */}
      {isLoading && (
        <div className="freshness-loading-overlay">
          <div className="loading-spinner"></div>
        </div>
      )}
    </div>
  )
}
