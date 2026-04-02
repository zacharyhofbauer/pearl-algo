/**
 * Tests for formatters utility functions
 */

import {
  getUsdPerPoint,
  formatPrice,
  formatTime,
  formatTimeFromDate,
  formatSigned,
  formatRelativeTime,
  formatPnL,
  formatDuration,
  formatTimeRemaining,
  formatExitReason,
  formatMarketCountdown,
  formatAgo,
  computeDurationSeconds,
} from '@/lib/formatters'

describe('getUsdPerPoint', () => {
  it('should return correct values for known symbols', () => {
    expect(getUsdPerPoint('MNQ')).toBe(2)
    expect(getUsdPerPoint('NQ')).toBe(20)
    expect(getUsdPerPoint('MES')).toBe(5)
    expect(getUsdPerPoint('ES')).toBe(50)
    expect(getUsdPerPoint('GC')).toBe(10)
    expect(getUsdPerPoint('CL')).toBe(10)
  })

  it('should handle case-insensitive input', () => {
    expect(getUsdPerPoint('mnq')).toBe(2)
    expect(getUsdPerPoint('MnQ')).toBe(2)
  })

  it('should handle null/undefined/unknown symbols', () => {
    expect(getUsdPerPoint(null)).toBeNull()
    expect(getUsdPerPoint(undefined)).toBeNull()
    expect(getUsdPerPoint('')).toBeNull()
    expect(getUsdPerPoint('UNKNOWN')).toBeNull()
  })
})

describe('formatPrice', () => {
  it('should format valid prices to 2 decimals', () => {
    expect(formatPrice(123.456)).toBe('123.46')
    expect(formatPrice(100)).toBe('100.00')
    expect(formatPrice(0.1)).toBe('0.10')
  })

  it('should handle null/undefined/NaN', () => {
    expect(formatPrice(null)).toBe('—')
    expect(formatPrice(undefined)).toBe('—')
    expect(formatPrice(NaN)).toBe('—')
  })

  it('should handle negative prices', () => {
    expect(formatPrice(-123.45)).toBe('-123.45')
  })
})

describe('formatTime', () => {
  it('should format valid ISO timestamps', () => {
    const result = formatTime('2024-01-01T12:34:56Z')
    expect(result).toMatch(/^\d{2}:\d{2}$/)
  })

  it('should handle null/undefined/invalid', () => {
    expect(formatTime(null)).toBe('—')
    expect(formatTime(undefined)).toBe('—')
    expect(formatTime('invalid')).toBe('—')
  })
})

describe('formatTimeFromDate', () => {
  it('should format valid Date objects', () => {
    const date = new Date('2024-01-01T12:34:56Z')
    const result = formatTimeFromDate(date)
    expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/)
  })

  it('should handle null', () => {
    expect(formatTimeFromDate(null)).toBe('--:--')
  })
})

describe('formatSigned', () => {
  it('should add + sign for positive numbers', () => {
    expect(formatSigned(123.45)).toBe('+123.45')
    expect(formatSigned(0)).toBe('+0.00')
  })

  it('should add - sign for negative numbers', () => {
    expect(formatSigned(-123.45)).toBe('-123.45')
  })

  it('should respect decimals parameter', () => {
    expect(formatSigned(123.456, 1)).toBe('+123.5')
    expect(formatSigned(123.456, 3)).toBe('+123.456')
  })
})

describe('formatRelativeTime', () => {
  beforeEach(() => {
    jest.useFakeTimers()
    jest.setSystemTime(new Date('2024-01-01T12:00:00Z'))
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('should format "Just now" for very recent times', () => {
    const recent = new Date('2024-01-01T11:59:58Z')
    expect(formatRelativeTime(recent)).toBe('Just now')
  })

  it('should format seconds ago', () => {
    const recent = new Date('2024-01-01T11:59:50Z')
    expect(formatRelativeTime(recent)).toBe('10s ago')
  })

  it('should format minutes ago', () => {
    const recent = new Date('2024-01-01T11:30:00Z')
    expect(formatRelativeTime(recent)).toBe('30m ago')
  })

  it('should format time for older dates', () => {
    const older = new Date('2024-01-01T10:00:00Z')
    const result = formatRelativeTime(older)
    expect(result).toMatch(/^\d{2}:\d{2}$/)
  })

  it('should handle null/undefined', () => {
    expect(formatRelativeTime(null)).toBe('Never')
    expect(formatRelativeTime(undefined as any)).toBe('Never')
  })

  it('should handle ISO strings', () => {
    expect(formatRelativeTime('2024-01-01T11:59:50Z')).toBe('10s ago')
  })
})

describe('formatPnL', () => {
  it('should format positive P&L with + sign', () => {
    expect(formatPnL(123.45)).toBe('+$123.45')
    expect(formatPnL(0)).toBe('+$0.00')
  })

  it('should format negative P&L with - sign', () => {
    expect(formatPnL(-123.45)).toBe('-$123.45')
  })

  it('should handle null/undefined/NaN', () => {
    expect(formatPnL(null)).toBe('—')
    expect(formatPnL(undefined)).toBe('—')
    expect(formatPnL(NaN)).toBe('—')
  })
})

describe('formatDuration', () => {
  it('should format seconds', () => {
    expect(formatDuration(30)).toBe('30s')
    expect(formatDuration(59)).toBe('59s')
  })

  it('should format minutes', () => {
    expect(formatDuration(60)).toBe('1m')
    expect(formatDuration(3599)).toBe('59m')
  })

  it('should format hours and minutes', () => {
    expect(formatDuration(3600)).toBe('1h 0m')
    expect(formatDuration(3660)).toBe('1h 1m')
  })

  it('should handle null/undefined/zero/negative', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(undefined)).toBe('—')
    expect(formatDuration(0)).toBe('—')
    expect(formatDuration(-10)).toBe('—')
  })
})

describe('formatTimeRemaining', () => {
  it('should format seconds', () => {
    expect(formatTimeRemaining(30)).toBe('30s')
  })

  it('should format minutes and seconds', () => {
    expect(formatTimeRemaining(90)).toBe('1m 30s')
  })

  it('should format hours and minutes', () => {
    expect(formatTimeRemaining(3660)).toBe('1h 1m')
  })
})

describe('formatExitReason', () => {
  it('should identify manual close', () => {
    const result = formatExitReason('close_all')
    expect(result.text).toBe('Manual Close')
    expect(result.type).toBe('manual')
  })

  it('should identify stop loss', () => {
    const result = formatExitReason('sl_hit')
    expect(result.text).toBe('Stop Loss')
    expect(result.type).toBe('stop')
  })

  it('should identify target hit', () => {
    const result = formatExitReason('tp_hit')
    expect(result.text).toBe('Target Hit')
    expect(result.type).toBe('target')
  })

  it('should identify trailing stop', () => {
    const result = formatExitReason('trail_stop')
    expect(result.text).toBe('Trailing Stop')
    expect(result.type).toBe('trail')
  })

  it('should identify time exit', () => {
    const result = formatExitReason('eod')
    expect(result.text).toBe('Time Exit')
    expect(result.type).toBe('time')
  })

  it('should format unknown reasons', () => {
    const result = formatExitReason('custom_reason')
    expect(result.text).toBe('Custom Reason')
    expect(result.type).toBe('other')
  })

  it('should handle empty string', () => {
    const result = formatExitReason('')
    expect(result.text).toBe('')
    expect(result.type).toBe('')
  })
})

describe('formatMarketCountdown', () => {
  beforeEach(() => {
    jest.useFakeTimers()
    jest.setSystemTime(new Date('2024-01-01T12:00:00Z'))
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('should format hours and minutes', () => {
    const nextOpen = '2024-01-01T15:30:00Z'
    expect(formatMarketCountdown(nextOpen)).toBe('Opens in 3h 30m')
  })

  it('should format days and hours', () => {
    const nextOpen = '2024-01-03T12:00:00Z'
    expect(formatMarketCountdown(nextOpen)).toBe('Opens in 2d 0h')
  })

  it('should return null for past dates', () => {
    const nextOpen = '2024-01-01T11:00:00Z'
    expect(formatMarketCountdown(nextOpen)).toBeNull()
  })

  it('should handle null/undefined', () => {
    expect(formatMarketCountdown(null)).toBeNull()
    expect(formatMarketCountdown(undefined)).toBeNull()
  })

  it('should handle invalid dates', () => {
    expect(formatMarketCountdown('invalid')).toBeNull()
  })
})

describe('formatAgo', () => {
  beforeEach(() => {
    jest.useFakeTimers()
    jest.setSystemTime(new Date('2024-01-01T12:00:00Z'))
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  it('should format seconds ago', () => {
    expect(formatAgo('2024-01-01T11:59:50Z')).toBe('10s ago')
  })

  it('should format minutes ago', () => {
    expect(formatAgo('2024-01-01T11:30:00Z')).toBe('30m ago')
  })

  it('should format hours ago', () => {
    expect(formatAgo('2024-01-01T10:00:00Z')).toBe('2h ago')
  })

  it('should format days ago', () => {
    expect(formatAgo('2023-12-30T12:00:00Z')).toBe('2d ago')
  })

  it('should handle null/undefined', () => {
    expect(formatAgo(null)).toBe('—')
    expect(formatAgo(undefined)).toBe('—')
  })
})

describe('computeDurationSeconds', () => {
  it('should compute duration correctly', () => {
    const entry = '2024-01-01T12:00:00Z'
    const exit = '2024-01-01T12:05:30Z'
    expect(computeDurationSeconds(entry, exit)).toBe(330)
  })

  it('should handle null/undefined', () => {
    expect(computeDurationSeconds(null, '2024-01-01T12:00:00Z')).toBeNull()
    expect(computeDurationSeconds('2024-01-01T12:00:00Z', null)).toBeNull()
    expect(computeDurationSeconds(null, null)).toBeNull()
  })

  it('should return 0 for same time', () => {
    const time = '2024-01-01T12:00:00Z'
    expect(computeDurationSeconds(time, time)).toBe(0)
  })

  it('should return 0 for negative duration', () => {
    const entry = '2024-01-01T12:05:00Z'
    const exit = '2024-01-01T12:00:00Z'
    expect(computeDurationSeconds(entry, exit)).toBe(0)
  })
})
