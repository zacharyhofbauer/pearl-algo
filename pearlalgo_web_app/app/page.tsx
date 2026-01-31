'use client'

import { useEffect, useState, useRef } from 'react'
import Image from 'next/image'
import CandlestickChart from '@/components/CandlestickChart'
import DataPanelsContainer from '@/components/DataPanelsContainer'
import PerformancePanel from '@/components/PerformancePanel'
import ChallengePanel from '@/components/ChallengePanel'
import AIStatusPanel from '@/components/AIStatusPanel'
import RecentTradesPanel from '@/components/RecentTradesPanel'
import PearlSuggestionsPanel from '@/components/PearlSuggestionsPanel'
import EquityCurvePanel from '@/components/EquityCurvePanel'
import RiskMetricsPanel from '@/components/RiskMetricsPanel'
import HelpPanel from '@/components/HelpPanel'
import MarketPressurePanel from '@/components/MarketPressurePanel'
import SystemHealthPanel from '@/components/SystemHealthPanel'
import ConfigPanel from '@/components/ConfigPanel'
import MarketRegimePanel from '@/components/MarketRegimePanel'
import SignalDecisionsPanel from '@/components/SignalDecisionsPanel'
import AnalyticsPanel from '@/components/AnalyticsPanel'
import UltrawideLayout from '@/components/UltrawideLayout'
import { useViewportType } from '@/hooks/useViewportType'
import type { IChartApi } from 'lightweight-charts'

interface CandleData {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

interface IndicatorData {
  time: number
  value: number
}

interface Indicators {
  ema9?: IndicatorData[]
  ema21?: IndicatorData[]
  vwap?: IndicatorData[]
  rsi?: IndicatorData[]
}

interface MarkerData {
  time: number
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle'
  text: string
}

// AI/ML Status
interface AIStatus {
  bandit_mode: 'off' | 'shadow' | 'live'
  contextual_mode: 'off' | 'shadow' | 'live'
  ml_filter: {
    enabled: boolean
    mode: string
    lift: {
      lift_ok?: boolean
      lift_win_rate?: number
      lift_avg_pnl?: number
    }
  }
  direction_gating: {
    enabled: boolean
    blocks: number
    shadow_regime: number
    shadow_trigger: number
  }
}

// Challenge Status
interface ChallengeStatus {
  enabled: boolean
  current_balance: number
  pnl: number
  trades: number
  wins: number
  win_rate: number
  drawdown_risk_pct: number
  outcome: 'active' | 'pass' | 'fail'
  profit_target: number
  max_drawdown: number
}

// Performance Stats
interface PeriodStats {
  pnl: number
  trades: number
  wins: number
  losses: number
  win_rate: number
  streak?: number
  streak_type?: string
}

interface PerformanceStats {
  '24h': PeriodStats
  '72h': PeriodStats
  '30d': PeriodStats
}

// Recent Exit (enhanced with full trade details)
interface RecentExit {
  signal_id: string
  direction: string
  pnl: number
  exit_reason: string
  exit_time: string
  // NEW: Full trade details
  entry_time?: string
  entry_price?: number
  exit_price?: number
  entry_reason?: string
  duration_seconds?: number
}

// Pearl Suggestion
interface PearlSuggestion {
  message: string
  action: string
}

// Equity Curve Point
interface EquityCurvePoint {
  time: number
  value: number
}

// Risk Metrics
interface RiskMetrics {
  max_drawdown: number
  max_drawdown_pct: number
  sharpe_ratio: number | null
  profit_factor: number | null
  avg_win: number
  avg_loss: number
  avg_rr: number | null
  largest_win: number
  largest_loss: number
  expectancy: number
}

// Buy/Sell Pressure
interface BuySellPressure {
  bias: 'buyers' | 'sellers' | 'mixed'
  strength: 'flat' | 'light' | 'moderate' | 'strong'
  score: number
  score_pct: number
  lookback_bars: number
  total_volume: number
  volume_ratio: number
}

// Cadence/System Health Metrics
interface CadenceMetrics {
  cycle_duration_ms: number
  duration_p50_ms: number
  duration_p95_ms: number
  velocity_mode_active: boolean
  velocity_reason: string
  missed_cycles: number
  current_interval_seconds: number
  cadence_lag_ms: number
}

// Market Regime
interface MarketRegime {
  regime: string
  confidence: number
  allowed_direction: 'long' | 'short' | 'both'
}

// Signal Rejections
interface SignalRejections {
  direction_gating: number
  ml_filter: number
  circuit_breaker: number
  session_filter: number
  max_positions: number
}

// Last Signal Decision
interface LastSignalDecision {
  signal_type: string
  ml_probability: number
  action: 'execute' | 'skip'
  reason: string
  timestamp: string | null
}

// Shadow Counters
interface ShadowCounters {
  would_block_total: number
  would_block_by_reason: Record<string, number>
  ml_would_skip: number
  ml_total_decisions: number
  ml_execute_rate: number
}

// Gateway Status
interface GatewayStatus {
  process_running: boolean
  port_listening: boolean
  port: number
  status: 'online' | 'offline' | 'degraded'
}

// Connection Health
interface ConnectionHealth {
  connection_failures: number
  data_fetch_errors: number
  data_level: string
  consecutive_errors: number
  last_successful_fetch?: string | null
}

// Error Summary
interface ErrorSummary {
  session_error_count: number
  last_error: string | null
  last_error_time: string | null
}

// Config
interface Config {
  symbol: string
  market: string
  timeframe: string
  scan_interval: number
  session_start: string
  session_end: string
  mode: 'live' | 'shadow' | 'paused' | 'stopped'
}

// Data Quality
interface DataQuality {
  latest_bar_age_minutes: number | null
  stale_threshold_minutes: number
  buffer_size: number | null
  buffer_target: number
  quiet_reason: string | null
  is_expected_stale: boolean
  is_stale: boolean
}

// Analytics Data
interface SessionPerformance {
  id: string
  name: string
  pnl: number
  wins: number
  losses: number
  win_rate: number
}

interface HourStats {
  hour: number
  hour_label: string
  pnl: number
  trades: number
  win_rate: number
}

interface DurationStats {
  id: string
  name: string
  pnl: number
  wins: number
  losses: number
  win_rate: number
}

interface DirectionBreakdown {
  long: { count: number; pnl: number }
  short: { count: number; pnl: number }
}

interface StatusBreakdown {
  generated: number
  entered: number
  exited: number
  cancelled: number
}

interface AnalyticsData {
  session_performance: SessionPerformance[]
  best_hours: HourStats[]
  worst_hours: HourStats[]
  hold_duration: DurationStats[]
  direction_breakdown: DirectionBreakdown
  status_breakdown: StatusBreakdown
}

interface AgentState {
  running: boolean
  paused: boolean
  daily_pnl: number
  daily_trades: number
  daily_wins: number
  daily_losses: number
  active_trades_count: number
  data_fresh?: boolean
  // Existing fields
  ai_status?: AIStatus
  challenge?: ChallengeStatus | null
  recent_exits?: RecentExit[]
  performance?: PerformanceStats
  pearl_suggestion?: PearlSuggestion | null
  equity_curve?: EquityCurvePoint[]
  risk_metrics?: RiskMetrics
  // NEW: Transparency panels data
  buy_sell_pressure?: BuySellPressure | null
  cadence_metrics?: CadenceMetrics | null
  market_regime?: MarketRegime | null
  signal_rejections_24h?: SignalRejections | null
  last_signal_decision?: LastSignalDecision | null
  shadow_counters?: ShadowCounters | null
  // NEW: System health extended
  gateway_status?: GatewayStatus | null
  connection_health?: ConnectionHealth | null
  error_summary?: ErrorSummary | null
  config?: Config | null
  data_quality?: DataQuality | null
}

// Market Status
interface MarketStatus {
  is_open: boolean
  close_reason: string | null
  next_open: string | null
  current_time_et: string
}

// API URL is determined at runtime based on where the page is loaded from
// Override options: NEXT_PUBLIC_API_URL env var, or ?api_port=8001 URL param
function getApiUrl(): string {
  // Check for environment variable override first
  const envUrl = process.env.NEXT_PUBLIC_API_URL
  if (envUrl) return envUrl

  if (typeof window === 'undefined') return 'http://localhost:8000' // SSR fallback
  const hostname = window.location.hostname

  // Check URL params for API port override (useful for testing different ports)
  const urlParams = new URLSearchParams(window.location.search)
  const apiPort = urlParams.get('api_port')
  if (apiPort) return `http://localhost:${apiPort}`

  // Use relative URLs on public domain (pearlalgo.io), localhost:8000 for local dev
  return ['localhost', '127.0.0.1'].includes(hostname) ? 'http://localhost:8000' : ''
}
const REFRESH_INTERVAL = 10000 // 10 seconds
type Timeframe = '1m' | '5m' | '15m' | '1h'

// Minimum bars to request for a full chart
const MIN_BARS = 150

// Fetch 72 hours (3 days) of markers for complete trade history
const MARKER_HOURS = 72

export default function PearlAlgoWebApp() {
  const [candles, setCandles] = useState<CandleData[]>([])
  const [indicators, setIndicators] = useState<Indicators>({})
  const [markers, setMarkers] = useState<MarkerData[]>([])
  const [agentState, setAgentState] = useState<AgentState | null>(null)
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [isLive, setIsLive] = useState(false)
  const [timeframe, setTimeframe] = useState<Timeframe>('5m')
  const [barCount, setBarCount] = useState(MIN_BARS)
  const [barSpacing, setBarSpacing] = useState(10)
  const [mainChartApi, setMainChartApi] = useState<IChartApi | null>(null)
  const [marketStatus, setMarketStatus] = useState<MarketStatus | null>(null)
  const lastDataHash = useRef<string>('')

  // Viewport detection for ultrawide layout
  const viewport = useViewportType()

  // Responsive bar spacing - smaller on mobile
  const getBarSpacing = () => {
    if (typeof window === 'undefined') return 10
    return window.innerWidth < 768 ? 6 : 10
  }

  // Calculate bar count based on viewport width - always request enough to fill chart
  const calculateBarCount = () => {
    if (typeof window === 'undefined') return MIN_BARS
    const width = window.innerWidth
    const barSpacing = getBarSpacing()
    const priceScaleWidth = 60
    const availableWidth = width - priceScaleWidth - 40
    const visibleBars = Math.floor(availableWidth / barSpacing)
    // Request 50% more bars than visible to allow scrolling, with minimum
    return Math.max(MIN_BARS, Math.floor(visibleBars * 1.5))
  }

  // Update bar count and spacing on resize
  useEffect(() => {
    const update = () => {
      setBarSpacing(getBarSpacing())
      setBarCount(calculateBarCount())
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  // Reset state when timeframe changes to force full refresh
  useEffect(() => {
    lastDataHash.current = ''
    setLoading(true)
    setCandles([])
    setIndicators({})
  }, [timeframe])

  const fetchData = async (tf: Timeframe, bars: number) => {
    try {
      // Ensure we always request at least MIN_BARS
      const requestBars = Math.max(MIN_BARS, bars)
      
      // Fetch all data in parallel
      const apiUrl = getApiUrl()
      const [candlesRes, indicatorsRes, markersRes, stateRes, marketStatusRes, analyticsRes] = await Promise.all([
        fetch(`${apiUrl}/api/candles?symbol=MNQ&timeframe=${tf}&bars=${requestBars}`),
        fetch(`${apiUrl}/api/indicators?symbol=MNQ&timeframe=${tf}&bars=${requestBars}`),
        fetch(`${apiUrl}/api/markers?hours=${MARKER_HOURS}`),
        fetch(`${apiUrl}/api/state`),
        fetch(`${apiUrl}/api/market-status`),
        fetch(`${apiUrl}/api/analytics`).catch(() => null),  // Analytics is optional
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
      if (dataHash !== lastDataHash.current) {
        lastDataHash.current = dataHash
        setCandles(candlesData)
        setIndicators(indicatorsData)
        setMarkers(filteredMarkers)
      }

      if (stateData && !stateData.error) {
        setAgentState(stateData)
      }

      // Set analytics data (optional - may not be available)
      if (analyticsRes && analyticsRes.ok) {
        try {
          const analyticsData = await analyticsRes.json()
          setAnalytics(analyticsData)
        } catch {
          // Ignore analytics parsing errors
        }
      }

      setLastUpdate(new Date())
      setIsLive(true)
      setError(null)
      
      // Only clear loading if we have sufficient data
      if (candlesData.length >= MIN_BARS * 0.8) {
        setLoading(false)
      }
    } catch (err) {
      console.error('Failed to fetch data:', err)
      setError(err instanceof Error ? err.message : 'Failed to fetch')
      setIsLive(false)
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData(timeframe, barCount)
    const interval = setInterval(() => fetchData(timeframe, barCount), REFRESH_INTERVAL)
    return () => clearInterval(interval)
  }, [timeframe, barCount])

  const formatTime = (date: Date | null) => {
    if (!date) return '--:--'
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  }

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  // Track if chart is fully loaded (for screenshot detection)
  const isChartReady = !loading && !error && candles.length > 0

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

  // Common header component
  const renderHeader = () => (
    <header className="header">
      <div className="title-group">
        <Image src="/logo.png" alt="PEARL" width={28} height={28} className="logo" priority />
        <div className="title-text">
          <h1>
            <span className="symbol">MNQ</span>
            <span className="page-name">Pearl Algo Web App</span>
          </h1>
        </div>
        {/* Market Status Badge */}
        {marketStatus && (
          <div className={`market-status-badge ${marketStatus.is_open ? 'open' : 'closed'}`}>
            <span className="market-status-dot"></span>
            {marketStatus.is_open ? 'Market Open' : 'Market Closed'}
          </div>
        )}
      </div>
      {/* Timeframe Selector */}
      <div className="timeframe-selector">
        {(['1m', '5m', '15m', '1h'] as Timeframe[]).map((tf) => (
          <button
            key={tf}
            className={timeframe === tf ? 'active' : ''}
            onClick={() => setTimeframe(tf)}
          >
            {tf}
          </button>
        ))}
      </div>
      <div className="status">
        <span className={`status-dot ${isLive ? '' : 'offline'}`}></span>
        <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
          {isLive ? 'Live' : 'Cached'} • {formatTime(lastUpdate)}
        </span>
      </div>
    </header>
  )

  // Common status panel component
  const renderStatusPanel = () => (
    (agentState || candles.length > 0) && (
      <div className="status-panel">
        {/* Current Price */}
        {candles.length > 0 && (
          <div className="stat price-stat">
            <span className="stat-label">Price</span>
            <span className={`stat-value price-value ${candles[candles.length-1]?.close >= candles[candles.length-1]?.open ? 'positive' : 'negative'}`}>
              {candles[candles.length-1]?.close.toFixed(2)}
            </span>
          </div>
        )}
        {agentState && (
          <>
            <div className="stat">
              <span className="stat-label">Agent</span>
              <span className={`stat-value ${agentState.running ? 'positive' : 'negative'}`}>
                {agentState.running ? (agentState.paused ? '⏸️ Paused' : '🟢 Running') : '🔴 Stopped'}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Day P&L</span>
              <span className={`stat-value ${agentState.daily_pnl >= 0 ? 'positive' : 'negative'}`}>
                {formatPnL(agentState.daily_pnl)}
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Trades</span>
              <span className="stat-value">
                {agentState.daily_wins}W / {agentState.daily_losses}L
              </span>
            </div>
            <div className="stat">
              <span className="stat-label">Open Pos</span>
              <span className={`stat-value ${agentState.active_trades_count > 0 ? 'highlight' : ''}`}>
                {agentState.active_trades_count}
              </span>
            </div>
          </>
        )}
        {/* Indicator Legend */}
        <div className="indicator-legend">
          <span className="legend-item"><span className="legend-color ema9"></span>EMA9</span>
          <span className="legend-item"><span className="legend-color ema21"></span>EMA21</span>
          <span className="legend-item"><span className="legend-color vwap"></span>VWAP</span>
        </div>
        {/* Marker Legend */}
        <div className="marker-legend">
          <span className="legend-item">
            <span className="marker-icon entry-long">▲</span>Long
          </span>
          <span className="legend-item">
            <span className="marker-icon entry-short">▼</span>Short
          </span>
          <span className="legend-item">
            <span className="marker-icon exit-win">●</span>Win
          </span>
          <span className="legend-item">
            <span className="marker-icon exit-loss">●</span>Loss
          </span>
        </div>
      </div>
    )
  )

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
        {loading && (
          <div className="loading-screen">
            <img src="/logo.png" alt="PEARL" className="loading-logo" />
            <div className="loading-text">Loading Live Data...</div>
            <div className="loading-spinner"></div>
          </div>
        )}
        {error && !loading && (
          <div className="no-data-container">
            <img src="/logo.png" alt="PEARL" className="no-data-logo" />
            <div className="no-data-title">No Live Data</div>
            <div className="no-data-message">{error}</div>
            <div className="no-data-hint">
              Start the Market Agent to see real-time data
            </div>
          </div>
        )}
        {!loading && !error && candles.length > 0 && (
          <CandlestickChart
            data={candles}
            indicators={indicators}
            markers={markers}
            barSpacing={barSpacing}
            onChartReady={setMainChartApi}
          />
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

  // Ultrawide layout for Xeneon Edge (2560x720)
  if (viewport.isUltrawide && agentState) {
    return (
      <div className={`dashboard ultrawide-mode`} data-chart-ready={isChartReady ? 'true' : 'false'}>
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

        <UltrawideLayout
          chartSection={renderChart()}
          rsiSection={renderRSI()}
          performanceSection={
            agentState.performance && (
              <PerformancePanel
                performance={agentState.performance}
                expectancy={agentState.risk_metrics?.expectancy}
              />
            )
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
          aiStatusSection={
            agentState.ai_status && (
              <AIStatusPanel
                aiStatus={agentState.ai_status}
                shadowCounters={agentState.shadow_counters}
              />
            )
          }
          recentTradesSection={
            agentState.recent_exits && agentState.recent_exits.length > 0 && (
              <RecentTradesPanel recentExits={agentState.recent_exits} maxItems={5} />
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
          {agentState.performance && (
            <PerformancePanel
              performance={agentState.performance}
              expectancy={agentState.risk_metrics?.expectancy}
            />
          )}
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
          {/* NEW: Market Pressure Panel */}
          {agentState.buy_sell_pressure && (
            <MarketPressurePanel pressure={agentState.buy_sell_pressure} />
          )}
          {/* NEW: Market Regime Panel */}
          {agentState.market_regime && (
            <MarketRegimePanel regime={agentState.market_regime} />
          )}
          {/* NEW: Signal Decisions Panel */}
          {(agentState.signal_rejections_24h || agentState.last_signal_decision) && (
            <SignalDecisionsPanel
              rejections={agentState.signal_rejections_24h || null}
              lastDecision={agentState.last_signal_decision || null}
            />
          )}
          {/* NEW: Config Panel */}
          {agentState.config && (
            <ConfigPanel config={agentState.config} />
          )}
          {/* NEW: System Health Panel */}
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
          {agentState.ai_status && (
            <AIStatusPanel
              aiStatus={agentState.ai_status}
              shadowCounters={agentState.shadow_counters}
            />
          )}
          {agentState.recent_exits && agentState.recent_exits.length > 0 && (
            <RecentTradesPanel
              recentExits={agentState.recent_exits}
              directionBreakdown={analytics?.direction_breakdown}
              statusBreakdown={analytics?.status_breakdown}
            />
          )}
          {analytics && (
            <AnalyticsPanel analytics={analytics} />
          )}
          {agentState.pearl_suggestion && (
            <PearlSuggestionsPanel
              suggestion={agentState.pearl_suggestion}
              onAccept={() => console.log('Suggestion accepted')}
              onDismiss={() => console.log('Suggestion dismissed')}
            />
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
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<any>(null)

  // Calculate responsive height
  const getChartHeight = () => {
    if (typeof window === 'undefined') return 120
    return Math.max(80, Math.min(120, window.innerHeight * 0.12))
  }

  useEffect(() => {
    if (!containerRef.current) return

    const chartHeight = getChartHeight()
    const { createChart, ColorType } = require('lightweight-charts')
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
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
        rightOffset: 8,  // Match main chart
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

    // Add overbought/oversold lines (more visible)
    const ob = chart.addLineSeries({ 
      color: 'rgba(255, 82, 82, 0.8)', 
      lineWidth: 1, 
      lineStyle: 2,  // Dashed
      priceLineVisible: false, 
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    const os = chart.addLineSeries({ 
      color: 'rgba(0, 230, 118, 0.8)', 
      lineWidth: 1, 
      lineStyle: 2,  // Dashed
      priceLineVisible: false, 
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    chartRef.current = { chart, series, ob, os }

    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: getChartHeight(),
        })
      }
    }
    window.addEventListener('resize', handleResize)
    return () => { window.removeEventListener('resize', handleResize); chart.remove() }
  }, [barSpacing])

  useEffect(() => {
    if (!chartRef.current || !data?.length) return
    chartRef.current.series.setData(data)
    
    // Overbought (70) and oversold (30) lines
    const obData = data.map(d => ({ time: d.time, value: 70 }))
    const osData = data.map(d => ({ time: d.time, value: 30 }))
    chartRef.current.ob.setData(obData)
    chartRef.current.os.setData(osData)
  }, [data])

  return (
    <div className="rsi-container">
      <span className="rsi-label">RSI(14)</span>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  )
}
