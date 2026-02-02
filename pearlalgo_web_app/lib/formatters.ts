/**
 * Centralized formatting utilities for the Pearl Algo Web App
 *
 * Consolidates duplicated formatting functions used across 12+ panels.
 * Import and use these formatters instead of creating local implementations.
 */

/**
 * Format a P&L value with sign and currency symbol
 * @param value - The P&L value
 * @param decimals - Number of decimal places (default: 2)
 * @param compact - Use compact notation for large values (default: false)
 */
export function formatPnL(value: number, decimals = 2, compact = false): string {
  const sign = value >= 0 ? '+' : ''
  if (compact && Math.abs(value) >= 1000) {
    return `${sign}$${(value / 1000).toFixed(1)}k`
  }
  return `${sign}$${value.toFixed(decimals)}`
}

/**
 * Format a percentage value
 * @param value - The percentage value (0-100 scale)
 * @param decimals - Number of decimal places (default: 1)
 * @param includeSign - Include +/- sign (default: false)
 */
export function formatPercent(value: number, decimals = 1, includeSign = false): string {
  const sign = includeSign && value > 0 ? '+' : ''
  return `${sign}${value.toFixed(decimals)}%`
}

/**
 * Format a decimal as percentage (0-1 scale to 0-100 scale)
 * @param value - The decimal value (0-1 scale)
 * @param decimals - Number of decimal places (default: 0)
 */
export function formatDecimalAsPercent(value: number, decimals = 0): string {
  return `${(value * 100).toFixed(decimals)}%`
}

/**
 * Format a price value
 * @param value - The price value
 * @param decimals - Number of decimal places (default: 2)
 */
export function formatPrice(value: number | undefined, decimals = 2): string {
  if (value === undefined || value === null) return '—'
  return value.toFixed(decimals)
}

/**
 * Format a timestamp string to time only (HH:MM:SS or HH:MM)
 * @param timestamp - ISO timestamp string
 * @param includeSeconds - Include seconds in output (default: true)
 */
export function formatTime(timestamp: string | null | undefined, includeSeconds = true): string {
  if (!timestamp) return '—'
  try {
    const date = new Date(timestamp)
    const options: Intl.DateTimeFormatOptions = {
      hour: '2-digit',
      minute: '2-digit',
      ...(includeSeconds && { second: '2-digit' }),
    }
    return date.toLocaleTimeString([], options)
  } catch {
    return '—'
  }
}

/**
 * Format a timestamp string to relative time (e.g., "5m ago", "2h ago")
 * @param timestamp - ISO timestamp string or Date object
 */
export function formatTimeAgo(timestamp: string | Date | null | undefined): string {
  if (!timestamp) return '—'
  try {
    const date = typeof timestamp === 'string' ? new Date(timestamp) : timestamp
    const seconds = Math.floor((Date.now() - date.getTime()) / 1000)

    if (seconds < 5) return 'now'
    if (seconds < 60) return `${seconds}s ago`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
    return `${Math.floor(seconds / 86400)}d ago`
  } catch {
    return '—'
  }
}

/**
 * Format seconds to a human-readable duration
 * @param seconds - Duration in seconds
 * @param compact - Use compact format (default: true)
 */
export function formatDuration(seconds: number | undefined, compact = true): string {
  if (seconds === undefined || seconds === null) return '—'

  if (seconds < 60) {
    return compact ? `${seconds}s` : `${seconds} seconds`
  }

  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60

  if (mins < 60) {
    if (compact) {
      return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
    }
    return `${mins} min ${secs > 0 ? `${secs} sec` : ''}`
  }

  const hours = Math.floor(mins / 60)
  const remainingMins = mins % 60

  if (compact) {
    return remainingMins > 0 ? `${hours}h ${remainingMins}m` : `${hours}h`
  }
  return `${hours} hr ${remainingMins > 0 ? `${remainingMins} min` : ''}`
}

/**
 * Format minutes to relative time (e.g., "5m", "2h")
 * @param minutes - Duration in minutes
 */
export function formatMinutesAgo(minutes: number | undefined): string {
  if (minutes === undefined || minutes === null) return '—'

  if (minutes < 1) return '<1m'
  if (minutes < 60) return `${Math.floor(minutes)}m`
  if (minutes < 1440) return `${Math.floor(minutes / 60)}h`
  return `${Math.floor(minutes / 1440)}d`
}

/**
 * Format milliseconds to human-readable latency
 * @param ms - Latency in milliseconds
 */
export function formatLatency(ms: number | undefined): string {
  if (ms === undefined || ms === null) return '—'

  if (ms < 1000) {
    return `${ms.toFixed(0)}ms`
  }
  return `${(ms / 1000).toFixed(1)}s`
}

/**
 * Format a currency value (without sign prefix)
 * @param value - The value
 * @param decimals - Number of decimal places (default: 2)
 * @param compact - Use compact notation for large values (default: false)
 */
export function formatCurrency(value: number, decimals = 2, compact = false): string {
  if (compact && Math.abs(value) >= 1000) {
    return `$${(value / 1000).toFixed(1)}k`
  }
  return `$${Math.abs(value).toFixed(decimals)}`
}

/**
 * Format a win/loss ratio
 * @param wins - Number of wins
 * @param losses - Number of losses
 */
export function formatWinLoss(wins: number, losses: number): string {
  return `${wins}W/${losses}L`
}

/**
 * Format a countdown timer from seconds
 * @param seconds - Remaining seconds
 */
export function formatCountdown(seconds: number): string {
  if (seconds <= 0) return '0s'

  if (seconds < 60) return `${seconds}s`

  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60

  if (mins < 60) {
    return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`
  }

  const hours = Math.floor(mins / 60)
  const remainingMins = mins % 60

  return remainingMins > 0 ? `${hours}h ${remainingMins}m` : `${hours}h`
}

/**
 * Grouped formatters object for convenience imports
 */
export const formatters = {
  pnl: formatPnL,
  percent: formatPercent,
  decimalAsPercent: formatDecimalAsPercent,
  price: formatPrice,
  time: formatTime,
  timeAgo: formatTimeAgo,
  duration: formatDuration,
  minutesAgo: formatMinutesAgo,
  latency: formatLatency,
  currency: formatCurrency,
  winLoss: formatWinLoss,
  countdown: formatCountdown,
}

export default formatters
