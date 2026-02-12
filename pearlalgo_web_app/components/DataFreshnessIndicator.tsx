'use client'

import { useState, useEffect, useCallback } from 'react'
import type { WebSocketStatus } from '@/hooks/useWebSocket'
import { formatTimeAgo } from '@/utils/formatting'

interface DataFreshnessIndicatorProps {
  lastUpdate: Date | null
  wsStatus: WebSocketStatus
  dataSource: 'live' | 'cached' | 'unknown'
  isLoading: boolean
  staleThresholdSeconds?: number
  onRefresh?: () => void
  variant?: 'full' | 'compact' | 'floating'
  onFitAll?: () => void  // Chart action: fit all content
  onGoLive?: () => void  // Chart action: scroll to real time
}

export default function DataFreshnessIndicator({
  lastUpdate,
  wsStatus,
  dataSource,
  isLoading,
  staleThresholdSeconds = 60,
  onRefresh,
  variant = 'compact',
  onFitAll,
  onGoLive,
}: DataFreshnessIndicatorProps) {
  const [secondsAgo, setSecondsAgo] = useState<number>(0)
  const [pulseKey, setPulseKey] = useState<number>(0)
  const [isExpanded, setIsExpanded] = useState(false)

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

  // formatTimeAgo imported from utils/formatting

  // Get status color class
  const getStatusClass = (): string => {
    if (isLoading) return 'loading'
    if (isStale) return 'stale'
    if (isWarning) return 'warning'
    return 'fresh'
  }

  // Get WebSocket status display with icons
  const getWsDisplay = () => {
    switch (wsStatus) {
      case 'connected':
        return {
          label: 'WS',
          className: 'ws-connected',
          icon: (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M13 3L4 14h7l-2 7 9-11h-7l2-7z"/>
            </svg>
          )
        }
      case 'connecting':
        return {
          label: 'WS',
          className: 'ws-connecting',
          icon: (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="spin-icon" aria-hidden="true">
              <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" opacity="0.25"/>
              <path d="M21 12a9 9 0 01-9 9"/>
            </svg>
          )
        }
      case 'disconnected':
        return {
          label: 'POLL',
          className: 'ws-disconnected',
          icon: (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="12" cy="12" r="10"/>
              <path d="M2 12h4M18 12h4M12 2v4M12 18v4"/>
            </svg>
          )
        }
      case 'error':
        return {
          label: 'ERR',
          className: 'ws-error',
          icon: (
            <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 2L2 22h20L12 2zm0 6v6m0 4h.01"/>
            </svg>
          )
        }
      default:
        return { label: '?', className: 'ws-unknown', icon: null }
    }
  }

  // Get data source display
  const getSourceDisplay = () => {
    switch (dataSource) {
      case 'live':
        return { label: 'LIVE', className: 'source-live' }
      case 'cached':
        return { label: 'CACHE', className: 'source-cached' }
      default:
        return { label: '?', className: 'source-unknown' }
    }
  }

  const wsDisplay = getWsDisplay()
  const sourceDisplay = getSourceDisplay()
  const statusClass = getStatusClass()

  // Compact inline version - just dot + time
  if (variant === 'compact') {
    return (
      <div
        className={`freshness-compact ${statusClass}`}
        onClick={() => setIsExpanded(!isExpanded)}
        title="Click for details"
        aria-expanded={isExpanded}
      >
        <span className={`freshness-dot ${isLoading ? 'loading' : ''}`} role="status" aria-label={`Data ${isStale ? 'stale' : isWarning ? 'warning' : 'fresh'}, updated ${formatTimeAgo(secondsAgo)} ago`} key={pulseKey}></span>
        <span className="freshness-time-compact">{formatTimeAgo(secondsAgo)}</span>
        {isLoading && <span className="freshness-loading-dot"></span>}

        {/* Expandable panel */}
        {isExpanded && (
          <div className="freshness-expanded-panel" onClick={(e) => e.stopPropagation()}>
            <div className="freshness-panel-row">
              <span className="panel-label">Status</span>
              <span className={`panel-value ${statusClass}`}>
                {isStale ? 'STALE' : isWarning ? 'WARNING' : 'FRESH'}
              </span>
            </div>
            <div className="freshness-panel-row">
              <span className="panel-label">Updated</span>
              <span className="panel-value">{formatTimeAgo(secondsAgo)} ago</span>
            </div>
            <div className="freshness-panel-row">
              <span className="panel-label">Source</span>
              <span className={`panel-badge ${sourceDisplay.className}`}>{sourceDisplay.label}</span>
            </div>
            <div className="freshness-panel-row">
              <span className="panel-label">Connection</span>
              <span className={`panel-badge ${wsDisplay.className}`}>
                {wsDisplay.icon}
                {wsDisplay.label}
              </span>
            </div>
            {onRefresh && (
              <button
                className={`freshness-panel-refresh ${isLoading ? 'spinning' : ''}`}
                onClick={(e) => { e.stopPropagation(); onRefresh(); }}
                disabled={isLoading}
              >
                {isLoading ? 'Refreshing...' : '↻ Refresh Now'}
              </button>
            )}
          </div>
        )}
      </div>
    )
  }

  // Floating version - under price with expand
  if (variant === 'floating') {
    return (
      <div className={`freshness-floating ${statusClass} ${isExpanded ? 'expanded' : ''}`}>
        <div
          className="freshness-floating-header"
          onClick={() => setIsExpanded(!isExpanded)}
          aria-expanded={isExpanded}
        >
          <span className={`freshness-dot ${isLoading ? 'loading' : ''}`} role="status" aria-label={`Data ${isStale ? 'stale' : isWarning ? 'warning' : 'fresh'}, updated ${formatTimeAgo(secondsAgo)} ago`} key={pulseKey}></span>
          <span className={`freshness-source-badge ${sourceDisplay.className}`}>{sourceDisplay.label}</span>
          <span className="freshness-time-inline">{formatTimeAgo(secondsAgo)}</span>
          <span className={`freshness-ws-badge ${wsDisplay.className}`}>
            {wsDisplay.icon}
            {wsDisplay.label}
          </span>
          {onRefresh && (
            <button
              className={`freshness-refresh-btn ${isLoading ? 'spinning' : ''}`}
              onClick={(e) => { e.stopPropagation(); onRefresh(); }}
              disabled={isLoading}
              title="Refresh"
              aria-label="Refresh data"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
              </svg>
            </button>
          )}
          {onFitAll && (
            <button
              className="freshness-action-btn"
              onClick={(e) => { e.stopPropagation(); onFitAll(); }}
              title="Fit All"
              aria-label="Fit all chart data"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
              </svg>
            </button>
          )}
          {onGoLive && (
            <button
              className="freshness-action-btn"
              onClick={(e) => { e.stopPropagation(); onGoLive(); }}
              title="Go Live"
              aria-label="Scroll to live data"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                <polygon points="5 3 19 12 5 21 5 3" />
              </svg>
            </button>
          )}
        </div>

        {isExpanded && (
          <div className="freshness-floating-details">
            <div className="detail-row">
              <span>Last Update</span>
              <span>{lastUpdate ? lastUpdate.toLocaleTimeString() : 'Never'}</span>
            </div>
            <div className="detail-row">
              <span>Data Age</span>
              <span className={statusClass}>{secondsAgo}s</span>
            </div>
            <div className="detail-row">
              <span>Stale After</span>
              <span>{staleThresholdSeconds}s</span>
            </div>
            <div className="detail-row">
              <span>WebSocket</span>
              <span className={wsDisplay.className}>{wsStatus}</span>
            </div>
          </div>
        )}
      </div>
    )
  }

  // Full version (original)
  return (
    <div className={`data-freshness-indicator ${statusClass}`}>
      <div className="freshness-heartbeat" key={pulseKey}>
        <span className={`heartbeat-dot ${isLoading ? 'loading' : ''}`}></span>
      </div>
      <div className="freshness-time">
        <span className="time-label">Updated</span>
        <span className={`time-value ${statusClass}`}>
          {lastUpdate ? formatTimeAgo(secondsAgo) : 'never'}
        </span>
      </div>
      <div className={`freshness-source ${sourceDisplay.className}`}>
        {sourceDisplay.label}
      </div>
      <div className={`freshness-ws ${wsDisplay.className}`} title={`WebSocket: ${wsStatus}`}>
        {wsDisplay.icon}
        <span className="ws-label">{wsDisplay.label}</span>
      </div>
      {onRefresh && (
        <button
          className={`freshness-refresh ${isLoading ? 'spinning' : ''}`}
          onClick={onRefresh}
          disabled={isLoading}
          title="Force refresh"
          aria-label="Force refresh data"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
        </button>
      )}
      {isLoading && (
        <div className="freshness-loading-overlay">
          <div className="loading-spinner"></div>
        </div>
      )}
    </div>
  )
}
