import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'

// Types for agent state
export interface AIStatus {
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

export interface ChallengeStatus {
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

export interface PeriodStats {
  pnl: number
  trades: number
  wins: number
  losses: number
  win_rate: number
  streak?: number
  streak_type?: string
}

export interface PerformanceStats {
  '24h': PeriodStats
  '72h': PeriodStats
  '30d': PeriodStats
}

export interface RecentExit {
  signal_id: string
  direction: string
  pnl: number
  exit_reason: string
  exit_time: string
  entry_time?: string
  entry_price?: number
  exit_price?: number
  entry_reason?: string
  duration_seconds?: number
}

export interface RiskMetrics {
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

export interface BuySellPressure {
  bias: 'buyers' | 'sellers' | 'mixed'
  strength: 'flat' | 'light' | 'moderate' | 'strong'
  score: number
  score_pct: number
  lookback_bars: number
  total_volume: number
  volume_ratio: number
}

export interface CadenceMetrics {
  cycle_duration_ms: number
  duration_p50_ms: number
  duration_p95_ms: number
  velocity_mode_active: boolean
  velocity_reason: string
  missed_cycles: number
  current_interval_seconds: number
  cadence_lag_ms: number
}

export interface MarketRegime {
  regime: string
  confidence: number
  allowed_direction: 'long' | 'short' | 'both'
}

export interface SignalRejections {
  direction_gating: number
  ml_filter: number
  circuit_breaker: number
  session_filter: number
  max_positions: number
}

export interface LastSignalDecision {
  signal_type: string
  ml_probability: number
  action: 'execute' | 'skip'
  reason: string
  timestamp: string | null
}

export interface ShadowCounters {
  would_block_total: number
  would_block_by_reason: Record<string, number>
  ml_would_skip: number
  ml_total_decisions: number
  ml_execute_rate: number
}

export interface GatewayStatus {
  process_running: boolean
  port_listening: boolean
  port: number
  status: 'online' | 'offline' | 'degraded'
}

export interface ConnectionHealth {
  connection_failures: number
  data_fetch_errors: number
  data_level: string
  consecutive_errors: number
  last_successful_fetch?: string | null
}

export interface ErrorSummary {
  session_error_count: number
  last_error: string | null
  last_error_time: string | null
}

export interface Config {
  symbol: string
  market: string
  timeframe: string
  scan_interval: number
  session_start: string
  session_end: string
  mode: 'live' | 'shadow' | 'paused' | 'stopped'
}

export interface DataQuality {
  latest_bar_age_minutes: number | null
  stale_threshold_minutes: number
  buffer_size: number | null
  buffer_target: number
  quiet_reason: string | null
  is_expected_stale: boolean
  is_stale: boolean
}

export interface EquityCurvePoint {
  time: number
  value: number
}

export interface AgentState {
  running: boolean
  paused: boolean
  daily_pnl: number
  daily_trades: number
  daily_wins: number
  daily_losses: number
  active_trades_count: number
  data_fresh: boolean
  ai_status: AIStatus | null
  challenge: ChallengeStatus | null
  recent_exits: RecentExit[]
  performance: PerformanceStats | null
  equity_curve: EquityCurvePoint[]
  risk_metrics: RiskMetrics | null
  buy_sell_pressure: BuySellPressure | null
  cadence_metrics: CadenceMetrics | null
  market_regime: MarketRegime | null
  signal_rejections_24h: SignalRejections | null
  last_signal_decision: LastSignalDecision | null
  shadow_counters: ShadowCounters | null
  gateway_status: GatewayStatus | null
  connection_health: ConnectionHealth | null
  error_summary: ErrorSummary | null
  config: Config | null
  data_quality: DataQuality | null
}

interface AgentStore {
  // State
  agentState: AgentState | null
  lastUpdated: Date | null
  isLoading: boolean
  error: string | null

  // Actions
  setAgentState: (state: Partial<AgentState>) => void
  updateFromWebSocket: (data: Partial<AgentState>) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  reset: () => void
}

const initialAgentState: AgentState = {
  running: false,
  paused: false,
  daily_pnl: 0,
  daily_trades: 0,
  daily_wins: 0,
  daily_losses: 0,
  active_trades_count: 0,
  data_fresh: false,
  ai_status: null,
  challenge: null,
  recent_exits: [],
  performance: null,
  equity_curve: [],
  risk_metrics: null,
  buy_sell_pressure: null,
  cadence_metrics: null,
  market_regime: null,
  signal_rejections_24h: null,
  last_signal_decision: null,
  shadow_counters: null,
  gateway_status: null,
  connection_health: null,
  error_summary: null,
  config: null,
  data_quality: null,
}

export const useAgentStore = create<AgentStore>()(
  subscribeWithSelector((set) => ({
    // Initial state
    agentState: null,
    lastUpdated: null,
    isLoading: true,
    error: null,

    // Actions
    setAgentState: (state) =>
      set((prev) => ({
        agentState: prev.agentState
          ? { ...prev.agentState, ...state }
          : { ...initialAgentState, ...state },
        lastUpdated: new Date(),
        isLoading: false,
        error: null,
      })),

    updateFromWebSocket: (data) =>
      set((prev) => ({
        agentState: prev.agentState
          ? { ...prev.agentState, ...data }
          : { ...initialAgentState, ...data },
        lastUpdated: new Date(),
      })),

    setLoading: (loading) => set({ isLoading: loading }),

    setError: (error) => set({ error, isLoading: false }),

    reset: () =>
      set({
        agentState: null,
        lastUpdated: null,
        isLoading: true,
        error: null,
      }),
  }))
)

// Selectors for common use cases
export const selectIsRunning = (state: AgentStore) => state.agentState?.running ?? false
export const selectDailyPnL = (state: AgentStore) => state.agentState?.daily_pnl ?? 0
export const selectActiveTradesCount = (state: AgentStore) => state.agentState?.active_trades_count ?? 0
export const selectPerformance = (state: AgentStore) => state.agentState?.performance
export const selectChallenge = (state: AgentStore) => state.agentState?.challenge
export const selectAIStatus = (state: AgentStore) => state.agentState?.ai_status
export const selectCadenceMetrics = (state: AgentStore) => state.agentState?.cadence_metrics
export const selectGatewayStatus = (state: AgentStore) => state.agentState?.gateway_status
