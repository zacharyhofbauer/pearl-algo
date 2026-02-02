/**
 * Color Utilities (U1.2)
 *
 * Provides color utilities that use CSS tokens instead of hardcoded values.
 * Use these functions instead of hardcoding colors in components.
 */

// Session color names that map to CSS variables
export type SessionColorName =
  | 'overnight'
  | 'early'
  | 'london'
  | 'us-open'
  | 'midday'
  | 'afternoon'
  | 'close'
  | 'extended'

// RGB tuple type
export type RGBTuple = [number, number, number]

// Session definitions with their hour ranges (ET timezone)
const SESSION_DEFINITIONS: {
  name: SessionColorName
  startHour: number
  endHour: number
  cssVar: string
  rgb: RGBTuple
}[] = [
  { name: 'overnight', startHour: 4, endHour: 6.5, cssVar: '--session-overnight-rgb', rgb: [147, 112, 219] },
  { name: 'early', startHour: 6.5, endHour: 8, cssVar: '--session-early-rgb', rgb: [100, 149, 237] },
  { name: 'london', startHour: 8, endHour: 9.5, cssVar: '--session-london-rgb', rgb: [0, 212, 255] },
  { name: 'us-open', startHour: 9.5, endHour: 12, cssVar: '--session-us-open-rgb', rgb: [0, 230, 118] },
  { name: 'midday', startHour: 12, endHour: 14, cssVar: '--session-midday-rgb', rgb: [255, 193, 7] },
  { name: 'afternoon', startHour: 14, endHour: 16, cssVar: '--session-afternoon-rgb', rgb: [255, 152, 0] },
  { name: 'close', startHour: 16, endHour: 18, cssVar: '--session-close-rgb', rgb: [255, 110, 199] },
  { name: 'extended', startHour: 18, endHour: 4, cssVar: '--session-extended-rgb', rgb: [106, 90, 205] },
]

/**
 * Get session color RGB values for a given hour.
 *
 * @param hour - Hour of day (0-24, can have decimals for minutes)
 * @returns RGB tuple for the session color
 *
 * @example
 * ```ts
 * const [r, g, b] = getSessionColorRGB(10.5) // 10:30 AM -> US Open session
 * const style = { backgroundColor: `rgba(${r}, ${g}, ${b}, 0.3)` }
 * ```
 */
export function getSessionColorRGB(hour: number): RGBTuple {
  // Handle overnight wrap-around (18:00 - 4:00)
  if (hour >= 18 || hour < 4) {
    return SESSION_DEFINITIONS.find((s) => s.name === 'extended')!.rgb
  }

  // Find matching session
  for (const session of SESSION_DEFINITIONS) {
    if (session.name === 'extended') continue
    if (hour >= session.startHour && hour < session.endHour) {
      return session.rgb
    }
  }

  // Fallback to overnight
  return SESSION_DEFINITIONS.find((s) => s.name === 'extended')!.rgb
}

/**
 * Get session color CSS variable name for a given hour.
 *
 * @param hour - Hour of day (0-24, can have decimals)
 * @returns CSS variable name (e.g., '--session-us-open-rgb')
 *
 * @example
 * ```ts
 * const cssVar = getSessionColorVar(10.5) // '--session-us-open-rgb'
 * const style = { backgroundColor: `rgba(var(${cssVar}), 0.3)` }
 * ```
 */
export function getSessionColorVar(hour: number): string {
  if (hour >= 18 || hour < 4) {
    return '--session-extended-rgb'
  }

  for (const session of SESSION_DEFINITIONS) {
    if (session.name === 'extended') continue
    if (hour >= session.startHour && hour < session.endHour) {
      return session.cssVar
    }
  }

  return '--session-extended-rgb'
}

/**
 * Get session name for a given hour.
 *
 * @param hour - Hour of day (0-24, can have decimals)
 * @returns Session name
 */
export function getSessionName(hour: number): SessionColorName {
  if (hour >= 18 || hour < 4) {
    return 'extended'
  }

  for (const session of SESSION_DEFINITIONS) {
    if (session.name === 'extended') continue
    if (hour >= session.startHour && hour < session.endHour) {
      return session.name
    }
  }

  return 'extended'
}

/**
 * Get session color as an RGBA string.
 *
 * @param hour - Hour of day (0-24)
 * @param alpha - Opacity (0-1)
 * @returns RGBA color string
 *
 * @example
 * ```ts
 * const color = getSessionColorRGBA(10.5, 0.3) // 'rgba(0, 230, 118, 0.3)'
 * ```
 */
export function getSessionColorRGBA(hour: number, alpha: number = 1): string {
  const [r, g, b] = getSessionColorRGB(hour)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

/**
 * Get current session color based on current time.
 *
 * @param alpha - Opacity (0-1)
 * @returns RGBA color string for current session
 */
export function getCurrentSessionColor(alpha: number = 1): string {
  const now = new Date()
  const hour = now.getHours() + now.getMinutes() / 60
  return getSessionColorRGBA(hour, alpha)
}

// Chart-specific color tokens (for use in chart components)
export const CHART_COLORS = {
  candleUp: 'var(--chart-candle-up)',
  candleDown: 'var(--chart-candle-down)',
  volumeUp: 'var(--chart-volume-up)',
  volumeDown: 'var(--chart-volume-down)',
  grid: 'var(--chart-grid)',
  crosshair: 'var(--chart-crosshair)',
  tooltipBg: 'var(--chart-tooltip-bg)',
} as const

// Financial color tokens
export const FINANCIAL_COLORS = {
  profit: 'var(--color-profit)',
  loss: 'var(--color-loss)',
  long: 'var(--color-long)',
  short: 'var(--color-short)',
  // RGB variants for rgba() usage
  profitRgb: 'var(--accent-green-rgb)',
  lossRgb: 'var(--accent-red-rgb)',
} as const

// Status color tokens
export const STATUS_COLORS = {
  online: 'var(--color-status-online)',
  warning: 'var(--color-status-warning)',
  offline: 'var(--color-status-offline)',
  ok: 'var(--color-health-ok)',
  error: 'var(--color-health-error)',
} as const
