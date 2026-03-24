/**
 * Formatters - Shared utility functions for formatting data
 * 
 * Centralized formatting functions to ensure consistency across components.
 * All functions handle null/undefined/NaN edge cases explicitly.
 */

/**
 * Get USD per point multiplier for a given symbol
 */
export function getUsdPerPoint(sym?: string | null): number | null {
  const s = (sym || '').toUpperCase().trim()
  // US index futures
  if (s === 'MNQ') return 2
  if (s === 'NQ') return 20
  if (s === 'MES') return 5
  if (s === 'ES') return 50
  if (s === 'MYM') return 0.5
  if (s === 'YM') return 5
  if (s === 'M2K') return 5
  if (s === 'RTY') return 50
  // Metals
  if (s === 'GC') return 10
  if (s === 'MGC') return 1
  if (s === 'SI') return 50
  if (s === 'HG') return 250
  // Energy
  if (s === 'CL') return 10
  if (s === 'MCL') return 1
  return null
}

/**
 * Format a price value to 2 decimal places
 */
export function formatPrice(price?: number | null): string {
  if (price === null || price === undefined || Number.isNaN(price)) return '—'
  return price.toFixed(2)
}

/**
 * Format a timestamp string to HH:MM format
 */
export function formatTime(ts?: string | null): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' })
}

/**
 * Format a Date object to h:mm:ss AM/PM ET format
 */
export function formatTimeFromDate(date: Date | null): string {
  if (!date) return '--:--'
  return date.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    hour12: true,
    timeZone: 'America/New_York',
  })
}

/**
 * Format a number with a sign prefix (+ or -)
 */
export function formatSigned(n: number, decimals = 2): string {
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(decimals)}`
}

/**
 * Format a relative time string (e.g., "5s ago", "2m ago")
 * Accepts ISO string or Date object
 */
export function formatRelativeTime(isoString: string | Date | null): string {
  if (!isoString) return 'Never'
  
  let date: Date
  if (isoString instanceof Date) {
    date = isoString
  } else {
    try {
      date = new Date(isoString)
      if (Number.isNaN(date.getTime())) return '—'
    } catch {
      return '—'
    }
  }
  
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000)
  if (seconds < 5) return 'Just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' })
}

/**
 * Format a P&L value with sign and dollar sign
 */
export function formatPnL(pnl?: number | null): string {
  if (pnl === null || pnl === undefined || Number.isNaN(pnl)) return '—'
  const sign = pnl >= 0 ? '+' : '-'
  return `${sign}$${Math.abs(pnl).toFixed(2)}`
}

/**
 * Format a duration in seconds to human-readable format
 */
export function formatDuration(seconds?: number | null): string {
  if (!seconds || seconds <= 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return `${hours}h ${mins}m`
}

/**
 * Format time remaining (similar to formatDuration but with seconds shown)
 */
export function formatTimeRemaining(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  const mins = Math.floor(seconds / 60)
  const secs = seconds % 60
  if (mins < 60) return `${mins}m ${secs}s`
  const hours = Math.floor(mins / 60)
  return `${hours}h ${mins % 60}m`
}

/**
 * Format exit reason to human-readable text and type
 */
export function formatExitReason(reason: string): { text: string; type: string } {
  if (!reason) return { text: '', type: '' }
  const lowerReason = reason.toLowerCase()

  if (lowerReason.includes('close_all') || lowerReason.includes('close all')) {
    return { text: 'Manual Close', type: 'manual' }
  }
  if (lowerReason.includes('trail')) {
    return { text: 'Trailing Stop', type: 'trail' }
  }
  if (lowerReason.includes('stop') || lowerReason.includes('sl_')) {
    return { text: 'Stop Loss', type: 'stop' }
  }
  if (lowerReason.includes('target') || lowerReason.includes('tp_') || lowerReason.includes('profit')) {
    return { text: 'Target Hit', type: 'target' }
  }
  if (lowerReason.includes('time') || lowerReason.includes('eod') || lowerReason.includes('session')) {
    return { text: 'Time Exit', type: 'time' }
  }

  return {
    text: reason.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()),
    type: 'other',
  }
}

/**
 * Format market countdown to next open time
 */
export function formatMarketCountdown(nextOpen?: string | null): string | null {
  if (!nextOpen) return null
  
  try {
    const nextOpenDate = new Date(nextOpen)
    if (Number.isNaN(nextOpenDate.getTime())) return null
    const now = new Date()
    const diffMs = nextOpenDate.getTime() - now.getTime()
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

/**
 * Format "time ago" string (similar to formatRelativeTime but with different thresholds)
 */
export function formatAgo(iso?: string | null, nowMs: number = Date.now()): string {
  if (!iso) return '—'
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return '—'
  const s = Math.max(0, Math.floor((nowMs - t) / 1000))
  if (s < 60) return `${s}s ago`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ago`
  const h = Math.floor(m / 60)
  if (h < 48) return `${h}h ago`
  const d = Math.floor(h / 24)
  return `${d}d ago`
}

/**
 * Compute duration in seconds between two ISO timestamps
 */
export function computeDurationSeconds(entryTime?: string | null, exitTime?: string | null): number | null {
  if (!entryTime || !exitTime) return null
  const a = new Date(entryTime).getTime()
  const b = new Date(exitTime).getTime()
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null
  return Math.max(0, Math.round((b - a) / 1000))
}
