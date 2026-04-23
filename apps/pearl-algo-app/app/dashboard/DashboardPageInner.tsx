'use client'

import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import Image from 'next/image'
import CandlestickChart from '@/components/CandlestickChart'
import RSIPane from '@/components/RSIPane'
import TradeDockPanel, { type RecentTradeRow, type PerformanceSummary, type RecentSignalEvent } from '@/components/TradeDockPanel'
import DashboardLayout from '@/components/DashboardLayout'
import InfoStrip from '@/components/InfoStrip'
import HealthDots from '@/components/info-strip/HealthDots'
import DataFreshnessIndicator from '@/components/DataFreshnessIndicator'
import WatchlistPanel from '@/components/WatchlistPanel'
import SystemLogsPanel from '@/components/SystemLogsPanel'
import LiveLogsPanel from '@/components/LiveLogsPanel'
import SignalsPanel from '@/components/SignalsPanel'
import ActivityLogPanel from '@/components/ActivityLogPanel'
import TrailingStopPanel from '@/components/TrailingStopPanel'
import { useWebSocket, getWebSocketUrl } from '@/hooks/useWebSocket'
import { useDashboardData } from '@/hooks/useDashboardData'
import { useLazyLoadCandles } from '@/hooks/useLazyLoadCandles'
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
  const prependCandles = useChartStore((s) => s.prependCandles)
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
  const addNotification = useUIStore((s) => s.addNotification)

  // Local state for chart API reference (not suitable for global store)
  const [mainChartApi, setMainChartApi] = useState<IChartApi | null>(null)

  // Lazy-load older bars from the archive when user pans toward the
  // leftmost bar. The hook's no-op when the archive runs out of data.
  useLazyLoadCandles({
    chart: mainChartApi,
    data: candles,
    symbol: agentState?.config?.symbol || 'MNQ',
    timeframe,
    onOlderBars: prependCandles,
  })

  // Badge tooltip state (which badge explanation is showing)
  const [badgeTip, setBadgeTip] = useState<string | null>(null)

  // Indicators dropdown state
  const [showIndicatorsDropdown, setShowIndicatorsDropdown] = useState(false)
  // Mobile menu state
  const [showMobileMenu, setShowMobileMenu] = useState(false)
  // Keyboard shortcuts help overlay (toggled by `?`, closed by `Esc`)
  const [showShortcutsHelp, setShowShortcutsHelp] = useState(false)
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
  const { refresh: requestWebSocketRefresh } = useWebSocket({
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
    if (wsStatus === 'connected') {
      requestWebSocketRefresh()
    }
    dashboardData.handleTradeRefresh()
  }, [dashboardData, requestWebSocketRefresh, wsStatus])

  // ── Toast emissions ─────────────────────────────────────────────────────────
  // Watch agent state for newsworthy events and push toasts via uiStore.
  // Each effect tracks the previously-seen value in a ref so we only emit on
  // *transitions*, not on every state update.

  // Trade-exit toasts (TP / SL / manual). Anchored to recent_exits[0].signal_id.
  const lastSeenExitIdRef = useRef<string | null>(null)
  useEffect(() => {
    const top = agentState?.recent_exits?.[0]
    if (!top || !top.signal_id) return
    // Skip on first paint so we don't toast historical exits.
    if (lastSeenExitIdRef.current === null) {
      lastSeenExitIdRef.current = top.signal_id
      return
    }
    if (top.signal_id === lastSeenExitIdRef.current) return
    lastSeenExitIdRef.current = top.signal_id

    const dir = (top.direction || '').toUpperCase() || 'TRADE'
    const reason = (top.exit_reason || '').toLowerCase()
    const isWin = (top.pnl ?? 0) >= 0
    let title = ''
    if (reason.includes('target') || reason.includes('tp_') || reason.includes('profit')) {
      title = `${dir} hit target  ·  ${isWin ? '+' : '-'}$${Math.abs(top.pnl ?? 0).toFixed(2)}`
    } else if (reason.includes('stop') || reason.includes('sl_')) {
      title = `${dir} stopped out  ·  ${isWin ? '+' : '-'}$${Math.abs(top.pnl ?? 0).toFixed(2)}`
    } else if (reason.includes('trail')) {
      title = `${dir} trail exit  ·  ${isWin ? '+' : '-'}$${Math.abs(top.pnl ?? 0).toFixed(2)}`
    } else {
      title = `${dir} closed  ·  ${isWin ? '+' : '-'}$${Math.abs(top.pnl ?? 0).toFixed(2)}`
    }

    addNotification({
      type: isWin ? 'success' : 'warning',
      title,
      message: top.exit_reason
        ? top.exit_reason.replace(/_/g, ' ')
        : undefined,
    })
  }, [agentState?.recent_exits, addNotification])

  // Circuit-breaker trip toasts (when trips_today increments).
  const lastSeenTripsRef = useRef<number | null>(null)
  useEffect(() => {
    const trips = agentState?.circuit_breaker?.trips_today
    if (typeof trips !== 'number') return
    if (lastSeenTripsRef.current === null) {
      lastSeenTripsRef.current = trips
      return
    }
    if (trips > lastSeenTripsRef.current) {
      const reason = agentState?.circuit_breaker?.trip_reason || 'tripped'
      addNotification({
        type: 'error',
        title: 'Circuit breaker tripped',
        message: reason,
      })
    }
    lastSeenTripsRef.current = trips
  }, [agentState?.circuit_breaker?.trips_today, agentState?.circuit_breaker?.trip_reason, addNotification])

  // WebSocket health degradation toast (connected → not connected). We only
  // toast on the disconnect transition; reconnect is silent so we don't spam.
  const lastSeenWsRef = useRef<typeof wsStatus | null>(null)
  useEffect(() => {
    const prev = lastSeenWsRef.current
    if (prev === 'connected' && wsStatus !== 'connected') {
      addNotification({
        type: 'warning',
        title: 'Live socket dropped',
        message: 'Falling back to HTTP polling. Will auto-reconnect.',
      })
    }
    lastSeenWsRef.current = wsStatus
  }, [wsStatus, addNotification])

  const formatTime = formatTimeFromDate
  const formatRelativeTimeFromDate = (date: Date | null) => {
    if (!date) return 'Never'
    return formatRelativeTime(date)
  }
  const formatMarketCountdownFromStatus = () => {
    if (!marketStatus?.next_open) return null
    return formatMarketCountdown(marketStatus.next_open)
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
    if (wsStatus === 'connected') {
      requestWebSocketRefresh()
    }
    dashboardData.handleTradeRefresh()
  }, [dashboardData, requestWebSocketRefresh, wsStatus])

  // Pull-to-refresh (mobile touch) - uses window scroll position
  const pullStartY = useRef(0)
  const pullActive = useRef(false)
  const pullDistanceRef = useRef(0)
  const [pullDistance, setPullDistance] = useState(0)
  const [pullRefreshing, setPullRefreshing] = useState(false)
  const PULL_THRESHOLD = 70

  // Keep ref in sync with state for use in touchend
  useEffect(() => { pullDistanceRef.current = pullDistance }, [pullDistance])

  // Keyboard shortcuts — TradingView-style, single key (no modifier required).
  // Guards against inputs/textareas/contenteditable to keep normal typing safe.
  // `?` / `Esc` toggle the shortcut help overlay (rendered at the bottom of
  // this component).
  useEffect(() => {
    const TIMEFRAMES: Timeframe[] = ['1m', '5m', '15m', '30m', '1h', '4h', '1D']
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const target = e.target as HTMLElement | null
      if (!target) return
      const tag = target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (target.isContentEditable) return

      switch (e.key) {
        case '[': {
          const idx = TIMEFRAMES.indexOf(timeframe)
          if (idx > 0) { setTimeframe(TIMEFRAMES[idx - 1]); e.preventDefault() }
          break
        }
        case ']': {
          const idx = TIMEFRAMES.indexOf(timeframe)
          if (idx >= 0 && idx < TIMEFRAMES.length - 1) { setTimeframe(TIMEFRAMES[idx + 1]); e.preventDefault() }
          break
        }
        case 'f':
        case 'F': {
          // Fit chart — same logic as DataFreshnessIndicator's fit-all button
          if (mainChartApi && candles.length > 0) {
            const visibleBars = Math.min(100, candles.length)
            if (candles.length > visibleBars) {
              const fromTime = candles[candles.length - visibleBars].time as unknown as import('lightweight-charts').Time
              const toTime = candles[candles.length - 1].time as unknown as import('lightweight-charts').Time
              mainChartApi.timeScale().setVisibleRange({ from: fromTime, to: toTime })
            } else {
              mainChartApi.timeScale().fitContent()
            }
            mainChartApi.timeScale().scrollToRealTime()
            e.preventDefault()
          }
          break
        }
        case 'g':
        case 'G': {
          mainChartApi?.timeScale().scrollToRealTime()
          e.preventDefault()
          break
        }
        case '?': {
          setShowShortcutsHelp((v) => !v)
          e.preventDefault()
          break
        }
        case 'Escape': {
          setShowShortcutsHelp(false)
          break
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [timeframe, setTimeframe, mainChartApi, candles])

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

  // Combined header - single row: timeframes left, status badges right
  const renderHeader = () => {
    return (
      <header className="header-combined">
        <div className="header-row-single">
          {/* Mobile: logo + hamburger — only visible when sidebars hidden */}
          <div className="mobile-logo">
            <Image src="/logo.png" alt="PEARL" width={20} height={20} />
          </div>
          <button
            className="mobile-menu-btn"
            onClick={() => setShowMobileMenu(!showMobileMenu)}
            title="Menu"
          >
            <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
              <line x1="3" y1="5" x2="15" y2="5"/><line x1="3" y1="9" x2="15" y2="9"/><line x1="3" y1="13" x2="15" y2="13"/>
            </svg>
          </button>

          {/* Left: Timeframe buttons (desktop) + dropdown (mobile) */}
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
          {/* Mobile timeframe dropdown */}
          <select
            className="mobile-tf-select"
            value={timeframe}
            onChange={(e) => setTimeframe(e.target.value as Timeframe)}
          >
            {(['1m', '5m', '15m', '30m', '1h', '4h', '1D'] as Timeframe[]).map((tf) => (
              <option key={tf} value={tf}>{tf}</option>
            ))}
          </select>

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

          </div>

          {/* Health dots (WS/GW/DATA/TV/DB) live in the header now —
              tucked left of the agent/market badges. The .header-health
              wrapper applies header-specific compact styling (no labels
              on phone, smaller dots) without disturbing the InfoStrip
              variant on tablet/desktop. */}
          <div className="header-health">
            <HealthDots
              wsStatus={wsStatus}
              gateway={agentState?.gateway_status ?? null}
              connectionHealth={agentState?.connection_health ?? null}
              tradovate={agentState?.tradovate_account ?? null}
              dataQuality={agentState?.data_quality ?? null}
              lastExitTime={agentState?.recent_exits?.[0]?.exit_time ?? null}
            />
          </div>
          {/* Right: Status badges */}
          <div className="header-badges">
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
          </div>
          {/* Badge explanation tooltip */}
          {badgeTip && (
            <div className="badge-tooltip" onClick={() => setBadgeTip(null)}>
              {badgeTip === 'agent' && (
                <p><strong>Agent</strong> — Trading scanner process. {agentState?.running ? 'Running and scanning for signals every cycle.' : 'Stopped. No signals are being generated.'}{agentState?.paused ? ' Currently paused due to circuit breaker or manual pause.' : ''}</p>
              )}
              {badgeTip === 'market' && (
                <p><strong>Market</strong> — CME Futures session. {marketStatus?.is_open ? 'Market is open. Real-time data flowing.' : `Market closed${marketStatus?.close_reason ? ` (${marketStatus.close_reason})` : ''}. Historical data only.`}</p>
              )}
            </div>
          )}
        </div>

        {/* Mobile slide-out menu */}
        {showMobileMenu && (
          <div className="mobile-menu-overlay" onClick={() => setShowMobileMenu(false)}>
            <div className="mobile-menu-panel" onClick={(e) => e.stopPropagation()}>
              <div className="mobile-menu-header">
                <Image src="/logo.png" alt="PEARL" width={20} height={20} />
                <span>PEARL</span>
                <button className="mobile-menu-close" onClick={() => setShowMobileMenu(false)}>
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                    <line x1="3" y1="3" x2="13" y2="13"/><line x1="13" y1="3" x2="3" y2="13"/>
                  </svg>
                </button>
              </div>
              <nav className="mobile-menu-nav">
                <a href="/dashboard?account=tv_paper" className="mobile-menu-item active">Dashboard</a>
                <a href="/settings" className="mobile-menu-item">Settings</a>
              </nav>
              <div className="mobile-menu-divider" />
              <div className="mobile-menu-section-label">Panels</div>
              <div className="mobile-menu-actions">
                <button className={`mobile-menu-item ${activeRightPanel === 'watchlist' ? 'active' : ''}`} onClick={() => { setShowMobileMenu(false); toggleRightPanel('watchlist') }}>
                  Watchlist
                </button>
                <button className={`mobile-menu-item ${activeRightPanel === 'activity' ? 'active' : ''}`} onClick={() => { setShowMobileMenu(false); toggleRightPanel('activity') }}>
                  Activity Log
                </button>
                <button className={`mobile-menu-item ${activeRightPanel === 'logs' ? 'active' : ''}`} onClick={() => { setShowMobileMenu(false); toggleRightPanel('logs') }}>
                  System Status
                </button>
                <button className={`mobile-menu-item ${activeRightPanel === 'signals' ? 'active' : ''}`} onClick={() => { setShowMobileMenu(false); toggleRightPanel('signals') }}>
                  Signals
                </button>
                <button className={`mobile-menu-item ${activeRightPanel === 'trailing' ? 'active' : ''}`} onClick={() => { setShowMobileMenu(false); toggleRightPanel('trailing') }}>
                  Trailing Stops
                </button>
              </div>
              <div className="mobile-menu-divider" />
              <div className="mobile-menu-actions">
                <button className="mobile-menu-item" onClick={() => { setShowMobileMenu(false); document.documentElement.requestFullscreen() }}>
                  Fullscreen
                </button>
                <button className="mobile-menu-item" onClick={() => { setShowMobileMenu(false); mainChartApi?.takeScreenshot() }}>
                  Screenshot
                </button>
              </div>
            </div>
          </div>
        )}
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
              The trading agent may be restarting. Data resumes automatically when it reconnects.
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
      return <LiveLogsPanel />
    }
    if (activeRightPanel === 'activity') {
      return <ActivityLogPanel recentSignals={recentSignals} />
    }
    if (activeRightPanel === 'signals') {
      return <SignalsPanel />
    }
    if (activeRightPanel === 'trailing') {
      return <TrailingStopPanel />
    }
    return null
  }

  // Standard layout (all viewports)
  return (
    <>
    <DashboardLayout
        isChartReady={isChartReady}
        pull={{ pullDistance, pullRefreshing, pullThreshold: PULL_THRESHOLD }}
        header={renderHeader()}
        infoStrip={
          <ErrorBoundary panelName="InfoStrip">
            <InfoStrip
              agentState={agentState}
              positions={positions}
              wsStatus={wsStatus}
            />
          </ErrorBoundary>
        }
        chart={renderChart()}
        activeRightPanel={activeRightPanel}
        onToggleRightPanel={toggleRightPanel}
        onCloseRightPanel={() => setActiveRightPanel(null)}
        rightPanelContent={renderRightPanelContent()}
        mainChartApi={mainChartApi}
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
                recentSignals={recentSignals}
                workingOrders={agentState?.tradovate_account?.working_orders}
                orderStats={agentState?.tradovate_account?.order_stats || null}
                accountEquity={agentState?.tradovate_account?.equity ?? performanceSummary?.all?.tradovate_equity ?? null}
                accountTotalPnl={performanceSummary?.all?.pnl ?? null}
                accountWinRate={performanceSummary?.all?.win_rate ?? null}
                accountId={(agentState?.tradovate_account as any)?.account ?? null}
                accountEnv={(agentState?.tradovate_account as any)?.env ?? null}
                analytics={agentState?.analytics ?? null}
                execArmed={agentState?.execution_state?.armed}
              />
            </ErrorBoundary>
          </>
        }
      />
    {showShortcutsHelp && (
      <div
        className="shortcuts-overlay"
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcuts-title"
        onClick={() => setShowShortcutsHelp(false)}
      >
        <div className="shortcuts-dialog" onClick={(e) => e.stopPropagation()}>
          <div className="shortcuts-header">
            <h2 id="shortcuts-title" className="shortcuts-title">Keyboard Shortcuts</h2>
            <button
              className="shortcuts-close"
              onClick={() => setShowShortcutsHelp(false)}
              aria-label="Close shortcuts help"
            >×</button>
          </div>
          <div className="shortcuts-body">
            <div className="shortcuts-section">
              <div className="shortcuts-section-label">Timeframe</div>
              <div className="shortcuts-row"><kbd>[</kbd><span className="shortcuts-desc">Previous timeframe</span></div>
              <div className="shortcuts-row"><kbd>]</kbd><span className="shortcuts-desc">Next timeframe</span></div>
            </div>
            <div className="shortcuts-section">
              <div className="shortcuts-section-label">Chart</div>
              <div className="shortcuts-row"><kbd>F</kbd><span className="shortcuts-desc">Fit to last ~100 bars</span></div>
              <div className="shortcuts-row"><kbd>G</kbd><span className="shortcuts-desc">Go live (scroll to now)</span></div>
            </div>
            <div className="shortcuts-section">
              <div className="shortcuts-section-label">Help</div>
              <div className="shortcuts-row"><kbd>?</kbd><span className="shortcuts-desc">Toggle this panel</span></div>
              <div className="shortcuts-row"><kbd>Esc</kbd><span className="shortcuts-desc">Close</span></div>
            </div>
          </div>
          <div className="shortcuts-footer">
            Shortcuts are disabled while typing in form fields.
          </div>
        </div>
      </div>
    )}
    </>
  )
}
