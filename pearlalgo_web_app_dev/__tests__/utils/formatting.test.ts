import {
  formatPnL,
  formatCurrency,
  formatPercent,
  formatTime,
  formatRelativeTime,
  formatTimeAgo,
} from '@/utils/formatting'

describe('formatting utilities', () => {
  describe('formatPnL', () => {
    it('formats positive P&L with plus sign', () => {
      expect(formatPnL(100.5)).toBe('+$100.50')
      expect(formatPnL(0.01)).toBe('+$0.01')
    })

    it('formats negative P&L without plus sign', () => {
      expect(formatPnL(-50.25)).toBe('-$50.25')
      expect(formatPnL(-0.01)).toBe('-$0.01')
    })

    it('handles null and undefined', () => {
      expect(formatPnL(null)).toBe('—')
      expect(formatPnL(undefined)).toBe('—')
    })

    it('handles NaN', () => {
      expect(formatPnL(NaN)).toBe('—')
    })

    it('handles zero', () => {
      expect(formatPnL(0)).toBe('+$0.00')
      expect(formatPnL(-0)).toBe('+$0.00')
    })

    it('handles large numbers', () => {
      expect(formatPnL(999999.99)).toBe('+$999999.99')
      expect(formatPnL(-999999.99)).toBe('-$999999.99')
    })
  })

  describe('formatCurrency', () => {
    it('formats currency with 2 decimals by default', () => {
      expect(formatCurrency(100.5)).toBe('$100.50')
      expect(formatCurrency(0.01)).toBe('$0.01')
    })

    it('handles null and undefined', () => {
      expect(formatCurrency(null)).toBe('—')
      expect(formatCurrency(undefined)).toBe('—')
    })

    it('handles NaN', () => {
      expect(formatCurrency(NaN)).toBe('—')
    })

    it('supports compact format', () => {
      expect(formatCurrency(1500, { compact: true })).toBe('$1.5k')
      expect(formatCurrency(1000, { compact: true })).toBe('$1.0k')
      expect(formatCurrency(999, { compact: true })).toBe('$999')
    })

    it('supports showSign option', () => {
      expect(formatCurrency(100, { showSign: true })).toBe('+$100.00')
      expect(formatCurrency(-50, { showSign: true })).toBe('-$50.00')
      expect(formatCurrency(1500, { compact: true, showSign: true })).toBe('+$1.5k')
    })

    it('handles zero', () => {
      expect(formatCurrency(0)).toBe('$0.00')
    })
  })

  describe('formatPercent', () => {
    it('formats percentage with 2 decimals by default', () => {
      expect(formatPercent(12.345)).toBe('12.35%')
      expect(formatPercent(0.01)).toBe('0.01%')
    })

    it('handles custom decimal places', () => {
      expect(formatPercent(12.345, 0)).toBe('12%')
      expect(formatPercent(12.345, 1)).toBe('12.3%')
      expect(formatPercent(12.345, 3)).toBe('12.345%')
    })

    it('handles null and undefined', () => {
      expect(formatPercent(null)).toBe('—')
      expect(formatPercent(undefined)).toBe('—')
    })

    it('handles NaN', () => {
      expect(formatPercent(NaN)).toBe('—')
    })

    it('handles negative percentages', () => {
      expect(formatPercent(-5.5)).toBe('-5.50%')
    })
  })

  describe('formatTime', () => {
    it('formats Date object in 24-hour format by default', () => {
      const date = new Date('2025-02-12T14:30:00Z')
      expect(formatTime(date)).toBe('14:30')
    })

    it('formats ISO string', () => {
      expect(formatTime('2025-02-12T14:30:00Z')).toBe('14:30')
    })

    it('handles null and undefined', () => {
      expect(formatTime(null)).toBe('—')
      expect(formatTime(undefined)).toBe('—')
    })

    it('handles invalid date strings', () => {
      expect(formatTime('invalid')).toBe('—')
    })

    it('supports 12-hour format', () => {
      const date = new Date('2025-02-12T14:30:00Z')
      const result = formatTime(date, { hour12: true })
      // Result depends on timezone, but should contain "PM" or "2:30"
      expect(result).toMatch(/\d{1,2}:\d{2}/)
    })

    it('handles midnight', () => {
      const date = new Date('2025-02-12T00:00:00Z')
      expect(formatTime(date)).toBe('00:00')
    })
  })

  describe('formatRelativeTime', () => {
    beforeEach(() => {
      jest.useFakeTimers()
      jest.setSystemTime(new Date('2025-02-12T12:00:00Z'))
    })

    afterEach(() => {
      jest.useRealTimers()
    })

    it('returns "Just now" for very recent times', () => {
      const recent = new Date('2025-02-12T11:59:58Z').toISOString()
      expect(formatRelativeTime(recent)).toBe('Just now')
    })

    it('formats seconds ago', () => {
      const secondsAgo = new Date('2025-02-12T11:59:50Z').toISOString()
      expect(formatRelativeTime(secondsAgo)).toBe('10s ago')
    })

    it('formats minutes ago', () => {
      const minutesAgo = new Date('2025-02-12T11:30:00Z').toISOString()
      expect(formatRelativeTime(minutesAgo)).toBe('30m ago')
    })

    it('falls back to absolute time for hours ago', () => {
      const hoursAgo = new Date('2025-02-12T10:00:00Z').toISOString()
      const result = formatRelativeTime(hoursAgo)
      expect(result).toMatch(/\d{2}:\d{2}/) // Should be absolute time format
    })

    it('handles null and undefined', () => {
      expect(formatRelativeTime(null)).toBe('—')
      expect(formatRelativeTime(undefined)).toBe('—')
    })

    it('handles invalid date strings', () => {
      expect(formatRelativeTime('invalid')).toBe('—')
    })
  })

  describe('formatTimeAgo', () => {
    it('returns "now" for very recent times', () => {
      expect(formatTimeAgo(0)).toBe('now')
      expect(formatTimeAgo(4)).toBe('now')
    })

    it('formats seconds', () => {
      expect(formatTimeAgo(5)).toBe('5s')
      expect(formatTimeAgo(59)).toBe('59s')
    })

    it('formats minutes', () => {
      expect(formatTimeAgo(60)).toBe('1m')
      expect(formatTimeAgo(3599)).toBe('59m')
    })

    it('formats hours', () => {
      expect(formatTimeAgo(3600)).toBe('1h')
      expect(formatTimeAgo(7200)).toBe('2h')
      expect(formatTimeAgo(86400)).toBe('24h')
    })
  })
})
