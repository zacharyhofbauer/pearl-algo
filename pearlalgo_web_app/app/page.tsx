'use client'

import { useEffect, useState, useCallback } from 'react'
import Image from 'next/image'
import CandlestickChart from '@/components/CandlestickChart'
import DataPanelsContainer from '@/components/DataPanelsContainer'
import PerformancePanel from '@/components/PerformancePanel'
import ChallengePanel from '@/components/ChallengePanel'
import RecentTradesPanel from '@/components/RecentTradesPanel'
import PearlInsightsPanel from '@/components/PearlInsightsPanel'
import EquityCurvePanel from '@/components/EquityCurvePanel'
import RiskMetricsPanel from '@/components/RiskMetricsPanel'
import HelpPanel from '@/components/HelpPanel'
import MarketPressurePanel from '@/components/MarketPressurePanel'
import SystemHealthPanel from '@/components/SystemHealthPanel'
import ConfigPanel from '@/components/ConfigPanel'
import MarketRegimePanel from '@/components/MarketRegimePanel'
import SignalDecisionsPanel from '@/components/SignalDecisionsPanel'
import AnalyticsPanel from '@/components/AnalyticsPanel'
import ActivePositionsPanel from '@/components/ActivePositionsPanel'
import PnLCalendarPanel from '@/components/PnLCalendarPanel'
import UltrawideLayout from '@/components/UltrawideLayout'
import { useViewportType } from '@/hooks/useViewportType'
import { useWebSocket, getWebSocketUrl } from '@/hooks/useWebSocket'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { getApiUrl, apiFetch } from '@/lib/api'
import type { IChartApi } from 'lightweight-charts'

// Import stores and types
import {
  useAgentStore,
  useChartStore,
  useUIStore,
  type Timeframe,
  type IndicatorData,
} from '@/stores'

// API configuration imported from @/lib/api
const REFRESH_INTERVAL = 10000 // 10 seconds (fallback when WebSocket disconnected)
const WS_REFRESH_INTERVAL = 30000 // 30 seconds (slower when WebSocket connected)

// Minimum bars to request for a full chart (500 = ~4 days on 5m, ~2 weeks on 1h)
const MIN_BARS = 500

// Fetch 72 hours (3 days) of markers - API limit
const MARKER_HOURS = 72

export default function PearlAlgoWebApp() {
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
  const setWsStatus = useUIStore((s) => s.setWsStatus)
  const setIsLive = useUIStore((s) => s.setIsLive)
  const setLastUpdate = useUIStore((s) => s.setLastUpdate)

  // Local state for chart API reference (not suitable for global store)
  const [mainChartApi, setMainChartApi] = useState<IChartApi | null>(null)

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
    try {
      // Ensure we always request at least MIN_BARS
      const requestBars = Math.max(MIN_BARS, bars)

      // Fetch all data in parallel (apiFetch includes auth headers when configured)
      const [candlesRes, indicatorsRes, markersRes, stateRes, marketStatusRes, analyticsRes] = await Promise.all([
        apiFetch(`/api/candles?symbol=MNQ&timeframe=${tf}&bars=${requestBars}`),
        apiFetch(`/api/indicators?symbol=MNQ&timeframe=${tf}&bars=${requestBars}`),
        apiFetch(`/api/markers?hours=${MARKER_HOURS}`),
        apiFetch(`/api/state`),
        apiFetch(`/api/market-status`),
        apiFetch(`/api/analytics`).catch(() => null),  // Analytics is optional
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

      setLastUpdate(new Date())
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
    setLastUpdate,
    setIsLive,
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

  const isDataStale = () => {
    if (!lastUpdate) return true
    const seconds = Math.floor((Date.now() - lastUpdate.getTime()) / 1000)
    return seconds > 120 // Stale if > 2 minutes
  }

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
        {/* Stale Data Warning */}
        {stale && isLive && (
          <div className="stale-warning">
            ⚠️ Data may be stale - last update {formatRelativeTime(lastUpdate)}
          </div>
        )}

        {/* Main Header Row */}
        <div className="header-row-main">
          {/* Brand */}
          <div className="header-brand">
            <Image src="/pearl-emoji.png" alt="PEARL" width={28} height={28} className="header-logo" priority />
            <div className="header-titles">
              <span className="header-symbol">MNQ</span>
              <span className="header-app-name">Pearl Algo Web App</span>
            </div>
          </div>

          {/* Stats */}
          {agentState && (
            <div className="header-stats-row">
              <div className={`stat-item pnl ${agentState.daily_pnl >= 0 ? 'positive' : 'negative'}`}>
                <span className="stat-label">P&L</span>
                <span className="stat-value">{formatPnL(agentState.daily_pnl)}</span>
              </div>
              <div className="stat-item trades">
                <span className="stat-label">W/L</span>
                <span className="stat-value">
                  <span className="win">{agentState.daily_wins}</span>/<span className="loss">{agentState.daily_losses}</span>
                </span>
              </div>
              {agentState.active_trades_count > 0 && (
                <div className="stat-item positions">
                  <span className="stat-value highlight">{agentState.active_trades_count} pos</span>
                </div>
              )}
            </div>
          )}

          {/* Timeframe */}
          <div className="header-timeframe">
            {(['1m', '5m', '15m', '1h'] as Timeframe[]).map((tf) => (
              <button
                key={tf}
                className={`tf-btn ${timeframe === tf ? 'active' : ''}`}
                onClick={() => setTimeframe(tf)}
              >
                {tf}
              </button>
            ))}
          </div>

          {/* Status Indicators */}
          <div className="header-status">
            <div className={`status-indicator ${stale ? 'stale' : 'live'}`}>
              <span className="status-dot"></span>
              <span className="status-text">{stale ? 'STALE' : 'LIVE'}</span>
            </div>
          </div>
        </div>

        {/* Secondary Row - Badges, Health, Legends */}
        <div className="header-row-secondary">
          {/* Badges */}
          <div className="header-badges">
            {agentState && (
              <span className={`badge agent-badge ${agentState.running ? (agentState.paused ? 'paused' : 'running') : 'stopped'}`}>
                <span className="badge-dot"></span>
                {agentState.running ? (agentState.paused ? 'PAUSED' : 'RUNNING') : 'STOPPED'}
              </span>
            )}
            {aiMode && (
              <span className={`badge ai-badge ${aiMode}`}>
                🧠 {aiMode.toUpperCase()}
              </span>
            )}
            {regime && (
              <span className={`badge regime-badge`}>
                {regime.icon} {regime.label}
              </span>
            )}
            {marketStatus && (
              <span className={`badge market-badge ${marketStatus.is_open ? 'open' : 'closed'}`}>
                {marketStatus.is_open ? '🟢 OPEN' : '🔴 CLOSED'}
                {countdown && <span className="countdown">{countdown}</span>}
              </span>
            )}
          </div>

          {/* Health Indicators */}
          {agentState && (
            <div className="header-health">
              <span className={`health-dot ${agentState.gateway_status?.status === 'online' ? 'ok' : 'error'}`}></span>
              <span className="health-label">GW</span>
              <span className={`health-dot ${agentState.data_fresh ? 'ok' : 'error'}`}></span>
              <span className="health-label">Data</span>
              <span className={`health-dot ${agentState.futures_market_open ? 'ok' : 'warning'}`}></span>
              <span className="health-label">Mkt</span>
              {dirGate?.enabled && (
                <>
                  <span className={`health-dot ${dirGate.blocks > 0 ? 'warning' : 'ok'}`}></span>
                  <span className="health-label">{dirGate.blocks > 0 ? `${dirGate.blocks}🚫` : 'Gate✓'}</span>
                </>
              )}
            </div>
          )}

          {/* Chart Legend */}
          <div className="header-legend">
            <span className="legend-item"><span className="legend-line ema9"></span>EMA9</span>
            <span className="legend-item"><span className="legend-line ema21"></span>EMA21</span>
            <span className="legend-item"><span className="legend-line vwap"></span>VWAP</span>
            <span className="legend-item"><span className="legend-marker long">▲</span>Long</span>
            <span className="legend-item"><span className="legend-marker short">▼</span>Short</span>
            <span className="legend-item"><span className="legend-marker win">●</span>Win</span>
            <span className="legend-item"><span className="legend-marker loss">●</span>Loss</span>
          </div>
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
        <button
          className="chart-action-btn"
          onClick={() => window.location.reload()}
          title="Refresh"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M23 4v6h-6M1 20v-6h6M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
          </svg>
        </button>
        <button
          className="chart-action-btn"
          onClick={() => mainChartApi?.timeScale().fitContent()}
          title="Fit All"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
          </svg>
        </button>
        <button
          className="chart-action-btn"
          onClick={() => mainChartApi?.timeScale().scrollToRealTime()}
          title="Go Live"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polygon points="5 3 19 12 5 21 5 3" />
          </svg>
        </button>
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
            />
          </ErrorBoundary>
        )}
      </div>
    </div>
  )

  // RSI section component
  const renderRSI = () => (
    indicators.rsi && indicators.rsi.length > 0 && (
      <div className="rsi-panel">
        <RSIChart data={indicators.rsi} barSpacing={barSpacing} />
      </div>
    )
  )

  // Compact header for ultrawide view
  const renderUltrawideHeader = () => {
    const stale = isDataStale()
    return (
      <div className="ultrawide-header">
        <div className="uw-brand">
          <Image src="/pearl-emoji.png" alt="PEARL" width={20} height={20} priority />
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
          {(['1m', '5m', '15m', '1h'] as Timeframe[]).map((tf) => (
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
      <div className={`dashboard ultrawide-mode`} data-chart-ready={isChartReady ? 'true' : 'false'}>
        {/* Market Closed Banner */}
        {marketStatus && !marketStatus.is_open && (
          <div className="market-closed-banner ultrawide-banner">
            <span className="market-closed-icon">🔴</span>
            <span className="market-closed-text">
              Market Closed ({marketStatus.close_reason})
              {marketStatus.next_open && <> — Opens {formatNextOpen(marketStatus.next_open)}</>}
            </span>
          </div>
        )}

        <UltrawideLayout
          headerSection={renderUltrawideHeader()}
          chartSection={renderChart()}
          rsiSection={renderRSI()}
          pearlAISection={
            <PearlInsightsPanel
              insights={agentState.pearl_insights}
              suggestion={agentState.pearl_suggestion}
              aiStatus={agentState.ai_status}
              shadowCounters={agentState.shadow_counters}
            />
          }
          performanceSection={
            agentState.performance && (
              <PerformancePanel
                performance={agentState.performance}
                expectancy={agentState.risk_metrics?.expectancy}
              />
            )
          }
          activePositionsSection={
            <ActivePositionsPanel
              activeTradesCount={agentState.active_trades_count}
              recentExits={agentState.recent_exits}
              dailyPnL={agentState.daily_pnl}
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
          regimeSection={
            agentState.market_regime && (
              <MarketRegimePanel regime={agentState.market_regime} />
            )
          }
          riskMetricsSection={
            agentState.risk_metrics && (
              <RiskMetricsPanel riskMetrics={agentState.risk_metrics} />
            )
          }
          equityCurveSection={
            agentState.equity_curve && agentState.equity_curve.length > 0 && (
              <EquityCurvePanel equityCurve={agentState.equity_curve} />
            )
          }
          recentTradesSection={
            agentState.recent_exits && agentState.recent_exits.length > 0 && (
              <RecentTradesPanel
                recentExits={agentState.recent_exits}
                maxItems={8}
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
          marketPressureSection={
            agentState.buy_sell_pressure && (
              <MarketPressurePanel pressure={agentState.buy_sell_pressure} />
            )
          }
        />
      </div>
    )
  }

  // Standard layout (mobile, tablet, desktop)
  return (
    <div className="dashboard" data-chart-ready={isChartReady ? 'true' : 'false'}>
      {/* Market Closed Banner */}
      {marketStatus && !marketStatus.is_open && (
        <div className="market-closed-banner">
          <span className="market-closed-icon">🔴</span>
          <span className="market-closed-text">
            Market Closed ({marketStatus.close_reason})
            {marketStatus.next_open && (
              <> — Opens {formatNextOpen(marketStatus.next_open)}</>
            )}
          </span>
        </div>
      )}

      {renderHeader()}
      {renderStatusPanel()}
      {renderChart()}
      {renderRSI()}

      {/* Data Panels */}
      {agentState && (
        <DataPanelsContainer>
          {/* Pearl AI - Combined insights and AI status */}
          <PearlInsightsPanel
            insights={agentState.pearl_insights}
            suggestion={agentState.pearl_suggestion}
            aiStatus={agentState.ai_status}
            shadowCounters={agentState.shadow_counters}
            onAccept={async () => {
              try {
                const action = agentState.pearl_suggestion?.accept_action ||
                  agentState.pearl_insights?.shadow_metrics?.active_suggestion?.action
                if (action) {
                  await apiFetch('/api/pearl-suggestion/accept', {
                    method: 'POST',
                    body: JSON.stringify({ action }),
                  })
                }
              } catch (e) {
                console.error('Failed to accept Pearl insight:', e)
              }
            }}
            onDismiss={async () => {
              try {
                const key = agentState.pearl_suggestion?.cooldown_key ||
                  agentState.pearl_insights?.shadow_metrics?.active_suggestion?.id
                if (key) {
                  await apiFetch('/api/pearl-suggestion/dismiss', {
                    method: 'POST',
                    body: JSON.stringify({ cooldown_key: key }),
                  })
                }
              } catch (e) {
                console.error('Failed to dismiss Pearl insight:', e)
              }
            }}
          />
          {agentState.performance && (
            <PerformancePanel
              performance={agentState.performance}
              expectancy={agentState.risk_metrics?.expectancy}
            />
          )}
          {/* Active Positions Panel */}
          <ActivePositionsPanel
            activeTradesCount={agentState.active_trades_count}
            recentExits={agentState.recent_exits}
            dailyPnL={agentState.daily_pnl}
          />
          {agentState.risk_metrics && (
            <RiskMetricsPanel riskMetrics={agentState.risk_metrics} />
          )}
          {agentState.equity_curve && agentState.equity_curve.length > 0 && (
            <EquityCurvePanel equityCurve={agentState.equity_curve} />
          )}
          {agentState.challenge && (
            <ChallengePanel
              challenge={agentState.challenge}
              equityCurve={agentState.equity_curve}
            />
          )}
          {/* Market Pressure Panel */}
          {agentState.buy_sell_pressure && (
            <MarketPressurePanel pressure={agentState.buy_sell_pressure} />
          )}
          {/* Market Regime Panel */}
          {agentState.market_regime && (
            <MarketRegimePanel regime={agentState.market_regime} />
          )}
          {/* Signal Decisions Panel */}
          {(agentState.signal_rejections_24h || agentState.last_signal_decision) && (
            <SignalDecisionsPanel
              rejections={agentState.signal_rejections_24h || null}
              lastDecision={agentState.last_signal_decision || null}
            />
          )}
          {/* Config Panel */}
          {agentState.config && (
            <ConfigPanel config={agentState.config} />
          )}
          {/* System Health Panel */}
          {(agentState.cadence_metrics || agentState.gateway_status || agentState.connection_health || agentState.data_quality) && (
            <SystemHealthPanel
              cadenceMetrics={agentState.cadence_metrics || null}
              dataFresh={agentState.data_fresh || false}
              gatewayStatus={agentState.gateway_status}
              connectionHealth={agentState.connection_health}
              errorSummary={agentState.error_summary}
              dataQuality={agentState.data_quality}
            />
          )}
          {agentState.recent_exits && agentState.recent_exits.length > 0 && (
            <RecentTradesPanel
              recentExits={agentState.recent_exits}
              directionBreakdown={agentState.analytics?.direction_breakdown}
              statusBreakdown={agentState.analytics?.status_breakdown}
            />
          )}
          {agentState.analytics && (
            <AnalyticsPanel
              analytics={agentState.analytics}
              recentExits={agentState.recent_exits}
            />
          )}
          {/* P&L Calendar */}
          {agentState.recent_exits && agentState.recent_exits.length > 0 && (
            <PnLCalendarPanel recentExits={agentState.recent_exits} />
          )}
        </DataPanelsContainer>
      )}

      {/* Help Panel - Quick Reference */}
      <HelpPanel />
    </div>
  )
}

// Simple RSI Chart Component
function RSIChart({ data, barSpacing = 10 }: { data: IndicatorData[], barSpacing?: number }) {
  const containerRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return

    const chartHeight = Math.max(80, Math.min(120, window.innerHeight * 0.12))
    const { createChart, ColorType } = require('lightweight-charts')
    const chart = createChart(node, {
      width: node.clientWidth,
      height: chartHeight,
      layout: {
        background: { type: ColorType.Solid, color: '#0a0a0f' },
        textColor: '#8a94a6',
      },
      grid: {
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      rightPriceScale: {
        borderColor: '#2a2a3a',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        visible: true,
        borderColor: '#2a2a3a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,
        barSpacing: barSpacing,
        tickMarkFormatter: (time: number) => {
          const date = new Date(time * 1000)
          const hours = date.getHours().toString().padStart(2, '0')
          const minutes = date.getMinutes().toString().padStart(2, '0')
          return `${hours}:${minutes}`
        },
      },
    })

    const series = chart.addLineSeries({
      color: '#ab47bc',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
    })

    // Add overbought/oversold lines
    const ob = chart.addLineSeries({
      color: 'rgba(255, 82, 82, 0.8)',
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    const os = chart.addLineSeries({
      color: 'rgba(0, 230, 118, 0.8)',
      lineWidth: 1,
      lineStyle: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Set data
    series.setData(data)
    const obData = data.map(d => ({ time: d.time, value: 70 }))
    const osData = data.map(d => ({ time: d.time, value: 30 }))
    ob.setData(obData)
    os.setData(osData)

    const handleResize = () => {
      chart.applyOptions({
        width: node.clientWidth,
        height: Math.max(80, Math.min(120, window.innerHeight * 0.12)),
      })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [data, barSpacing])

  return (
    <div className="rsi-container">
      <span className="rsi-label">RSI(14)</span>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  )
}
