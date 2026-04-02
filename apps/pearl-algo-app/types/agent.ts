// Types for agent state and related structures
// Extracted from stores/agentStore.ts for better organization

export interface TvPaperConsistency {
  met: boolean
  best_day_pnl: number
  best_day_pct: number
  best_day_date: string | null
}

export interface TvPaperMinDays {
  met: boolean
  days_traded: number
  days_required: number
}

export interface TvPaperExtensions {
  stage: 'evaluation' | 'sim_funded' | 'live'
  eod_high_water_mark?: number
  current_drawdown_floor?: number
  drawdown_locked?: boolean
  consistency?: TvPaperConsistency
  min_days?: TvPaperMinDays
  trading_days_count?: number
  max_contracts_mini?: number
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
  attempt_number?: number
  /** TV Paper-specific extensions (present only for prop firm accounts) */
  tv_paper?: TvPaperExtensions
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
  'yesterday': PeriodStats
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
  // ML and regime data
  ml_probability?: number
  regime_at_entry?: string
  target_points?: number
}

export interface TopLoss {
  signal_id: string
  pnl: number
  exit_reason: string
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
  // Exposure metrics
  max_concurrent_positions_peak?: number
  max_stop_risk_exposure?: number
  top_losses?: TopLoss[]
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
  circuit_breaker: number
  session_filter: number
  max_positions: number
}

// Execution state - armed/disarmed status
export interface ExecutionState {
  enabled: boolean
  armed: boolean
  mode: 'live' | 'paper' | 'shadow'
  disarm_reason?: string
}

// Circuit breaker detailed status
export interface CircuitBreakerStatus {
  active: boolean
  in_cooldown: boolean
  cooldown_remaining_seconds?: number
  rolling_win_rate?: number
  trip_reason?: string
  trips_today: number
}

// Session context
export interface SessionContext {
  current_session: string  // 'premarket' | 'morning' | 'midday' | 'afternoon' | 'extended' | 'closed'
  session_start_time?: string
  session_end_time?: string
  session_pnl: number
  session_trades: number
  session_wins: number
  time_until_next_session_seconds?: number
}

// Signal activity tracking
export interface SignalActivity {
  last_signal_time?: string
  minutes_since_last_signal?: number
  signals_last_hour: number
  signals_today: number
  quiet_reason?: string
  quiet_period_minutes?: number
  signal_breakdown: {
    long_signals: number
    short_signals: number
    executed: number
    blocked: number
  }
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

// Analytics types
export interface SessionPerformance {
  id: string
  name: string
  pnl: number
  wins: number
  losses: number
  win_rate: number
}

export interface HourStats {
  hour: number
  hour_label: string
  pnl: number
  trades: number
  win_rate: number
}

export interface DurationStats {
  id: string
  name: string
  pnl: number
  wins: number
  losses: number
  win_rate: number
}

export interface DirectionBreakdown {
  long: { count: number; pnl: number }
  short: { count: number; pnl: number }
}

export interface StatusBreakdown {
  generated: number
  entered: number
  exited: number
  cancelled: number
}

export interface AnalyticsData {
  session_performance: SessionPerformance[]
  best_hours: HourStats[]
  worst_hours: HourStats[]
  hold_duration: DurationStats[]
  direction_breakdown: DirectionBreakdown
  status_breakdown: StatusBreakdown
}

export interface PearlSuggestion {
  message: string
  action: string
  accept_action?: string
  cooldown_key?: string
  id?: string
}

export interface PearlShadowMetrics {
  total_suggestions: number
  suggestions_followed: number
  suggestions_dismissed: number
  suggestions_expired: number
  total_would_have_saved: number
  total_would_have_made: number
  net_shadow_impact: number
  accuracy_rate: number
  correct_suggestions: number
  incorrect_suggestions: number
  by_type: Record<string, {
    count: number
    followed: number
    dismissed: number
    would_have_saved: number
    would_have_made: number
  }>
  recent_suggestions: Array<{
    id: string
    type: string
    message: string
    outcome: string
    would_have_saved: number | null
    would_have_made: number | null
    timestamp: string
  }>
  active_suggestion: {
    id: string
    type: string
    message: string
    action: string
    timestamp: string
    pnl_at_suggestion: number
  } | null
  mode: 'shadow' | 'live'
}

export interface PearlInsights {
  // Current suggestion (if any)
  current_suggestion: PearlSuggestion | null

  // Shadow tracking metrics
  shadow_metrics: PearlShadowMetrics | null

  // AI status
  ai_enabled: boolean
  last_insight_time: string | null

  // Quick stats for display
  suggestions_today: number
  accuracy_7d: number
}

export interface AccountConfig {
  display_name: string
  badge: string
  badge_color: string
  telegram_prefix: string
  description: string
}

export interface PearlFeedMessage {
  id: string
  content: string
  type: string
  priority?: string | null
  timestamp?: string | null
  trade_id?: string | null
  metadata?: any
}

export interface PearlAIDebugInfo {
  routing?: any
  model_used?: string | null
  tool_calls?: any[]
  tool_results?: any[]
  input_tokens?: number | null
  output_tokens?: number | null
  latency_ms?: number | null
  cache_hit?: boolean | null
  fallback_used?: boolean | null
  response_source?: string | null
}

export interface PearlAIHeartbeat {
  enabled: boolean
  mounted?: boolean
  feed_total?: number
  last_message_time?: string | null
  last_message_type?: string | null
  last_state_seen_time?: string | null
  last_state_sync_time?: string | null
  last_state_sync_error?: string | null
}

export interface AgentState {
  running: boolean
  paused: boolean
  daily_pnl: number
  daily_trades: number
  daily_wins: number
  daily_losses: number
  active_trades_count: number
  /** Aggregate unrealized P&L across open (virtual) trades */
  active_trades_unrealized_pnl?: number | null
  futures_market_open: boolean
  data_fresh: boolean
  challenge: ChallengeStatus | null
  recent_exits: RecentExit[]
  performance: PerformanceStats | null
  equity_curve: EquityCurvePoint[]
  risk_metrics: RiskMetrics | null
  buy_sell_pressure: BuySellPressure | null
  cadence_metrics: CadenceMetrics | null
  market_regime: MarketRegime | null
  signal_rejections_24h: SignalRejections | null
  gateway_status: GatewayStatus | null
  connection_health: ConnectionHealth | null
  error_summary: ErrorSummary | null
  config: Config | null
  data_quality: DataQuality | null
  analytics: AnalyticsData | null
  pearl_suggestion: PearlSuggestion | null
  pearl_insights: PearlInsights | null
  /** Recent Pearl AI feed messages (narrations, insights, alerts, chat responses) */
  pearl_feed?: PearlFeedMessage[]
  /** Whether operator passphrase locking is configured on the API server */
  operator_lock_enabled?: boolean
  // New fields for enhanced transparency
  execution_state: ExecutionState | null
  circuit_breaker: CircuitBreakerStatus | null
  session_context: SessionContext | null
  signal_activity: SignalActivity | null
  openclaw_status?: { status: string; port?: number } | null
}

/**
 * Lightweight runtime validation for incoming WebSocket/API data.
 * Checks that data is an object and has expected structure.
 */
export function validateAgentStateData(data: unknown): data is Partial<AgentState> & { accounts?: Record<string, AccountConfig> } {
  if (typeof data !== 'object' || data === null) {
    return false
  }
  
  // Basic shape check - at minimum, it should be an object
  // More specific validation can be added later if needed
  return true
}

/**
 * Merge incoming agent state data with existing state.
 * Handles accounts extraction and state merging safely.
 */
export function mergeAgentState(
  prev: AgentState | null,
  incoming: Partial<AgentState> & { accounts?: Record<string, AccountConfig> },
  initialAgentState: AgentState
): { agentState: AgentState; accounts?: Record<string, AccountConfig> } {
  // Extract accounts if present
  const { accounts, ...agentFields } = incoming
  
  // Merge agent state
  const mergedAgentState: AgentState = prev
    ? { ...prev, ...agentFields }
    : { ...initialAgentState, ...agentFields }
  
  const result: { agentState: AgentState; accounts?: Record<string, AccountConfig> } = {
    agentState: mergedAgentState,
  }
  
  if (accounts !== undefined) {
    result.accounts = accounts
  }
  
  return result
}
