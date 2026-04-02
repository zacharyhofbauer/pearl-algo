/**
 * Pearl Panel Types - Consolidated interfaces for the Pearl AI panel
 * 
 * These types provide a cleaner, unified interface for Pearl panel data,
 * derived from the raw AgentState to reduce prop drilling and improve clarity.
 */

import type {
  AgentState,
  PearlFeedMessage,
  PearlSuggestion,
  PearlInsights,
  PearlAIHeartbeat,
  PearlAIDebugInfo,
} from '@/stores'

// ============================================================================
// Core Panel Data Types
// ============================================================================

export type PearlMode = 'off' | 'shadow' | 'live'

export interface PearlStatus {
  mode: PearlMode
  heartbeatRecent: boolean
  lastActivityTs: string | null
  mounted: boolean
  chatAvailable: boolean
  operatorLockEnabled: boolean | null
}

export interface TradingContext {
  pnl: number | null
  wins: number | null
  losses: number | null
  positions: number | null
  regime: string | null
  allowedDirection: string | null
  marketOpen: boolean | null
  dataFresh: boolean | null
  lastDecision: {
    action: string
    timestamp: string | null
  } | null
}

export interface PearlHeadline {
  text: string
  source: 'feed' | 'suggestion' | 'default'
  timestamp: string | null
}

// ============================================================================
// Unified Panel Data
// ============================================================================

export interface PearlPanelData {
  // Core status
  status: PearlStatus
  // Single headline (derived from feed or suggestion)
  headline: PearlHeadline
  // Simplified trading context
  tradingContext: TradingContext
  // Feed messages
  feed: PearlFeedMessage[]
  // Current suggestion (if any)
  suggestion: PearlSuggestion | null
  // Full insights (for shadow metrics history)
  insights: PearlInsights | null
  // Debug/heartbeat info
  heartbeat: PearlAIHeartbeat | null
  debug: PearlAIDebugInfo | null
}

// ============================================================================
// Metrics Types (loaded on demand)
// ============================================================================

export interface ModelMetrics {
  count: number
  tokens: number
  cost_usd: number
  avg_latency_ms: number
  error_rate: number
}

export interface MetricsSummary {
  period_hours: number
  total_requests: number
  total_tokens: number
  total_cost_usd: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
  cache_hit_rate: number
  error_rate: number
  fallback_rate: number
  by_endpoint: Record<string, ModelMetrics>
  by_model: Record<string, ModelMetrics>
}

export interface ResponseSourceDist {
  counts: Record<string, number>
  percentages: Record<string, number>
  total: number
  period_hours?: number
  period?: string
}

export interface CostSummary {
  today_usd: number
  month_usd: number
  limit_usd: number | null
}

export interface PearlMetrics {
  summary: MetricsSummary | null
  cost: CostSummary | null
  sources: ResponseSourceDist | null
  asOfMs: number | null
  loading: boolean
  error: string | null
}


// ============================================================================
// Chat Types
// ============================================================================

export interface ChatMessage {
  role: 'user' | 'pearl'
  text: string
  meta?: {
    complexity?: string
    source?: string
  }
}

export interface PearlChatResponse {
  response: string
  timestamp: string
  complexity: string
  source?: string
}

// ============================================================================
// Helper Functions - Derive unified data from AgentState
// ============================================================================

/**
 * Derive the overall Pearl mode from Pearl insights only.
 */
export function derivePearlMode(insights: PearlInsights | null): PearlMode {
  const shadowMetrics = insights?.shadow_metrics
  
  if (shadowMetrics?.mode === 'shadow') return 'shadow'
  return 'off'
}

/**
 * Derive the headline text from feed or suggestion
 */
export function deriveHeadline(
  feed: PearlFeedMessage[],
  suggestion: PearlSuggestion | null,
  insights: PearlInsights | null
): PearlHeadline {
  // Priority 1: Latest feed message
  const latestFeed = feed.length > 0 ? feed[feed.length - 1] : null
  if (latestFeed?.content) {
    return {
      text: latestFeed.content,
      source: 'feed',
      timestamp: latestFeed.timestamp || null,
    }
  }
  
  // Priority 2: Active suggestion
  const activeSuggestion = suggestion || insights?.shadow_metrics?.active_suggestion
  if (activeSuggestion?.message) {
    return {
      text: activeSuggestion.message,
      source: 'suggestion',
      timestamp: null,
    }
  }
  
  // Default
  return {
    text: 'Watching for opportunities…',
    source: 'default',
    timestamp: null,
  }
}

/**
 * Derive trading context from agent state
 */
export function deriveTradingContext(agentState: AgentState | null): TradingContext {
  if (!agentState) {
    return {
      pnl: null,
      wins: null,
      losses: null,
      positions: null,
      regime: null,
      allowedDirection: null,
      marketOpen: null,
      dataFresh: null,
      lastDecision: null,
    }
  }
  
  const regimeRaw = agentState.market_regime?.regime
  const regimeTrimmed = typeof regimeRaw === 'string' ? regimeRaw.trim() : ''
  const regimeNorm = regimeTrimmed.toLowerCase()
  const regime =
    regimeTrimmed && !['unknown', 'n/a', 'na', 'none'].includes(regimeNorm) ? regimeTrimmed : null

  const allowedDirectionRaw = agentState.market_regime?.allowed_direction
  const allowedDirectionTrimmed = typeof allowedDirectionRaw === 'string' ? allowedDirectionRaw.trim() : ''
  const allowedDirectionNorm = allowedDirectionTrimmed.toLowerCase()
  const allowedDirection =
    regime && allowedDirectionTrimmed && !['unknown', 'n/a', 'na', 'none'].includes(allowedDirectionNorm)
      ? allowedDirectionTrimmed
      : null
  
  return {
    pnl: typeof agentState.daily_pnl === 'number' ? agentState.daily_pnl : null,
    wins: typeof agentState.daily_wins === 'number' ? agentState.daily_wins : null,
    losses: typeof agentState.daily_losses === 'number' ? agentState.daily_losses : null,
    positions: typeof agentState.active_trades_count === 'number' ? agentState.active_trades_count : null,
    regime,
    allowedDirection,
    marketOpen: typeof agentState.futures_market_open === 'boolean' ? agentState.futures_market_open : null,
    dataFresh: typeof agentState.data_fresh === 'boolean' ? agentState.data_fresh : null,
    lastDecision: null,
  }
}

/**
 * Derive Pearl status from agent state and heartbeat
 */
export function derivePearlStatus(
  agentState: AgentState | null,
  heartbeat: PearlAIHeartbeat | null,
  feed: PearlFeedMessage[],
  nowMs: number
): PearlStatus {
  // Determine last activity timestamp
  const lastMessageTs = heartbeat?.last_message_time ||
    (feed.length > 0 ? feed[feed.length - 1]?.timestamp : null)
  const lastStateTs = heartbeat?.last_state_sync_time || heartbeat?.last_state_seen_time || null
  const lastActivityTs = lastMessageTs || lastStateTs
  
  // Check if heartbeat is recent (within 15 seconds)
  let heartbeatRecent = false
  if (lastActivityTs) {
    const t = Date.parse(lastActivityTs)
    if (Number.isFinite(t)) {
      heartbeatRecent = nowMs - t < 15000
    }
  }
  
  const mode = derivePearlMode(agentState?.pearl_insights || null)
  
  return {
    mode,
    heartbeatRecent,
    lastActivityTs,
    mounted: heartbeat?.mounted ?? false,
    chatAvailable: false,
    operatorLockEnabled: agentState?.operator_lock_enabled ?? null,
  }
}

/**
 * Create unified PearlPanelData from AgentState
 */
export function createPearlPanelData(
  agentState: AgentState | null,
  nowMs: number
): PearlPanelData {
  const feed = agentState?.pearl_feed || []
  const suggestion = agentState?.pearl_suggestion || null
  const insights = agentState?.pearl_insights || null
  const heartbeat: PearlAIHeartbeat | null = null
  const debug: PearlAIDebugInfo | null = null
  
  return {
    status: derivePearlStatus(agentState, heartbeat, feed, nowMs),
    headline: deriveHeadline(feed, suggestion, insights),
    tradingContext: deriveTradingContext(agentState),
    feed,
    suggestion: suggestion || insights?.shadow_metrics?.active_suggestion || null,
    insights,
    heartbeat,
    debug,
  }
}
