'use client'

import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import Image from 'next/image'
import CandlestickChart from '@/components/CandlestickChart'
import ChallengePanel from '@/components/ChallengePanel'
import PearlInsightsPanel from '@/components/PearlInsightsPanel'
import PearlHeaderBar from '@/components/PearlHeaderBar'
import RiskEquityPanel from '@/components/RiskEquityPanel'
import MarketContextPanel from '@/components/MarketContextPanel'
import SystemHealthPanel from '@/components/SystemHealthPanel'
import SignalDecisionsPanel from '@/components/SignalDecisionsPanel'
import AnalyticsPanel from '@/components/AnalyticsPanel'
import SystemStatusPanel from '@/components/SystemStatusPanel'
import TradeDockPanel, { type RecentTradeRow, type PerformanceSummary } from '@/components/TradeDockPanel'
import PostTradesPanels from '@/components/PostTradesPanels'
import UltrawideLayout from '@/components/UltrawideLayout'
import DataFreshnessIndicator from '@/components/DataFreshnessIndicator'
import { useViewportType } from '@/hooks/useViewportType'
import { useWebSocket, getWebSocketUrl } from '@/hooks/useWebSocket'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import AccountSelector, { shouldShowAccountSelector } from '@/components/AccountSelector'
import { getApiUrl, apiFetch } from '@/lib/api'
import type { IChartApi } from 'lightweight-charts'

// Indicator panels
import { VolumeProfilePanel } from '@/components/indicators'

// Import stores and types
import {
  useAgentStore,
  useChartStore,
  useChartSettingsStore,
  useUIStore,
  type Timeframe,
  type IndicatorData,
  type Position,
  type PositionLine,
  type DataSource,
} from '@/stores'

// API configuration imported from @/lib/api
const REFRESH_INTERVAL = 10000 // 10 seconds (fallback when WebSocket disconnected)
const WS_REFRESH_INTERVAL = 30000 // 30 seconds (slower when WebSocket connected)

// Minimum bars to request for a full chart (500 = ~4 days on 5m, ~2 weeks on 1h)
const MIN_BARS = 500

// Fetch 72 hours (3 days) of markers - API limit
const MARKER_HOURS = 72

/**
 * Account selection gate -- shown on first visit when no account is chosen.
 * Wraps the real dashboard so hooks inside PearlAlgoWebApp are never called
 * conditionally (React rules of hooks).
 */
function AccountGate({ children }: { children: React.ReactNode }) {
  const [showPicker, setShowPicker] = useState(false)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    // Show account selector on every clean URL (no ?account= param)
    // Once user picks, the URL gets ?account=mffu and the selector won't show
    if (shouldShowAccountSelector()) {
      setShowPicker(true)
    } else {
      setReady(true)
    }
  }, [])

  if (showPicker) {
    return (
      <AccountSelector
        onSelect={(param) => {
          setShowPicker(false)
          if (param) {
            const url = new URL(window.location.href)
            url.searchParams.set('account', param)
            window.location.href = url.toString()
            return
          }
          setReady(true)
        }}
      />
    )
  }

  if (!ready) return null

  return <>{children}</>
}

export default function PearlAlgoWebAppWrapper() {
  return (
    <AccountGate>
      <PearlAlgoWebAppInner />
    </AccountGate>
  )
}

function PearlAlgoWebAppInner() {
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
  const lastDataHash = useChartStore((s) => s.lastDataHash)
  const setCandles = useChartStore((s) => s.setCandles)
  const setIndicators = useChartStore((s) => s.setIndicators)
  const setMarkers = useChartStore((s) => s.setMarkers)
  const setMarketStatus = useChartStore((s) => s.setMarketStatus)
  const setTimeframe = useChartStore((s) => s.setTimeframe)
  const setBarCount = useChartStore((s) => s.setBarCount)
  const setBarSpacing = useChartStore((s) => s.setBarSpacing)
  const setChartLoading = useChartStore((s) => s.setLoading)
  const setChartError = useChartStore((s) => s.setError)
  const setLastDataHash = useChartStore((s) => s.setLastDataHash)

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

  // Track fetch start time for duration calculation
  const fetchStartRef = useRef<number>(0)

  // Local state for chart API reference (not suitable for global store)
  const [mainChartApi, setMainChartApi] = useState<IChartApi | null>(null)

  // Local state for active positions (for chart price lines)
  const [positions, setPositions] = useState<Position[]>([])
  const [recentTrades, setRecentTrades] = useState<RecentTradeRow[]>([])

  // Badge tooltip state (which badge explanation is showing)
  const [badgeTip, setBadgeTip] = useState<string | null>(null)
  const [performanceSummary, setPerformanceSummary] = useState<PerformanceSummary | null>(null)

  // Convert positions to price lines for chart visualization (more visible than live price)
  const positionLines = useMemo<PositionLine[]>(() => {
    const lines: PositionLine[] = []

    positions.forEach((pos) => {
      // Entry price line - blue/purple, more visible
      lines.push({
        price: pos.entry_price,
        // Slightly lighter (less busy) but still readable
        color: pos.direction === 'long' ? 'rgba(33, 150, 243, 0.42)' : 'rgba(156, 39, 176, 0.42)',
        title: '',
        kind: 'entry',
        lineStyle: 2, // dashed
        axisLabelVisible: true,
      })

      // Stop loss line - red, more visible
      if (pos.stop_loss) {
        lines.push({
          price: pos.stop_loss,
          color: 'rgba(244, 67, 54, 0.42)',
          title: '',
          kind: 'sl',
          lineStyle: 2, // dashed
          axisLabelVisible: true,
        })
      }

      // Take profit line - green, more visible
      if (pos.take_profit) {
        lines.push({
          price: pos.take_profit,
          color: 'rgba(76, 175, 80, 0.42)',
          title: '',
          kind: 'tp',
          lineStyle: 2, // dashed
          axisLabelVisible: true,
        })
      }
    })

    return lines
  }, [positions])

  // Viewport detection for ultrawide layout
  const viewport = useViewportType()

  // WebSocket connection for real-time updates
  useWebSocket({
    url: getWebSocketUrl(),
    reconnect: true,
    reconnectInterval: 3000,
    maxReconnectAttempts: 10,
    pingInterval: 30000,
    onStatusChange: setWsStatus,
    onMessage: (message) => {
      if (message.type === 'initial_state' || message.type === 'state_update' || message.type === 'full_refresh') {
        const data = message.data
        if (data) {
          updateFromWebSocket(data)
          setLastUpdate(new Date())
          setIsLive(true)
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
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [getBarSpacing, calculateBarCount, setBarSpacing, setBarCount])

  const fetchData = useCallback(async (tf: Timeframe, bars: number) => {
    // Track fetch timing and state
    fetchStartRef.current = performance.now()
    setIsFetching(true)

    try {
      // Ensure we always request at least MIN_BARS
      const requestBars = Math.max(MIN_BARS, bars)

      // Fetch all data in parallel (apiFetch includes auth headers when configured)
      const [candlesRes, indicatorsRes, markersRes, stateRes, marketStatusRes, analyticsRes, positionsRes, tradesRes, perfSummaryRes] = await Promise.all([
        apiFetch(`/api/candles?symbol=MNQ&timeframe=${tf}&bars=${requestBars}`),
        apiFetch(`/api/indicators?symbol=MNQ&timeframe=${tf}&bars=${requestBars}`),
        apiFetch(`/api/markers?hours=${MARKER_HOURS}`),
        apiFetch(`/api/state`),
        apiFetch(`/api/market-status`),
        apiFetch(`/api/analytics`).catch(() => null),  // Analytics is optional
        apiFetch(`/api/positions`).catch(() => null),  // Positions for chart lines
        apiFetch(`/api/trades?limit=50`).catch(() => null), // Recent trades for trade dock
        apiFetch(`/api/performance-summary`).catch(() => null), // Common performance timeframes
      ])

      // Update market status
      if (marketStatusRes.ok) {
        const marketData = await marketStatusRes.json()
        setMarketStatus(marketData)
      }

      // Handle 503 (data unavailable) specifically
      if (candlesRes.status === 503) {
        const errorData = await candlesRes.json().catch(() => ({}))
        throw new Error(errorData?.detail?.message || 'No Data — Agent Not Running')
      }

      if (!candlesRes.ok) throw new Error(`API Error: ${candlesRes.status}`)

      const candlesData = await candlesRes.json()
      const indicatorsData = indicatorsRes.ok ? await indicatorsRes.json() : {}
      const markersData = markersRes.ok ? await markersRes.json() : []
      const stateData = stateRes.ok ? await stateRes.json() : null

      // Filter markers to only those within the candle time range
      // This prevents markers from appearing at the edge when they're outside visible range
      let filteredMarkers = markersData
      if (candlesData.length > 0 && markersData.length > 0) {
        const firstCandleTime = candlesData[0].time
        const lastCandleTime = candlesData[candlesData.length - 1].time
        filteredMarkers = markersData.filter(
          (m: { time: number }) => m.time >= firstCandleTime && m.time <= lastCandleTime
        )
      }

      // Only update if data changed (include timeframe in hash to force update on tf change)
      const dataHash = `${tf}:${JSON.stringify(candlesData.slice(-3))}`
      if (dataHash !== lastDataHash) {
        setLastDataHash(dataHash)
        setCandles(candlesData)
        setIndicators(indicatorsData)
        setMarkers(filteredMarkers)
      }

      if (stateData && !stateData.error) {
        // Include analytics in state if available
        if (analyticsRes && analyticsRes.ok) {
          try {
            const analyticsData = await analyticsRes.json()
            setAgentState({ ...stateData, analytics: analyticsData })
          } catch {
            setAgentState(stateData)
          }
        } else {
          setAgentState(stateData)
        }
      }

      // Update positions for chart price lines
      if (positionsRes && positionsRes.ok) {
        try {
          const positionsData = await positionsRes.json()
          setPositions(positionsData)
        } catch {
          setPositions([])
        }
      } else {
        setPositions([])
      }

      // Update recent trades for the below-chart trade dock
      if (tradesRes && tradesRes.ok) {
        try {
          const tradesData = await tradesRes.json()
          setRecentTrades(Array.isArray(tradesData) ? tradesData : [])
        } catch {
          setRecentTrades([])
        }
      } else {
        setRecentTrades([])
      }

      // Update performance summary (TD/7D/30D/WTD/MTD/YTD)
      if (perfSummaryRes && perfSummaryRes.ok) {
        try {
          const perfData = await perfSummaryRes.json()
          setPerformanceSummary(perfData || null)
        } catch {
          setPerformanceSummary(null)
        }
      } else {
        setPerformanceSummary(null)
      }

      // Calculate fetch duration and determine data source
      const fetchDuration = performance.now() - fetchStartRef.current
      // Detect cached data: if candles response has x-data-source header or is very fast (<50ms)
      const dataSourceHeader = candlesRes.headers.get('x-data-source')
      const detectedSource: DataSource = dataSourceHeader === 'cache' ? 'cached' : 'live'

      // Record successful fetch with timing and source
      recordFetch(fetchDuration, detectedSource)
      setIsLive(true)
      setChartError(null)

      // Always clear loading when we have data (even if less than ideal)
      // This fixes timeframe buttons getting stuck in loading state
      if (candlesData.length > 0) {
        setChartLoading(false)
      }
    } catch (err) {
      console.error('Failed to fetch data:', err)
      setChartError(err instanceof Error ? err.message : 'Failed to fetch')
      setIsLive(false)
      setChartLoading(false)
      setIsFetching(false)
    }
  }, [
    lastDataHash,
    setAgentState,
    setCandles,
    setIndicators,
    setMarkers,
    setMarketStatus,
    setLastDataHash,
    setChartError,
    setChartLoading,
    setIsLive,
    setIsFetching,
    recordFetch,
  ])

  useEffect(() => {
    fetchData(timeframe, barCount)
    // Use slower polling when WebSocket is connected (WS handles state updates)
    // Use faster polling when WebSocket is disconnected
    const refreshInterval = wsStatus === 'connected' ? WS_REFRESH_INTERVAL : REFRESH_INTERVAL
    const interval = setInterval(() => fetchData(timeframe, barCount), refreshInterval)
    return () => clearInterval(interval)
  }, [timeframe, barCount, wsStatus, fetchData])

  const formatTime = (date: Date | null) => {
    if (!date) return '--:--'
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  }

  const formatRelativeTime = (date: Date | null) => {
    if (!date) return 'Never'
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000)
    if (seconds < 5) return 'Just now'
    if (seconds < 60) return `${seconds}s ago`
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes}m ago`
    return formatTime(date)
  }

  const formatMarketCountdown = () => {
    if (!marketStatus) return null

    if (marketStatus.is_open) {
      // Market is open - would need close time from API
      // For now, show that it's open
      return null
    } else if (marketStatus.next_open) {
      try {
        const nextOpen = new Date(marketStatus.next_open)
        const now = new Date()
        const diffMs = nextOpen.getTime() - now.getTime()
        if (diffMs <= 0) return null

        const hours = Math.floor(diffMs / (1000 * 60 * 60))
        const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

        if (hours > 24) {
          const days = Math.floor(hours / 24)
          return `Opens in ${days}d ${hours % 24}h`
        }
        return `Opens in ${hours}h ${minutes}m`
      } catch {
        return null
      }
    }
    return null
  }

  const getAgentModeBadge = () => {
    if (!agentState) return null

    const aiStatus = agentState.ai_status
    if (!aiStatus) return null

    // Check if any AI component is in live mode
    const hasLive = aiStatus.bandit_mode === 'live' ||
                    aiStatus.contextual_mode === 'live' ||
                    (aiStatus.ml_filter.enabled && aiStatus.ml_filter.mode === 'live')

    // Check if any AI component is in shadow mode
    const hasShadow = aiStatus.bandit_mode === 'shadow' ||
                      aiStatus.contextual_mode === 'shadow' ||
                      (aiStatus.ml_filter.enabled && aiStatus.ml_filter.mode === 'shadow')

    if (hasLive) return { mode: 'live', label: 'AI LIVE' }
    if (hasShadow) return { mode: 'shadow', label: 'AI SHADOW' }
    return { mode: 'off', label: 'AI OFF' }
  }

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
    fetchData(timeframe, barCount)
  }, [fetchData, timeframe, barCount])

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
        fetchData(timeframe, barCount).finally(() => {
          refreshingRef = false
          setPullRefreshing(false)
          setPullDistance(0)
        })
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
  }, [fetchData, timeframe, barCount])

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
        timeZoneName: 'short',
      })
    } catch {
      return ''
    }
  }

  // Get AI mode from status
  const getAIMode = () => {
    if (!agentState?.ai_status) return null
    const ai = agentState.ai_status
    const hasLive = ai.bandit_mode === 'live' || ai.contextual_mode === 'live' ||
                    (ai.ml_filter?.enabled && ai.ml_filter?.mode === 'live')
    const hasShadow = ai.bandit_mode === 'shadow' || ai.contextual_mode === 'shadow' ||
                      (ai.ml_filter?.enabled && ai.ml_filter?.mode === 'shadow')
    if (hasLive) return 'live'
    if (hasShadow) return 'shadow'
    return 'off'
  }

  // Combined header - all info in one modern compact section
  const renderHeader = () => {
    const agentMode = getAgentModeBadge()
    const regime = getRegimeBadge()
    const countdown = formatMarketCountdown()
    const stale = isDataStale()
    const aiMode = getAIMode()
    const dirGate = agentState?.ai_status?.direction_gating

    return (
      <header className="header-combined">
        {/* Main Header Row */}
        <div className="header-row-main">
          {/* Brand */}
          <div className="header-brand">
            <Image src="/logo.png" alt="PEARL" width={28} height={28} className="header-logo" priority />
            <div className="header-titles">
              <span className="header-symbol">MNQ</span>
              <h1 className="header-app-name">Pearl Algo Web App</h1>
            </div>
          </div>

          {/* Stats */}
          {/* Moved daily P&L / W-L / positions into the Trades dock header for better visibility */}

          {/* Timeframe */}
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
        </div>

        {/* Secondary Row - System Status + AI Metrics */}
        <div className="header-row-secondary">
          <div className="header-badges">
            {/* System status badges - tap for explanation */}
            {agentState && (
              <span
                className={`badge agent-badge ${agentState.running ? (agentState.paused ? 'paused' : 'running') : 'stopped'}`}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'agent' ? null : 'agent') }}
              >
                <span className="badge-dot"></span>
                {agentState.running ? (agentState.paused ? 'PAUSED' : 'RUNNING') : 'STOPPED'}
              </span>
            )}
            {agentState && (
              <span
                className={`badge gw-badge ${agentState.gateway_status?.status === 'online' ? 'ok' : 'error'}`}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'gw' ? null : 'gw') }}
              >
                <span className="badge-dot"></span>
                GW
              </span>
            )}
            {aiMode && (
              <span
                className={`badge ai-badge ${aiMode}`}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'ai' ? null : 'ai') }}
              >
                🧠 {aiMode.toUpperCase()}
                {agentState?.shadow_counters && agentState.shadow_counters.would_block_total > 0 && (
                  <span className="badge-shadow-count">{agentState.shadow_counters.would_block_total}</span>
                )}
              </span>
            )}
            {marketStatus && (
              <span
                className={`badge market-badge ${marketStatus.is_open ? 'open' : 'closed'}`}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'market' ? null : 'market') }}
              >
                {marketStatus.is_open ? '🟢 OPEN' : '🔴 CLOSED'}
              </span>
            )}
            {agentState && (
              <span
                className={`badge data-badge ${agentState.data_fresh ? 'ok' : 'stale'}`}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'data' ? null : 'data') }}
              >
                <span className="badge-dot"></span>
                Data
              </span>
            )}
            {agentState?.ml_filter_performance?.lift_ok && agentState.ml_filter_performance.win_rate_pass != null && (
              <span
                className={`badge ml-badge ${(agentState.ml_filter_performance.lift_win_rate || 0) > 0.1 ? 'good' : 'neutral'}`}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'ml' ? null : 'ml') }}
              >
                ML {Math.round((agentState.ml_filter_performance.win_rate_pass) * 100)}%
              </span>
            )}
            {agentState?.shadow_counters && (agentState.shadow_counters.blocked_total > 0) && (
              <span
                className={`badge saved-badge ${(agentState.shadow_counters.net_saved || 0) >= 0 ? 'positive' : 'negative'}`}
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

  // Status panel no longer needed - integrated into header
  const renderStatusPanel = () => null

  // Chart section component
  const renderChart = () => (
    <div className="chart-wrapper">
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
      <div className="chart-container">
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
            <CandlestickChart
              data={candles}
              indicators={indicators}
              markers={markers}
              barSpacing={barSpacing}
              timeframe={timeframe}
              onChartReady={setMainChartApi}
              positionLines={positionLines}
            />
          </ErrorBoundary>
        )}
      </div>
    </div>
  )

  // Chart settings store for indicator visibility
  const showVolumeProfilePanel = useChartSettingsStore((s) => s.showVolumeProfilePanel)

  // Volume Profile section component
  const renderVolumeProfile = () => (
    showVolumeProfilePanel && indicators.volumeProfile && (
      <VolumeProfilePanel
        data={indicators.volumeProfile}
        currentPrice={candles.length > 0 ? candles[candles.length - 1].close : undefined}
        height={300}
      />
    )
  )

  // Compact header for ultrawide view
  const renderUltrawideHeader = () => {
    const stale = isDataStale()
    return (
      <div className="ultrawide-header">
        <div className="uw-brand">
          <Image src="/logo.png" alt="PEARL" width={20} height={20} priority />
          <span className="uw-symbol">MNQ</span>
        </div>
        <div className="uw-stats">
          <span className={`uw-pnl ${(agentState?.daily_pnl || 0) >= 0 ? 'positive' : 'negative'}`}>
            {(agentState?.daily_pnl || 0) >= 0 ? '+' : ''}${(agentState?.daily_pnl || 0).toFixed(0)}
          </span>
          <span className="uw-trades">
            {agentState?.performance?.['24h']?.wins || 0}W/{agentState?.performance?.['24h']?.losses || 0}L
          </span>
        </div>
        <div className="uw-timeframe">
          {(['1m', '5m', '15m', '30m', '1h', '4h', '1D'] as Timeframe[]).map((tf) => (
            <button
              key={tf}
              className={`uw-tf-btn ${timeframe === tf ? 'active' : ''}`}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>
        <div className={`uw-status ${stale ? 'stale' : 'live'}`}>
          <span className="uw-status-dot"></span>
          {stale ? 'STALE' : 'LIVE'}
        </div>
      </div>
    )
  }

  // Ultrawide layout for Xeneon Edge (2560x720)
  if (viewport.isUltrawide && agentState) {
    return (
      <>
        {/* Skip navigation link for accessibility */}
        <a href="#main-content" className="skip-link">Skip to main content</a>
        <PearlHeaderBar />
        <main className="main-content" id="main-content">
          <div className={`dashboard ultrawide-mode`} data-chart-ready={isChartReady ? 'true' : 'false'}>
            <UltrawideLayout
              headerSection={renderUltrawideHeader()}
              chartSection={renderChart()}
              belowChartSection={
                <TradeDockPanel
                  positions={positions}
                  recentTrades={recentTrades}
                  symbol={agentState?.config?.symbol || 'MNQ'}
                  currentPrice={candles.length > 0 ? candles[candles.length - 1].close : undefined}
                  openUnrealizedPnL={agentState?.active_trades_unrealized_pnl ?? null}
                  performanceSummary={performanceSummary}
                  directionBreakdown={agentState.analytics?.direction_breakdown || null}
                  statusBreakdown={agentState.analytics?.status_breakdown || null}
                  maxOpenRows={4}
                  maxRecentRows={6}
                  dailyPnL={agentState?.daily_pnl}
                  dailyWins={agentState?.daily_wins}
                  dailyLosses={agentState?.daily_losses}
                  activeTradesCount={agentState?.active_trades_count}
                />
              }
              pearlAISection={
                <PearlInsightsPanel
                  insights={agentState.pearl_insights}
                  suggestion={agentState.pearl_suggestion}
                  agentState={agentState}
                  aiStatus={agentState.ai_status}
                  shadowCounters={agentState.shadow_counters}
                  mlFilterPerformance={agentState.ml_filter_performance}
                  chatAvailable={Boolean(agentState.pearl_ai_available)}
                  operatorLockEnabled={agentState.operator_lock_enabled ?? null}
                  pearlFeed={agentState.pearl_feed ?? []}
                  pearlAIHeartbeat={agentState.pearl_ai_heartbeat ?? null}
                  pearlAIDebug={agentState.pearl_ai_debug ?? null}
                />
              }
              systemStatusSection={
                <SystemStatusPanel
                  executionState={agentState.execution_state}
                  circuitBreaker={agentState.circuit_breaker}
                  marketRegime={agentState.market_regime}
                  sessionContext={agentState.session_context}
                  errorSummary={agentState.error_summary}
                  isRunning={agentState.running}
                  isPaused={agentState.paused}
                />
              }
              challengeSection={
                agentState.challenge && (
                  <ChallengePanel
                    challenge={agentState.challenge}
                    equityCurve={agentState.equity_curve}
                  />
                )
              }
              marketContextSection={
                (agentState.market_regime || agentState.buy_sell_pressure) && (
                  <MarketContextPanel
                    regime={agentState.market_regime}
                    pressure={agentState.buy_sell_pressure}
                  />
                )
              }
              riskEquitySection={
                (agentState.risk_metrics || (agentState.equity_curve && agentState.equity_curve.length > 0)) && (
                  <RiskEquityPanel
                    riskMetrics={agentState.risk_metrics}
                    equityCurve={agentState.equity_curve || []}
                  />
                )
              }
              analyticsSection={
                agentState.analytics && (
                  <AnalyticsPanel
                    analytics={agentState.analytics}
                    recentExits={agentState.recent_exits}
                  />
                )
              }
              systemHealthSection={
                (agentState.cadence_metrics || agentState.gateway_status) && (
                  <SystemHealthPanel
                    cadenceMetrics={agentState.cadence_metrics || null}
                    dataFresh={agentState.data_fresh || false}
                    gatewayStatus={agentState.gateway_status}
                    connectionHealth={agentState.connection_health}
                    errorSummary={agentState.error_summary}
                    dataQuality={agentState.data_quality}
                  />
                )
              }
              signalDecisionsSection={
                (agentState.signal_rejections_24h || agentState.last_signal_decision) && (
                  <SignalDecisionsPanel
                    rejections={agentState.signal_rejections_24h || null}
                    lastDecision={agentState.last_signal_decision || null}
                  />
                )
              }
            />
          </div>
        </main>
      </>
    )
  }

  // Standard layout (mobile, tablet, desktop)
  return (
    <>
      {/* Skip navigation link for accessibility */}
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <PearlHeaderBar />
      <main className="main-content" id="main-content">
        {/* Pull-to-refresh indicator */}
        <div
          className={`pull-to-refresh ${pullRefreshing ? 'refreshing' : ''} ${pullDistance > 0 ? 'visible' : ''}`}
          style={{
            height: pullDistance > 0 ? pullDistance : 0,
            opacity: pullDistance > 0 ? Math.min(pullDistance / PULL_THRESHOLD, 1) : 0,
          }}
        >
          <div
            className={`pull-icon ${pullRefreshing ? 'spinning' : ''}`}
            style={{
              transform: pullRefreshing ? 'none' : `rotate(${Math.min(pullDistance / PULL_THRESHOLD, 1) * 180}deg)`,
            }}
          >
            {pullRefreshing ? '↻' : '↓'}
          </div>
          <div className="pull-text">
            {pullRefreshing ? 'Refreshing...' : pullDistance >= PULL_THRESHOLD ? 'Release to refresh' : 'Pull to refresh'}
          </div>
        </div>
        <div className="dashboard" data-chart-ready={isChartReady ? 'true' : 'false'}>
          {renderHeader()}
          {renderStatusPanel()}
          {renderChart()}

          {/* Trades Dock (Open / Recent) - TradingView-style section */}
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
          />

          {/* Post-trade panels (signals / ops / advanced analytics) */}
          {agentState && <PostTradesPanels agentState={agentState} />}
        </div>
      </main>
    </>
  )
}
