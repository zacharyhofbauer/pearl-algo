/**
 * Shared formatting utilities for Pearl Algo Web App
 *
 * Centralized formatting functions to ensure consistency across all components.
 * Replaces duplicate implementations scattered throughout the codebase.
 */

/**
 * Format P&L (Profit & Loss) value as currency string
 * @param pnl - P&L value (can be null, undefined, or NaN)
 * @returns Formatted string like "+$100.00" or "-$50.25" or "—" for invalid values
 */
export function formatPnL(pnl: number | null | undefined): string {
  if (pnl === null || pnl === undefined || Number.isNaN(pnl)) return '—'
  const sign = pnl >= 0 ? '+' : '-'
  return `${sign}$${Math.abs(pnl).toFixed(2)}`
}

/**
 * Format currency value
 * @param value - Currency value
 * @param options - Formatting options
 * @param options.compact - Use compact format (e.g., "$1.5k" for >= 1000)
 * @param options.showSign - Include +/- sign prefix
 * @returns Formatted string like "$100.00" or "$1.5k" (if compact) or "—" for invalid values
 */
export function formatCurrency(
  value: number | null | undefined,
  options: { compact?: boolean; showSign?: boolean } = {}
): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  
  const { compact = false, showSign = false } = options
  
  const prefix = showSign ? (value >= 0 ? '+' : '-') : (value < 0 ? '-' : '')
  const abs = Math.abs(value)
  
  if (compact && abs >= 1000) {
    return `${prefix}$${(abs / 1000).toFixed(1)}k`
  }
  
  return `${prefix}$${abs.toFixed(compact ? 0 : 2)}`
}

/**
 * Format percentage value
 * @param value - Percentage value (can be null, undefined, or NaN)
 * @param decimals - Number of decimal places (default: 2)
 * @returns Formatted string like "12.34%" or "—" for invalid values
 */
export function formatPercent(value: number | null | undefined, decimals: number = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(decimals)}%`
}

/**
 * Format time from Date or ISO string
 * @param date - Date object, ISO string, or null/undefined
 * @param options - Formatting options
 * @param options.hour12 - Use 12-hour format (default: false, uses 24-hour)
 * @returns Formatted time string like "14:30" or "—" for invalid values
 */
export function formatTime(
  date: Date | string | null | undefined,
  options: { hour12?: boolean } = {}
): string {
  if (!date) return '—'
  
  const d = date instanceof Date ? date : new Date(date)
  if (Number.isNaN(d.getTime())) return '—'
  
  return d.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZone: 'America/New_York',
  })
}

/**
 * Format relative time from ISO string (e.g., "5m ago", "Just now")
 * @param isoString - ISO 8601 date string or null
 * @returns Formatted relative time string or "—" for invalid values
 */
export function formatRelativeTime(isoString: string | null | undefined): string {
  if (!isoString) return '—'
  
  try {
    const d = new Date(isoString)
    if (Number.isNaN(d.getTime())) return '—'
    
    const seconds = Math.floor((Date.now() - d.getTime()) / 1000)
    
    if (seconds < 5) return 'Just now'
    if (seconds < 60) return `${seconds}s ago`
    
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes}m ago`
    
    // Fall back to absolute time if more than an hour
    return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' })
  } catch {
    return '—'
  }
}

/**
 * Format time ago in seconds (compact format for freshness indicators)
 * @param seconds - Number of seconds ago
 * @returns Formatted string like "now", "5s", "10m", "2h"
 */
export function formatTimeAgo(seconds: number): string {
  if (seconds < 5) return 'now'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  return `${Math.floor(seconds / 3600)}h`
}
