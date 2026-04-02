/**
 * Zod Validation Schemas
 *
 * Runtime validation for WebSocket messages and API responses.
 * These catch malformed data before it corrupts Zustand state.
 */

import { z } from 'zod'

// ── WebSocket Message Schemas ───────────────────────────────────────────────

const WsStateMessage = z.object({
  type: z.enum(['initial_state', 'state_update', 'full_refresh']),
  data: z.record(z.string(), z.unknown()).nullable().optional(),
})

const WsControlMessage = z.object({
  type: z.enum(['pong', 'auth_ok']),
})

const WsErrorMessage = z.object({
  type: z.enum(['error', 'auth_error']),
  message: z.string().optional(),
  detail: z.unknown().optional(),
})

export const WebSocketMessageSchema = z.union([
  WsStateMessage,
  WsControlMessage,
  WsErrorMessage,
])

export type WebSocketMessage = z.infer<typeof WebSocketMessageSchema>

// ── Agent State Partial Schema (for WS state updates) ───────────────────────
// Intentionally loose — validates shape, not every field.
// This prevents crashes from completely malformed payloads while allowing
// the backend to add new fields freely.

export const AgentStatePartialSchema = z.object({
  running: z.boolean().optional(),
  paused: z.boolean().optional(),
  daily_pnl: z.number().optional(),
  daily_trades: z.number().optional(),
  daily_wins: z.number().optional(),
  daily_losses: z.number().optional(),
  active_trades_count: z.number().optional(),
  active_trades_unrealized_pnl: z.number().nullable().optional(),
  futures_market_open: z.boolean().optional(),
  data_fresh: z.boolean().optional(),
  config: z.object({
    symbol: z.string(),
    market: z.string(),
    timeframe: z.string(),
    scan_interval: z.number(),
    session_start: z.string(),
    session_end: z.string(),
    mode: z.enum(['live', 'shadow', 'paused', 'stopped']),
  }).nullable().optional(),
  // Allow any additional fields (backend may add new ones)
}).passthrough()

// ── Chart Data Schemas ──────────────────────────────────────────────────────

export const CandleDataSchema = z.object({
  time: z.number(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().optional(),
})

export const CandleArraySchema = z.array(CandleDataSchema)

export const MarkerDataSchema = z.object({
  time: z.number(),
  position: z.enum(['aboveBar', 'belowBar']),
  color: z.string(),
  shape: z.enum(['arrowUp', 'arrowDown', 'circle']),
  text: z.string(),
  kind: z.enum(['entry', 'exit']).optional(),
  signal_id: z.string().optional(),
  direction: z.string().optional(),
  entry_price: z.number().optional(),
  exit_price: z.number().optional(),
  pnl: z.number().optional(),
  reason: z.string().optional(),
  exit_reason: z.string().optional(),
})

export const MarkerArraySchema = z.array(MarkerDataSchema)

export const MarketStatusSchema = z.object({
  is_open: z.boolean(),
  close_reason: z.string().nullable(),
  next_open: z.string().nullable(),
  current_time_et: z.string(),
})

// ── API Error Schema ────────────────────────────────────────────────────────

export const ApiErrorSchema = z.object({
  detail: z.union([
    z.string(),
    z.object({ message: z.string() }).passthrough(),
  ]).optional(),
  message: z.string().optional(),
  error: z.string().optional(),
})

// ── Validation Helpers ──────────────────────────────────────────────────────

/**
 * Parse a WebSocket message with validation.
 * Returns null and logs a warning if the message is malformed.
 */
export function parseWebSocketMessage(raw: string): WebSocketMessage | null {
  try {
    const json = JSON.parse(raw)
    const result = WebSocketMessageSchema.safeParse(json)
    if (result.success) {
      return result.data
    }
    // If it doesn't match any known type, still allow it if it has a type field
    // (backend may have added new message types we don't know about yet)
    if (typeof json === 'object' && json !== null && typeof json.type === 'string') {
      return json as WebSocketMessage
    }
    console.warn('[WS] Unknown message format:', result.error.issues)
    return null
  } catch {
    console.warn('[WS] Failed to parse message as JSON')
    return null
  }
}

/**
 * Validate candle data from API response.
 * Returns validated data or null on failure.
 */
export function validateCandles(data: unknown): z.infer<typeof CandleArraySchema> | null {
  const result = CandleArraySchema.safeParse(data)
  if (result.success) return result.data
  console.warn('[API] Invalid candle data:', result.error.issues.slice(0, 3))
  return null
}

/**
 * Validate markers from API response.
 * Returns validated data or null on failure.
 */
export function validateMarkers(data: unknown): z.infer<typeof MarkerArraySchema> | null {
  const result = MarkerArraySchema.safeParse(data)
  if (result.success) return result.data
  console.warn('[API] Invalid marker data:', result.error.issues.slice(0, 3))
  return null
}

/**
 * Validate agent state data (partial) from WS or API.
 * Permissive — uses passthrough to allow unknown fields.
 */
export function validateAgentState(data: unknown): boolean {
  if (typeof data !== 'object' || data === null) return false
  const result = AgentStatePartialSchema.safeParse(data)
  if (!result.success) {
    console.warn('[API] Agent state validation issues:', result.error.issues.slice(0, 3))
  }
  // Still return true for objects — we don't want to reject state updates
  // just because they have unexpected field types. The schema is advisory.
  return typeof data === 'object' && data !== null
}

// ── Key Levels Schema ─────────────────────────────────────────────────────

export const KeyLevelsSchema = z.object({
  daily_open: z.number().nullable(),
  prev_day_high: z.number().nullable(),
  prev_day_low: z.number().nullable(),
  prev_day_mid: z.number().nullable(),
  monday_high: z.number().nullable(),
  monday_low: z.number().nullable(),
  monday_mid: z.number().nullable(),
  weekly_open: z.number().nullable(),
  prev_week_high: z.number().nullable(),
  prev_week_low: z.number().nullable(),
  prev_week_mid: z.number().nullable(),
  monthly_open: z.number().nullable(),
  prev_month_high: z.number().nullable(),
  prev_month_low: z.number().nullable(),
  prev_month_mid: z.number().nullable(),
  quarterly_open: z.number().nullable(),
  prev_quarter_high: z.number().nullable(),
  prev_quarter_low: z.number().nullable(),
  prev_quarter_mid: z.number().nullable(),
  yearly_open: z.number().nullable(),
  current_year_high: z.number().nullable(),
  current_year_low: z.number().nullable(),
  current_year_mid: z.number().nullable(),
})

export type KeyLevelsData = z.infer<typeof KeyLevelsSchema>
