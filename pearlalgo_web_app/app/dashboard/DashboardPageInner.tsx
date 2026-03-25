'use client'

import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import Image from 'next/image'
import CandlestickChart from '@/components/CandlestickChart'
import RSIPane from '@/components/RSIPane'
import TradeDockPanel, { type RecentTradeRow, type PerformanceSummary, type RecentSignalEvent } from '@/components/TradeDockPanel'
import DashboardLayout from '@/components/DashboardLayout'
import DataFreshnessIndicator from '@/components/DataFreshnessIndicator'
import WatchlistPanel from '@/components/WatchlistPanel'
import SystemLogsPanel from '@/components/SystemLogsPanel'
import ActivityLogPanel from '@/components/ActivityLogPanel'
import { useWebSocket, getWebSocketUrl } from '@/hooks/useWebSocket'
import { useDashboardData } from '@/hooks/useDashboardData'
import { useAIStatus } from '@/hooks/useAIStatus'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { formatTimeFromDate, formatRelativeTime, formatMarketCountdown } from '@/lib/formatters'
import type { IChartApi } from 'lightweight-charts'

import {
  useAgentStore,
  useChartStore,
  useUIStore,
  useChartSettingsStore,
  type Timeframe,
  type Position,
  type PositionLine,
} from '@/stores'

const MIN_BARS = 500

export default function DashboardPageInner() {
  // Agent store
  const agentState = useAgentStore((s) => s.agentState)
  const setAgentState = useAgentStore((s) => s.setAgentState)
  const updateFromWebSocket = useAgentStore((s) => s.updateFromWebSocket)

  // Chart store
  const candles = useChartStore((s) => s.candles)
  const indicators = useChartStore((s) => s.indicators)
  const markers = useChartStore((s) => s.markers)
  const marketStatus = useChartStore((s) => s.marketStatus)
  const timeframe = useChartStore((s) => s.timeframe)
  const barCount = useChartStore((s) => s.barCount)
  const barSpacing = useChartStore((s) => s.barSpacing)
  const chartLoading = useChartStore((s) => s.isLoading)
  const chartError = useChartStore((s) => s.error)
  const setCandles = useChartStore((s) => s.setCandles)
  const setIndicators = useChartStore((s) => s.setIndicators)
  const setMarkers = useChartStore((s) => s.setMarkers)
  const setMarketStatus = useChartStore((s) => s.setMarketStatus)
  const setTimeframe = useChartStore((s) => s.setTimeframe)
  const setBarCount = useChartStore((s) => s.setBarCount)
  const setBarSpacing = useChartStore((s) => s.setBarSpacing)
  const setChartLoading = useChartStore((s) => s.setLoading)
  const setChartError = useChartStore((s) => s.setError)

  // UI store
  const wsStatus = useUIStore((s) => s.wsStatus)
  const isLive = useUIStore((s) => s.isLive)
  const lastUpdate = useUIStore((s) => s.lastUpdate)
  const dataSource = useUIStore((s) => s.dataSource)
  const isFetching = useUIStore((s) => s.isFetching)
  const setWsStatus = useUIStore((s) => s.setWsStatus)
  const setIsLive = useUIStore((s) => s.setIsLive)
  const setLastUpdate = useUIStore((s) => s.setLastUpdate)
  const setIsFetching = useUIStore((s) => s.setIsFetching)
  const recordFetch = useUIStore((s) => s.recordFetch)
  const activeRightPanel = useUIStore((s) => s.activeRightPanel)
  const toggleRightPanel = useUIStore((s) => s.toggleRightPanel)
  const setActiveRightPanel = useUIStore((s) => s.setActiveRightPanel)

  // Local state for chart API reference (not suitable for global store)
  const [mainChartApi, setMainChartApi] = useState<IChartApi | null>(null)

  // Badge tooltip state (which badge explanation is showing)
  const [badgeTip, setBadgeTip] = useState<string | null>(null)

  // Indicators dropdown state
  const [showIndicatorsDropdown, setShowIndicatorsDropdown] = useState(false)
  const indicatorSettings = useChartSettingsStore((s) => s.indicators)
  const toggleIndicator = useChartSettingsStore((s) => s.toggleIndicator)

  // Close indicators dropdown on outside click
  useEffect(() => {
    if (!showIndicatorsDropdown) return
    const close = () => setShowIndicatorsDropdown(false)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [showIndicatorsDropdown])

  // ── AGENT OFFLINE grace period (15 s) ───────────────────────────────────────
  // Avoid flashing "AGENT OFFLINE" on brief WS reconnects.
  const offlineSinceRef = useRef<number | null>(null)
  const [showOffline, setShowOffline] = useState(false)

  useEffect(() => {
    const isReallyOffline = (() => {
      // WS must be disconnected
      if (wsStatus === 'connected') return false
      // And agent must report not-running OR data must be stale (>30 s)
      if (agentState?.running === false) return true
      const lastUp = useAgentStore.getState().lastUpdated
      if (lastUp && Date.now() - lastUp.getTime() > 30_000) return true
      return false
    })()

    if (!isReallyOffline) {
      offlineSinceRef.current = null
      setShowOffline(false)
      return
    }

    // Start tracking when the offline condition began
    if (offlineSinceRef.current === null) offlineSinceRef.current = Date.now()

    // If already past 15 s, show immediately
    if (Date.now() - offlineSinceRef.current >= 15_000) {
      setShowOffline(true)
      return
    }

    // Otherwise wait for the remaining time
    const remaining = 15_000 - (Date.now() - offlineSinceRef.current)
    const timer = setTimeout(() => setShowOffline(true), remaining)
    return () => clearTimeout(timer)
  }, [wsStatus, agentState?.running, lastUpdate])
  const [isCompactHeader, setIsCompactHeader] = useState(false)

  // Local state for active positions (for chart price lines) - updated from HTTP + WebSocket
  const [positions, setPositions] = useState<Position[]>([])
  const [recentTrades, setRecentTrades] = useState<RecentTradeRow[]>([])
  const [recentSignals, setRecentSignals] = useState<RecentSignalEvent[]>([])
  const [performanceSummary, setPerformanceSummary] = useState<PerformanceSummary | null>(null)

  // Dashboard data hook - handles HTTP fetching with in-flight guard
  const dashboardData = useDashboardData({
    timeframe,
    barCount,
    wsStatus,
  })

  // Merge dashboard data from hook into local state (HTTP fetch results)
  useEffect(() => {
    if (dashboardData.positions.length > 0 || positions.length === 0) {
      setPositions(dashboardData.positions)
    }
    if (dashboardData.recentTrades.length > 0 || recentTrades.length === 0) {
      setRecentTrades(dashboardData.recentTrades)
    }
    if (dashboardData.recentSignals.length > 0 || recentSignals.length === 0) {
      setRecentSignals(dashboardData.recentSignals)
    }
    if (dashboardData.performanceSummary !== null) {
      setPerformanceSummary(dashboardData.performanceSummary)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally merge only from fetch, avoid overwriting with stale local state
  }, [dashboardData.positions, dashboardData.recentTrades, dashboardData.recentSignals, dashboardData.performanceSummary])

  // Convert positions to price lines for chart visualization (more visible than live price)
  const positionLines = useMemo<PositionLine[]>(() => {
    const lines: PositionLine[] = []
    const seenPrices = new Set<string>()
    const addLine = (line: PositionLine) => {
      const key = Number(line.price).toFixed(2)
      if (seenPrices.has(key)) return
      seenPrices.add(key)
      lines.push(line)
    }

    positions.forEach((pos) => {
      // Entry price line - blue/purple, more visible
      addLine({
        price: pos.entry_price,
        // Slightly lighter (less busy) but still readable
        color: pos.direction === 'long' ? 'rgba(33, 150, 243, 0.55)' : 'rgba(156, 39, 176, 0.55)',
        title: '',
        kind: 'entry',
        lineWidth: 2,
        lineStyle: 0, // solid
        axisLabelVisible: true,
      })

      // Stop loss line - red, more visible
      if (pos.stop_loss) {
        addLine({
          price: pos.stop_loss,
          color: 'rgba(244, 67, 54, 0.62)',
          title: '',
          kind: 'sl',
          lineWidth: 2,
          lineStyle: 2, // dashed
          axisLabelVisible: true,
        })
      }

      // Take profit line - green, more visible
      if (pos.take_profit) {
        addLine({
          price: pos.take_profit,
          color: 'rgba(76, 175, 80, 0.62)',
          title: '',
          kind: 'tp',
          lineWidth: 2,
          lineStyle: 2, // dashed
          axisLabelVisible: true,
        })
      }
    })

    // Fallback/augment from broker working orders so protective levels can still
    // appear on chart when signal-derived TP/SL enrichment is delayed.
    const workingOrders = agentState?.tradovate_account?.working_orders || []
    workingOrders.forEach((o) => {
      const level = o?.stop_price ?? o?.price
      if (typeof level !== 'number' || !Number.isFinite(level) || level <= 0) return
      const orderType = String(o?.order_type || '').toLowerCase()
      const isStop = o?.stop_price != null || orderType.includes('stop')
      addLine({
        price: level,
        color: isStop ? 'rgba(244, 67, 54, 0.5)' : 'rgba(76, 175, 80, 0.5)',
        title: '',
        kind: isStop ? 'sl' : 'tp',
        lineWidth: 2,
        lineStyle: 2,
        axisLabelVisible: true,
      })
    })

    return lines
  }, [positions, agentState?.tradovate_account?.working_orders])

  // WebSocket connection for real-time updates
  useWebSocket({
    url: getWebSocketUrl(),
    reconnect: true,
    reconnectInterval: 3000,
    maxReconnectAttempts: 10,
    pingInterval: 30000,
    onStatusChange: (status) => {
      setWsStatus(status)
      // Set isLive=false on disconnect or error so the UI reflects reality
      if (status === 'disconnected' || status === 'error') {
        setIsLive(false)
      }
    },
    onMessage: (message) => {
      if (message.type === 'initial_state' || message.type === 'state_update' || message.type === 'full_refresh') {
        const data = message.data
        if (data) {
          updateFromWebSocket(data)
          setLastUpdate(new Date())
          setIsLive(true)

          // Consume positions, trades, and performance summary from WS
          // (previously HTTP-only, now included in broadcast for ~2s latency)
          if (data.positions !== undefined) {
            setPositions(Array.isArray(data.positions) ? data.positions : [])
          }
          if (data.recent_trades !== undefined) {
            setRecentTrades(Array.isArray(data.recent_trades) ? data.recent_trades : [])
          }
          if (data.performance_summary !== undefined) {
            setPerformanceSummary(data.performance_summary || null)
          }
        }
      }
    },
  })

  // Responsive bar spacing - smaller on mobile
  const getBarSpacing = useCallback(() => {
    if (typeof window === 'undefined') return 10
    return window.innerWidth < 768 ? 6 : 10
  }, [])

  // Calculate bar count based on viewport width - always request enough to fill chart
  const calculateBarCount = useCallback(() => {
    if (typeof window === 'undefined') return MIN_BARS
    const width = window.innerWidth
    const spacing = getBarSpacing()
    const priceScaleWidth = 60
    const availableWidth = width - priceScaleWidth - 40
    const visibleBars = Math.floor(availableWidth / spacing)
    // Request 50% more bars than visible to allow scrolling, with minimum
    return Math.max(MIN_BARS, Math.floor(visibleBars * 1.5))
  }, [getBarSpacing])

  // Update bar count and spacing on resize
  useEffect(() => {
    const update = () => {
      setBarSpacing(getBarSpacing())
      setBarCount(calculateBarCount())
      setIsCompactHeader(window.innerWidth <= 480)
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [getBarSpacing, calculateBarCount, setBarSpacing, setBarCount])

  // Callback for TradeDockPanel to trigger an immediate refetch after close actions
  const handleTradeRefresh = useCallback(() => {
    dashboardData.handleTradeRefresh()
  }, [dashboardData])

  const formatTime = formatTimeFromDate
  const formatRelativeTimeFromDate = (date: Date | null) => {
    if (!date) return 'Never'
    return formatRelativeTime(date)
  }
  const formatMarketCountdownFromStatus = () => {
    if (!marketStatus?.next_open) return null
    return formatMarketCountdown(marketStatus.next_open)
  }

  // Use useAIStatus hook instead of inline logic
  const aiStatus = useAIStatus(agentState?.ai_status)
  const getAgentModeBadge = () => aiStatus.badge

  const getRegimeBadge = () => {
    if (!agentState?.market_regime) return null
    const regime = agentState.market_regime
    if (regime.confidence === 0 || regime.regime === 'unknown') return null

    const icons: Record<string, string> = {
      'trending_up': '📈',
      'trending_down': '📉',
      'ranging': '↔️',
      'volatile': '⚡',
    }
    return {
      icon: icons[regime.regime] || '❓',
      label: regime.regime.replace('_', ' ').toUpperCase(),
      confidence: Math.round(regime.confidence * 100)
    }
  }

  // Stale threshold reduced to 60 seconds for better responsiveness
  const STALE_THRESHOLD_SECONDS = 60

  const isDataStale = () => {
    if (!lastUpdate) return true
    const seconds = Math.floor((Date.now() - lastUpdate.getTime()) / 1000)
    return seconds > STALE_THRESHOLD_SECONDS
  }

  // Force refresh function for manual refresh button
  const handleForceRefresh = useCallback(() => {
    dashboardData.handleTradeRefresh()
  }, [dashboardData])

  // Pull-to-refresh (mobile touch) - uses window scroll position
  const pullStartY = useRef(0)
  const pullActive = useRef(false)
  const pullDistanceRef = useRef(0)
  const [pullDistance, setPullDistance] = useState(0)
  const [pullRefreshing, setPullRefreshing] = useState(false)
  const PULL_THRESHOLD = 70

  // Keep ref in sync with state for use in touchend
  useEffect(() => { pullDistanceRef.current = pullDistance }, [pullDistance])

  useEffect(() => {
    let refreshingRef = false

    const onTouchStart = (e: TouchEvent) => {
      if (refreshingRef) return
      // Check both window scroll and document scroll (cross-browser)
      const scrollTop = window.scrollY || document.documentElement.scrollTop || 0
      if (scrollTop <= 5) {
        pullStartY.current = e.touches[0].clientY
        pullActive.current = false
      } else {
        pullStartY.current = 0
      }
    }

    const onTouchMove = (e: TouchEvent) => {
      if (pullStartY.current === 0 || refreshingRef) return
      const scrollTop = window.scrollY || document.documentElement.scrollTop || 0
      const diff = e.touches[0].clientY - pullStartY.current

      if (diff > 10 && scrollTop <= 5) {
        // Pulling down from top - activate
        pullActive.current = true
        e.preventDefault()
        const distance = Math.min(diff * 0.4, 100)
        setPullDistance(distance)
      } else if (diff < -5 && !pullActive.current) {
        // Scrolling up - cancel pull tracking
        pullStartY.current = 0
      }
    }

    const onTouchEnd = () => {
      if (!pullActive.current || refreshingRef) {
        if (!refreshingRef) setPullDistance(0)
        pullStartY.current = 0
        pullActive.current = false
        return
      }

      if (pullDistanceRef.current >= PULL_THRESHOLD * 0.4) {
        refreshingRef = true
        setPullRefreshing(true)
        setPullDistance(40)
        dashboardData.handleTradeRefresh()
        // Brief visual feedback before clearing pull state
        setTimeout(() => {
          refreshingRef = false
          setPullRefreshing(false)
          setPullDistance(0)
        }, 800)
      } else {
        setPullDistance(0)
      }
      pullStartY.current = 0
      pullActive.current = false
    }

    // Cancel pull if user scrolls via momentum after lifting finger
    const onScroll = () => {
      if (pullActive.current && !refreshingRef) {
        pullActive.current = false
        setPullDistance(0)
      }
    }

    document.addEventListener('touchstart', onTouchStart, { passive: true })
    document.addEventListener('touchmove', onTouchMove, { passive: false })
    document.addEventListener('touchend', onTouchEnd, { passive: true })
    document.addEventListener('touchcancel', onTouchEnd, { passive: true })
    window.addEventListener('scroll', onScroll, { passive: true })

    return () => {
      document.removeEventListener('touchstart', onTouchStart)
      document.removeEventListener('touchmove', onTouchMove)
      document.removeEventListener('touchend', onTouchEnd)
      document.removeEventListener('touchcancel', onTouchEnd)
      window.removeEventListener('scroll', onScroll)
    }
  }, [dashboardData])

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  // Track if chart is fully loaded (for screenshot detection)
  const isChartReady = !chartLoading && !chartError && candles.length > 0

  // Format next market open time
  const formatNextOpen = (isoString: string | null) => {
    if (!isoString) return ''
    try {
      const date = new Date(isoString)
      return date.toLocaleString('en-US', {
        weekday: 'short',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
        hour12: true,
        timeZone: 'America/New_York',
        timeZoneName: 'short',
      })
    } catch {
      return ''
    }
  }

  // getAIMode is replaced by aiStatus.aiMode from useAIStatus hook

  // Combined header - single row: timeframes left, status badges right
  const renderHeader = () => {
    const aiMode = aiStatus.aiMode

    return (
      <header className="header-combined">
        <div className="header-row-single">
          {/* Left: Timeframe buttons */}
          <div className="header-timeframe">
            {(['1m', '5m', '15m', '30m', '1h', '4h', '1D'] as Timeframe[]).map((tf) => (
              <button
                key={tf}
                className={`tf-btn ${timeframe === tf ? 'active' : ''}`}
                onClick={() => setTimeframe(tf)}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Center: Action buttons */}
          <div className="header-actions">
            {/* Indicators toggle */}
            <div style={{ position: 'relative' }}>
              <button
                className="header-action-btn"
                title="Indicators"
                onClick={() => setShowIndicatorsDropdown((v) => !v)}
              >
                <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="1,12 4,4 8,10 12,2 15,8" />
                </svg>
              </button>
              {showIndicatorsDropdown && (
                <div className="indicators-dropdown" onClick={(e) => e.stopPropagation()}>
                  <div className="indicators-section-header">Overlays</div>
                  {([
                    { key: 'ema9' as const, label: 'EMA Crossover', color: '#00d4ff' },
                    { key: 'vwap' as const, label: 'VWAP', color: 'rgba(100,181,246,0.85)' },
                    { key: 'vwapBands' as const, label: 'VWAP Bands', color: 'rgba(76,175,80,0.5)' },
                    { key: 'keyLevels' as const, label: 'Key Levels', color: '#08bcd4' },
                    { key: 'sessions' as const, label: 'Sessions', color: 'rgba(8,153,129,0.5)' },
                    { key: 'sdZones' as const, label: 'S/D Zones', color: 'rgba(255,193,7,0.4)' },
                    { key: 'tbtTrendlines' as const, label: 'TBT Trendlines', color: '#ff9800' },
                    { key: 'bollingerBands' as const, label: 'Bollinger Bands', color: 'rgba(41,98,255,0.7)' },
                    { key: 'atrBands' as const, label: 'ATR Bands', color: 'rgba(255,152,0,0.5)' },
                    { key: 'srPowerZones' as const, label: 'S&R Power', color: '#ab47bc' },
                  ]).map(({ key, label, color }) => (
                    <div key={key} className="indicator-toggle-item" onClick={() => {
                      if (key === 'ema9') { toggleIndicator('ema9'); toggleIndicator('ema21') }
                      else { toggleIndicator(key) }
                    }}>
                      <span className="indicator-color-dot" style={{ background: color }} />
                      <span>{label}</span>
                      <span className={`indicator-dot ${indicatorSettings[key] ? 'active' : ''}`} />
                    </div>
                  ))}
                  <div className="indicators-section-header">Panes</div>
                  {([
                    { key: 'rsi' as const, label: 'RSI (14)', color: '#7c4dff' },
                    { key: 'volume' as const, label: 'Volume', color: '#26a69a' },
                  ]).map(({ key, label, color }) => (
                    <div key={key} className="indicator-toggle-item" onClick={() => toggleIndicator(key)}>
                      <span className="indicator-color-dot" style={{ background: color }} />
                      <span>{label}</span>
                      <span className={`indicator-dot ${indicatorSettings[key] ? 'active' : ''}`} />
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Fullscreen */}
            <button
              className="header-action-btn"
              title="Fullscreen"
              onClick={() => {
                if (document.fullscreenElement) {
                  document.exitFullscreen()
                } else {
                  document.documentElement.requestFullscreen()
                }
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="1,5 1,1 5,1" /><polyline points="11,1 15,1 15,5" /><polyline points="15,11 15,15 11,15" /><polyline points="5,15 1,15 1,11" />
              </svg>
            </button>

            {/* Screenshot */}
            <button
              className="header-action-btn"
              title="Screenshot"
              onClick={() => {
                if (mainChartApi) {
                  mainChartApi.takeScreenshot()
                }
              }}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <rect x="1" y="3" width="14" height="11" rx="2" /><circle cx="8" cy="9" r="3" /><path d="M5 3L6 1h4l1 2" />
              </svg>
            </button>
          </div>

          {/* Right: Status badges */}
          <div className="header-badges">
            {/* System status badges - tap for explanation */}
            {agentState && (
              <span
                className={`badge agent-badge ${agentState.running ? (agentState.paused ? 'paused' : 'running') : 'stopped'}`}
                role="button" tabIndex={0}
                title="Agent — Trading scanner process status"
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'agent' ? null : 'agent') }}
              >
                <span className="badge-dot"></span>
                {agentState.running
                  ? (agentState.paused ? (isCompactHeader ? 'PAUSE' : 'PAUSED') : (isCompactHeader ? 'RUN' : 'RUNNING'))
                  : (isCompactHeader ? 'STOP' : 'STOPPED')}
              </span>
            )}
            {agentState && (
              <span
                className={`badge gw-badge ${agentState.gateway_status?.status === 'online' ? 'ok' : 'error'}`}
                role="button" tabIndex={0}
                title="Gateway — IBKR connection status"
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'gw' ? null : 'gw') }}
              >
                <span className="badge-dot"></span>
                GW
              </span>
            )}
            {aiStatus.aiMode && (
              <span
                className={`badge ai-badge ${aiStatus.aiMode}`}
                role="button" tabIndex={0}
                title="AI/ML — Signal filtering mode"
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'ai' ? null : 'ai') }}
              >
                {isCompactHeader && aiStatus.aiMode === 'shadow'
                  ? 'SHDW'
                  : aiStatus.aiMode.toUpperCase()}
                {agentState?.shadow_counters && agentState.shadow_counters.would_block_total > 0 && (
                  <span className="badge-shadow-count">{agentState.shadow_counters.would_block_total}</span>
                )}
              </span>
            )}
            {marketStatus && (
              <span
                className={`badge market-badge ${marketStatus.is_open ? 'open' : 'closed'}`}
                role="button" tabIndex={0}
                title="Market — CME Futures session status"
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'market' ? null : 'market') }}
              >
                {isCompactHeader ? (marketStatus.is_open ? 'OPN' : 'CLS') : (marketStatus.is_open ? 'OPEN' : 'CLOSED')}
              </span>
            )}
            {agentState && (
              <span
                className={`badge data-badge ${agentState.data_fresh ? 'ok' : 'stale'}`}
                role="button" tabIndex={0}
                title="Data — Market data feed freshness"
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'data' ? null : 'data') }}
              >
                <span className="badge-dot"></span>
                {isCompactHeader ? 'DATA' : 'Data'}
              </span>
            )}
            {agentState?.ml_filter_performance?.lift_ok && agentState.ml_filter_performance.win_rate_pass != null && (
              <span
                className={`badge ml-badge ${(agentState.ml_filter_performance.lift_win_rate || 0) > 0.1 ? 'good' : 'neutral'}`}
                role="button" tabIndex={0}
                title="ML Filter — Win rate when ML passes signal"
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'ml' ? null : 'ml') }}
              >
                ML {Math.round((agentState.ml_filter_performance.win_rate_pass) * 100)}%
              </span>
            )}
            {agentState?.shadow_counters && (agentState.shadow_counters.blocked_total > 0) && (
              <span
                className={`badge saved-badge ${(agentState.shadow_counters.net_saved || 0) >= 0 ? 'positive' : 'negative'}`}
                role="button" tabIndex={0}
                title="Shadow Savings — Net P&L impact of blocked signals"
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'saved' ? null : 'saved') }}
              >
                {(agentState.shadow_counters.net_saved || 0) >= 0 ? '↑' : '↓'}${Math.abs(agentState.shadow_counters.net_saved || 0).toFixed(0)}
              </span>
            )}
          </div>
          {/* Badge explanation tooltip */}
          {badgeTip && (
            <div className="badge-tooltip" onClick={() => setBadgeTip(null)}>
              {badgeTip === 'agent' && (
                <p><strong>Agent</strong> — Trading scanner process. {agentState?.running ? 'Running and scanning for signals every cycle.' : 'Stopped. No signals are being generated.'}{agentState?.paused ? ' Currently paused due to circuit breaker or manual pause.' : ''}</p>
              )}
              {badgeTip === 'gw' && (
                <p><strong>Gateway</strong> — IBKR Gateway connection. {agentState?.gateway_status?.status === 'online' ? `Online on port ${agentState.gateway_status.port}. Market data and execution available.` : 'Offline. No market data or execution. Check Gateway process.'}</p>
              )}
              {badgeTip === 'ai' && (() => {
                const ai = agentState?.ai_status
                const sc = agentState?.shadow_counters
                return (
                  <p><strong>AI/ML — {aiMode?.toUpperCase()}</strong> — {aiMode === 'shadow' ? 'Observing and scoring signals without blocking. ' : aiMode === 'live' ? 'Actively filtering signals. ' : 'AI systems disabled. '}
                    {ai && <>Bandit: {ai.bandit_mode}, Ctx: {ai.contextual_mode}, Filter: {ai.ml_filter?.mode || 'off'}. </>}
                    {sc && sc.would_block_total > 0 && <>{sc.would_block_total} signals would have been blocked if enforced.</>}
                  </p>
                )
              })()}
              {badgeTip === 'market' && (
                <p><strong>Market</strong> — CME Futures session. {marketStatus?.is_open ? 'Market is open. Real-time data flowing.' : `Market closed${marketStatus?.close_reason ? ` (${marketStatus.close_reason})` : ''}. Historical data only.`}</p>
              )}
              {badgeTip === 'data' && (
                <p><strong>Data Feed</strong> — {agentState?.data_fresh ? 'Fresh. Latest bar is recent and buffer has enough bars for indicators.' : 'Stale. Data may be delayed or unavailable. Check IBKR connection.'}</p>
              )}
              {badgeTip === 'ml' && (() => {
                const ml = agentState?.ml_filter_performance
                return (
                  <p><strong>ML Filter</strong> — Win rate when ML says PASS: {ml?.win_rate_pass != null ? `${Math.round(ml.win_rate_pass * 100)}%` : 'N/A'} vs FAIL: {ml?.win_rate_fail != null ? `${Math.round(ml.win_rate_fail * 100)}%` : 'N/A'}. Lift: {ml?.lift_win_rate != null ? `+${Math.round(ml.lift_win_rate * 100)}%` : 'N/A'}. Based on {ml?.trades_passed || 0} PASS / {ml?.trades_blocked || 0} FAIL trades scored.</p>
                )
              })()}
              {badgeTip === 'saved' && (() => {
                const sc = agentState?.shadow_counters
                const net = sc?.net_saved || 0
                return (
                  <p><strong>Shadow Savings</strong> — {net >= 0 ? `Would save $${net.toFixed(0)}` : `Would cost $${Math.abs(net).toFixed(0)}`} if circuit breaker was in enforce mode. Blocked signals: {sc?.blocked_total || 0} ({sc?.blocked_wins || 0}W / {sc?.blocked_losses || 0}L = ${(sc?.blocked_pnl || 0).toFixed(0)}). Allowed signals: {sc?.allowed_total || 0} ({sc?.allowed_wins || 0}W / {sc?.allowed_losses || 0}L = ${(sc?.allowed_pnl || 0).toFixed(0)}).</p>
                )
              })()}
            </div>
          )}
        </div>
      </header>
    )
  }

  // Chart section component
  const renderChart = () => (
    <div className="chart-wrapper">
      {/* Agent/Execution offline banner (15 s grace period for OFFLINE) */}
      {agentState && (showOffline || agentState.execution_state?.enabled === false) && (
        <div className="agent-offline-banner">
          <span className="agent-offline-title">
            {showOffline && agentState.running === false ? 'AGENT OFFLINE' : showOffline ? 'DATA STALE' : 'EXECUTION DISABLED'}
          </span>
          <span className="agent-offline-message">
            {showOffline && agentState.running === false
              ? 'The trading agent is not running. Data may be stale.'
              : showOffline
              ? 'No updates received for >30 s. Connection may be lost.'
              : 'Execution is disabled. Orders will not be placed.'}
          </span>
        </div>
      )}
      <div className="chart-container" role="img" aria-label="MNQ candlestick price chart with indicators">
        <div className="chart-actions">
          {/* Data Freshness Indicator with chart action buttons */}
          <DataFreshnessIndicator
            lastUpdate={lastUpdate}
            wsStatus={wsStatus}
            dataSource={dataSource}
            isLoading={isFetching}
            staleThresholdSeconds={STALE_THRESHOLD_SECONDS}
            onRefresh={handleForceRefresh}
            onFitAll={() => {
              if (mainChartApi && candles.length > 0) {
                // Zoom to show last ~100 bars for a readable view
                const visibleBars = Math.min(100, candles.length)
                if (candles.length > visibleBars) {
                  const fromTime = candles[candles.length - visibleBars].time as unknown as import('lightweight-charts').Time
                  const toTime = candles[candles.length - 1].time as unknown as import('lightweight-charts').Time
                  mainChartApi.timeScale().setVisibleRange({ from: fromTime, to: toTime })
                } else {
                  mainChartApi.timeScale().fitContent()
                }
                mainChartApi.timeScale().scrollToRealTime()
              }
            }}
            onGoLive={() => mainChartApi?.timeScale().scrollToRealTime()}
            variant="floating"
          />
        </div>
        {chartLoading && (
          <div className="loading-screen">
            <Image src="/pearl-emoji.png" alt="PEARL" className="loading-logo" width={64} height={64} priority />
            <div className="loading-text">Loading Live Data...</div>
            <div className="loading-spinner"></div>
          </div>
        )}
        {chartError && !chartLoading && (
          <div className="no-data-container">
            <Image src="/pearl-emoji.png" alt="PEARL" className="no-data-logo" width={64} height={64} />
            <div className="no-data-title">No Live Data</div>
            <div className="no-data-message">{chartError}</div>
            <div className="no-data-hint">
              Start the Market Agent to see real-time data
            </div>
          </div>
        )}
        {!chartLoading && !chartError && candles.length > 0 && (
          <ErrorBoundary
            panelName="Chart"
            fallback={
              <div className="chart-error-fallback">
                <div className="error-boundary-icon">⚠️</div>
                <div className="error-boundary-title">Chart Error</div>
                <div className="error-boundary-message">Failed to render chart</div>
                <button className="error-boundary-retry" onClick={() => window.location.reload()}>
                  Reload Page
                </button>
              </div>
            }
          >
            <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100%' }}>
              <div style={{ flex: 1, minHeight: 0 }}>
                <CandlestickChart
                  data={candles}
                  indicators={indicators}
                  markers={markers}
                  barSpacing={barSpacing}
                  timeframe={timeframe}
                  onChartReady={setMainChartApi}
                  positionLines={positionLines}
                />
              </div>
              {indicatorSettings.rsi && (
                <RSIPane
                  rsiData={indicators?.rsi}
                  mainChart={mainChartApi}
                  barSpacing={barSpacing}
                />
              )}
            </div>
          </ErrorBoundary>
        )}
      </div>
    </div>
  )

  // Right panel content based on active tab
  const renderRightPanelContent = () => {
    if (activeRightPanel === 'watchlist') {
      const lastCandle = candles.length > 0 ? candles[candles.length - 1] : null
      const prevCandle = candles.length > 1 ? candles[candles.length - 2] : null
      const currentPrice = lastCandle?.close
      const priceChange = lastCandle && prevCandle ? lastCandle.close - prevCandle.close : 0
      const priceChangePercent = prevCandle && prevCandle.close !== 0 ? (priceChange / prevCandle.close) * 100 : 0
      return (
        <WatchlistPanel
          symbol={agentState?.config?.symbol || 'MNQ'}
          currentPrice={currentPrice}
          priceChange={priceChange}
          priceChangePercent={priceChangePercent}
          dailyPnL={agentState?.daily_pnl ?? 0}
          dailyWins={agentState?.daily_wins ?? 0}
          dailyLosses={agentState?.daily_losses ?? 0}
          recentSignals={recentSignals}
        />
      )
    }
    if (activeRightPanel === 'logs') {
      return (
        <SystemLogsPanel
          recentSignals={recentSignals}
          pearlFeed={agentState?.pearl_feed || []}
          signalRejections={agentState?.signal_rejections_24h || null}
          lastSignalDecision={agentState?.last_signal_decision || null}
          agentState={agentState}
        />
      )
    }
    if (activeRightPanel === 'activity') {
      return <ActivityLogPanel recentSignals={recentSignals} />
    }
    return null
  }

  // Standard layout (all viewports)
  return (
    <DashboardLayout
        isChartReady={isChartReady}
        pull={{ pullDistance, pullRefreshing, pullThreshold: PULL_THRESHOLD }}
        header={renderHeader()}
        chart={renderChart()}
        activeRightPanel={activeRightPanel}
        onToggleRightPanel={toggleRightPanel}
        onCloseRightPanel={() => setActiveRightPanel(null)}
        rightPanelContent={renderRightPanelContent()}
        panels={
          <>
            <ErrorBoundary panelName="Trades">
              <TradeDockPanel
                positions={positions}
                recentTrades={recentTrades}
                symbol={agentState?.config?.symbol || 'MNQ'}
                currentPrice={candles.length > 0 ? candles[candles.length - 1].close : undefined}
                openUnrealizedPnL={agentState?.active_trades_unrealized_pnl ?? null}
                performanceSummary={performanceSummary}
                directionBreakdown={agentState?.analytics?.direction_breakdown || null}
                statusBreakdown={agentState?.analytics?.status_breakdown || null}
                maxOpenRows={6}
                maxRecentRows={10}
                dailyPnL={agentState?.daily_pnl}
                dailyWins={agentState?.daily_wins}
                dailyLosses={agentState?.daily_losses}
                activeTradesCount={agentState?.active_trades_count}
                onRefresh={handleTradeRefresh}
                riskMetrics={agentState?.risk_metrics || null}
                signalRejections={agentState?.signal_rejections_24h || null}
                lastSignalDecision={agentState?.last_signal_decision || null}
                recentSignals={recentSignals}
                workingOrders={agentState?.tradovate_account?.working_orders}
                orderStats={agentState?.tradovate_account?.order_stats || null}
                accountEquity={agentState?.tradovate_account?.equity ?? performanceSummary?.all?.tradovate_equity ?? null}
                accountTotalPnl={performanceSummary?.all?.pnl ?? null}
                accountWinRate={performanceSummary?.all?.win_rate ?? null}
              />
            </ErrorBoundary>
          </>
        }
      />
  )
}