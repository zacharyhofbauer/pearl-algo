'use client'

import React, { useState, useCallback, useEffect, useRef } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { apiFetch } from '@/lib/api'

// ── Types ──────────────────────────────────────────────────────

type AuditTab = 'ledger' | 'signals' | 'events' | 'equity' | 'recon'
type DateRange = '7d' | '30d' | 'all'

interface AuditEvent {
  id?: string
  timestamp: string
  event_type: string
  account?: string
  details?: string
  metadata?: Record<string, unknown>
}

interface AuditSignal {
  id?: string
  signal_id?: string
  timestamp: string
  symbol?: string
  direction?: string
  outcome: 'accepted' | 'rejected' | string
  reason?: string
  score?: number
  entry_price?: number
  pnl?: number
}

interface EquitySnapshot {
  date: string
  equity: number
  cash?: number
  unrealized_pnl?: number
  realized_pnl?: number
  drawdown?: number
}

interface ReconEntry {
  date?: string
  timestamp?: string
  field: string
  expected: string | number
  actual: string | number
  status: 'match' | 'mismatch' | 'warning' | string
  details?: string
}

interface PaginatedResponse<T> {
  items: T[]
  total?: number
  page?: number
  page_size?: number
  has_more?: boolean
}

// ── Helpers ────────────────────────────────────────────────────

function getDateRange(range: DateRange): { start_date: string; end_date: string } {
  const end = new Date()
  const start = new Date()
  if (range === '7d') {
    start.setDate(start.getDate() - 7)
  } else if (range === '30d') {
    start.setDate(start.getDate() - 30)
  } else {
    start.setFullYear(start.getFullYear() - 5) // "all" = 5 years back
  }
  return {
    start_date: start.toISOString().split('T')[0],
    end_date: end.toISOString().split('T')[0],
  }
}

function getAccountParam(): string {
  if (typeof window === 'undefined') return ''
  const params = new URLSearchParams(window.location.search)
  return params.get('account') || ''
}

function formatTs(ts: string | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

function formatDate(ts: string | null | undefined): string {
  if (!ts) return '—'
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatUsd(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  const sign = n >= 0 ? '+' : ''
  return `${sign}$${n.toFixed(2)}`
}

function formatPct(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return `${n.toFixed(2)}%`
}

// ── Inline Styles (matching dark trading dashboard theme) ──────

const S = {
  tabs: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
    padding: '8px 12px',
    borderBottom: '1px solid var(--border-color, #2a2a3a)',
    flexWrap: 'wrap' as const,
  },
  tab: {
    background: 'transparent',
    border: '1px solid transparent',
    color: 'var(--text-secondary, #b0b8c8)',
    padding: '6px 12px',
    borderRadius: '4px',
    fontSize: '12px',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    letterSpacing: '0.3px',
    textTransform: 'uppercase' as const,
    whiteSpace: 'nowrap' as const,
  },
  tabActive: {
    color: 'var(--text-primary, #f0eeeb)',
    background: 'rgba(0, 212, 255, 0.14)',
    borderColor: 'rgba(0, 212, 255, 0.25)',
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '8px',
    padding: '8px 12px',
    borderBottom: '1px solid var(--border-subtle, #1e1e28)',
    flexWrap: 'wrap' as const,
  },
  toolbarGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  rangeBtn: {
    background: 'transparent',
    border: '1px solid var(--border-color, #2a2a3a)',
    color: 'var(--text-secondary, #b0b8c8)',
    padding: '4px 10px',
    borderRadius: '4px',
    fontSize: '11px',
    fontWeight: 700,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    textTransform: 'uppercase' as const,
  },
  rangeBtnActive: {
    color: 'var(--text-primary, #f0eeeb)',
    background: 'rgba(0, 212, 255, 0.12)',
    borderColor: 'rgba(0, 212, 255, 0.3)',
  },
  exportBtn: {
    background: 'transparent',
    border: '1px solid rgba(0, 212, 255, 0.3)',
    color: 'var(--accent-cyan, #00d4ff)',
    padding: '4px 12px',
    borderRadius: '4px',
    fontSize: '11px',
    fontWeight: 700,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.3px',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: '12px',
  },
  th: {
    textAlign: 'left' as const,
    padding: '8px 10px',
    fontSize: '10px',
    fontWeight: 800,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    color: 'var(--text-tertiary, #8a92a0)',
    borderBottom: '1px solid var(--border-color, #2a2a3a)',
    whiteSpace: 'nowrap' as const,
  },
  thRight: {
    textAlign: 'right' as const,
    padding: '8px 10px',
    fontSize: '10px',
    fontWeight: 800,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
    color: 'var(--text-tertiary, #8a92a0)',
    borderBottom: '1px solid var(--border-color, #2a2a3a)',
    whiteSpace: 'nowrap' as const,
  },
  td: {
    padding: '6px 10px',
    borderBottom: '1px solid var(--border-subtle, #1e1e28)',
    color: 'var(--text-secondary, #b0b8c8)',
    verticalAlign: 'top' as const,
  },
  tdMono: {
    padding: '6px 10px',
    borderBottom: '1px solid var(--border-subtle, #1e1e28)',
    color: 'var(--text-primary, #f0eeeb)',
    fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace",
    fontSize: '12px',
    verticalAlign: 'top' as const,
  },
  tdRight: {
    padding: '6px 10px',
    borderBottom: '1px solid var(--border-subtle, #1e1e28)',
    textAlign: 'right' as const,
    fontFamily: "'SF Mono', 'Monaco', 'Consolas', monospace",
    fontSize: '12px',
    verticalAlign: 'top' as const,
  },
  positive: { color: 'var(--accent-green, #00e676)' },
  negative: { color: 'var(--accent-red, #ff5252)' },
  muted: { color: 'var(--text-muted, #6e7380)' },
  badge: {
    display: 'inline-block',
    padding: '2px 6px',
    borderRadius: '3px',
    fontSize: '10px',
    fontWeight: 700,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.3px',
  },
  badgeAccepted: {
    background: 'rgba(0, 230, 118, 0.12)',
    color: 'var(--accent-green, #00e676)',
  },
  badgeRejected: {
    background: 'rgba(255, 82, 82, 0.12)',
    color: 'var(--accent-red, #ff5252)',
  },
  badgeMatch: {
    background: 'rgba(0, 230, 118, 0.12)',
    color: 'var(--accent-green, #00e676)',
  },
  badgeMismatch: {
    background: 'rgba(255, 82, 82, 0.12)',
    color: 'var(--accent-red, #ff5252)',
  },
  badgeWarning: {
    background: 'rgba(255, 171, 0, 0.12)',
    color: 'var(--accent-yellow, #ffab00)',
  },
  badgeEvent: {
    background: 'rgba(0, 212, 255, 0.10)',
    color: 'var(--accent-cyan, #00d4ff)',
  },
  empty: {
    padding: '24px 12px',
    color: 'var(--text-tertiary, #8a92a0)',
    fontSize: '12px',
    textAlign: 'center' as const,
  },
  loadMore: {
    width: '100%',
    marginTop: '4px',
    padding: '8px 10px',
    background: 'transparent',
    border: '1px solid var(--border-color, #2a2a3a)',
    borderRadius: '4px',
    color: 'var(--text-secondary, #b0b8c8)',
    fontSize: '11px',
    fontWeight: 600,
    cursor: 'pointer',
    transition: 'all 0.15s ease',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.3px',
  },
  loading: {
    padding: '16px',
    textAlign: 'center' as const,
    color: 'var(--text-tertiary, #8a92a0)',
    fontSize: '12px',
  },
  error: {
    padding: '12px',
    color: 'var(--accent-red, #ff5252)',
    fontSize: '12px',
    textAlign: 'center' as const,
  },
  contentWrap: {
    padding: '0',
    overflow: 'auto',
    maxHeight: '600px',
  },
  filterRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
  },
  filterLabel: {
    fontSize: '10px',
    fontWeight: 700,
    color: 'var(--text-tertiary, #8a92a0)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.3px',
  },
  filterSelect: {
    background: 'var(--bg-card, #1a1a24)',
    border: '1px solid var(--border-color, #2a2a3a)',
    color: 'var(--text-secondary, #b0b8c8)',
    padding: '3px 8px',
    borderRadius: '4px',
    fontSize: '11px',
    cursor: 'pointer',
    outline: 'none',
  },
  dirLong: {
    display: 'inline-block',
    padding: '1px 5px',
    borderRadius: '3px',
    fontSize: '10px',
    fontWeight: 700,
    background: 'rgba(0, 212, 255, 0.15)',
    color: 'var(--color-long, #00d4ff)',
    textTransform: 'uppercase' as const,
  },
  dirShort: {
    display: 'inline-block',
    padding: '1px 5px',
    borderRadius: '3px',
    fontSize: '10px',
    fontWeight: 700,
    background: 'rgba(255, 110, 199, 0.15)',
    color: 'var(--color-short, #ff6ec7)',
    textTransform: 'uppercase' as const,
  },
} as const

// ── Shared sub-components ──────────────────────────────────────

function DateRangeSelector({
  range,
  onRangeChange,
}: {
  range: DateRange
  onRangeChange: (r: DateRange) => void
}) {
  return (
    <div style={S.filterRow}>
      <span style={S.filterLabel}>Range</span>
      {(['7d', '30d', 'all'] as DateRange[]).map((r) => (
        <button
          key={r}
          type="button"
          style={{ ...S.rangeBtn, ...(range === r ? S.rangeBtnActive : {}) }}
          onClick={() => onRangeChange(r)}
        >
          {r === 'all' ? 'All' : r}
        </button>
      ))}
    </div>
  )
}

function ExportButton({ range, eventType }: { range: DateRange; eventType?: string }) {
  const [busy, setBusy] = useState(false)

  const handleExport = async () => {
    if (busy) return
    setBusy(true)
    try {
      const { start_date, end_date } = getDateRange(range)
      const account = getAccountParam()
      const params = new URLSearchParams({
        format: 'csv',
        start_date,
        end_date,
      })
      if (account) params.set('account', account)
      if (eventType) params.set('event_type', eventType)

      const res = await apiFetch(`/api/audit/export?${params.toString()}`)
      if (!res.ok) throw new Error(`Export failed (${res.status})`)

      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `audit_export_${start_date}_${end_date}.csv`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Export failed:', err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <button
      type="button"
      style={{ ...S.exportBtn, opacity: busy ? 0.5 : 1 }}
      onClick={handleExport}
      disabled={busy}
    >
      {busy ? 'Exporting…' : 'Export CSV'}
    </button>
  )
}

function LoadMoreButton({
  loading,
  hasMore,
  onClick,
}: {
  loading: boolean
  hasMore: boolean
  onClick: () => void
}) {
  if (!hasMore) return null
  return (
    <button
      type="button"
      style={{ ...S.loadMore, opacity: loading ? 0.5 : 1 }}
      onClick={onClick}
      disabled={loading}
    >
      {loading ? 'Loading…' : 'Load More'}
    </button>
  )
}

// ── Tab: Trade Ledger (events with event_type=trade) ───────────

function TradeLedgerTab() {
  const [range, setRange] = useState<DateRange>('7d')
  const [rows, setRows] = useState<AuditEvent[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  const fetchPage = useCallback(
    async (pageNum: number, append: boolean) => {
      setLoading(true)
      setError(null)
      try {
        const { start_date, end_date } = getDateRange(range)
        const account = getAccountParam()
        const params = new URLSearchParams({
          event_type: 'trade',
          start_date,
          end_date,
          page: String(pageNum),
          page_size: '50',
        })
        if (account) params.set('account', account)

        const res = await apiFetch(`/api/audit/events?${params.toString()}`)
        if (!res.ok) throw new Error(`Error ${res.status}`)
        const data: PaginatedResponse<AuditEvent> | AuditEvent[] = await res.json()

        if (!mountedRef.current) return

        const items = Array.isArray(data) ? data : data.items || []
        const more = Array.isArray(data) ? false : (data.has_more ?? items.length >= 50)

        setRows((prev) => (append ? [...prev, ...items] : items))
        setHasMore(more)
        setPage(pageNum)
      } catch (err) {
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : 'Failed to load')
        }
      } finally {
        if (mountedRef.current) setLoading(false)
      }
    },
    [range]
  )

  useEffect(() => {
    mountedRef.current = true
    fetchPage(1, false)
    return () => {
      mountedRef.current = false
    }
  }, [fetchPage])

  return (
    <div>
      <div style={S.toolbar}>
        <DateRangeSelector range={range} onRangeChange={setRange} />
        <ExportButton range={range} eventType="trade" />
      </div>
      <div style={S.contentWrap}>
        {error && <div style={S.error}>{error}</div>}
        {!error && rows.length === 0 && !loading && (
          <div style={S.empty}>No trade events in this period</div>
        )}
        {rows.length > 0 && (
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Time</th>
                <th style={S.th}>Type</th>
                <th style={S.th}>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.id || `${row.timestamp}-${i}`}>
                  <td style={S.tdMono}>{formatTs(row.timestamp)}</td>
                  <td style={S.td}>
                    <span style={{ ...S.badge, ...S.badgeEvent }}>
                      {(row.event_type || '').replace(/_/g, ' ')}
                    </span>
                  </td>
                  <td style={S.td}>{row.details || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {loading && <div style={S.loading}>Loading…</div>}
        <div style={{ padding: '0 10px 8px' }}>
          <LoadMoreButton
            loading={loading}
            hasMore={hasMore}
            onClick={() => fetchPage(page + 1, true)}
          />
        </div>
      </div>
    </div>
  )
}

// ── Tab: Signals ───────────────────────────────────────────────

function SignalsTab() {
  const [range, setRange] = useState<DateRange>('7d')
  const [outcomeFilter, setOutcomeFilter] = useState<'' | 'accepted' | 'rejected'>('')
  const [rows, setRows] = useState<AuditSignal[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  const fetchPage = useCallback(
    async (pageNum: number, append: boolean) => {
      setLoading(true)
      setError(null)
      try {
        const { start_date, end_date } = getDateRange(range)
        const account = getAccountParam()
        const params = new URLSearchParams({
          start_date,
          end_date,
          page: String(pageNum),
          page_size: '50',
        })
        if (account) params.set('account', account)
        if (outcomeFilter) params.set('outcome', outcomeFilter)

        const res = await apiFetch(`/api/audit/signals?${params.toString()}`)
        if (!res.ok) throw new Error(`Error ${res.status}`)
        const data: PaginatedResponse<AuditSignal> | AuditSignal[] = await res.json()

        if (!mountedRef.current) return

        const items = Array.isArray(data) ? data : data.items || []
        const more = Array.isArray(data) ? false : (data.has_more ?? items.length >= 50)

        setRows((prev) => (append ? [...prev, ...items] : items))
        setHasMore(more)
        setPage(pageNum)
      } catch (err) {
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : 'Failed to load')
        }
      } finally {
        if (mountedRef.current) setLoading(false)
      }
    },
    [range, outcomeFilter]
  )

  useEffect(() => {
    mountedRef.current = true
    fetchPage(1, false)
    return () => {
      mountedRef.current = false
    }
  }, [fetchPage])

  return (
    <div>
      <div style={S.toolbar}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' as const }}>
          <DateRangeSelector range={range} onRangeChange={setRange} />
          <div style={S.filterRow}>
            <span style={S.filterLabel}>Outcome</span>
            <select
              style={S.filterSelect}
              value={outcomeFilter}
              onChange={(e) => setOutcomeFilter(e.target.value as '' | 'accepted' | 'rejected')}
            >
              <option value="">All</option>
              <option value="accepted">Accepted</option>
              <option value="rejected">Rejected</option>
            </select>
          </div>
        </div>
        <ExportButton range={range} />
      </div>
      <div style={S.contentWrap}>
        {error && <div style={S.error}>{error}</div>}
        {!error && rows.length === 0 && !loading && (
          <div style={S.empty}>No signals in this period</div>
        )}
        {rows.length > 0 && (
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Time</th>
                <th style={S.th}>Symbol</th>
                <th style={S.th}>Dir</th>
                <th style={S.th}>Outcome</th>
                <th style={S.th}>Reason</th>
                <th style={S.thRight}>Score</th>
                <th style={S.thRight}>Entry</th>
                <th style={S.thRight}>P&L</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const isAccepted = row.outcome === 'accepted'
                const dir = (row.direction || '').toLowerCase()
                return (
                  <tr key={row.id || row.signal_id || `${row.timestamp}-${i}`}>
                    <td style={S.tdMono}>{formatTs(row.timestamp)}</td>
                    <td style={S.td}>{row.symbol || '—'}</td>
                    <td style={S.td}>
                      {dir ? (
                        <span style={dir === 'long' ? S.dirLong : S.dirShort}>
                          {dir.toUpperCase()}
                        </span>
                      ) : (
                        '—'
                      )}
                    </td>
                    <td style={S.td}>
                      <span
                        style={{
                          ...S.badge,
                          ...(isAccepted ? S.badgeAccepted : S.badgeRejected),
                        }}
                      >
                        {row.outcome}
                      </span>
                    </td>
                    <td style={{ ...S.td, maxWidth: '200px', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      {row.reason || '—'}
                    </td>
                    <td style={S.tdRight}>
                      {row.score !== null && row.score !== undefined
                        ? row.score.toFixed(2)
                        : '—'}
                    </td>
                    <td style={S.tdRight}>
                      {row.entry_price !== null && row.entry_price !== undefined
                        ? row.entry_price.toFixed(2)
                        : '—'}
                    </td>
                    <td
                      style={{
                        ...S.tdRight,
                        ...(row.pnl !== null && row.pnl !== undefined
                          ? row.pnl >= 0
                            ? S.positive
                            : S.negative
                          : S.muted),
                      }}
                    >
                      {formatUsd(row.pnl)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {loading && <div style={S.loading}>Loading…</div>}
        <div style={{ padding: '0 10px 8px' }}>
          <LoadMoreButton
            loading={loading}
            hasMore={hasMore}
            onClick={() => fetchPage(page + 1, true)}
          />
        </div>
      </div>
    </div>
  )
}

// ── Tab: System Events ─────────────────────────────────────────

function SystemEventsTab() {
  const [range, setRange] = useState<DateRange>('7d')
  const [eventType, setEventType] = useState('')
  const [rows, setRows] = useState<AuditEvent[]>([])
  const [page, setPage] = useState(1)
  const [hasMore, setHasMore] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  const fetchPage = useCallback(
    async (pageNum: number, append: boolean) => {
      setLoading(true)
      setError(null)
      try {
        const { start_date, end_date } = getDateRange(range)
        const account = getAccountParam()
        const params = new URLSearchParams({
          start_date,
          end_date,
          page: String(pageNum),
          page_size: '50',
        })
        if (account) params.set('account', account)
        if (eventType) params.set('event_type', eventType)

        const res = await apiFetch(`/api/audit/events?${params.toString()}`)
        if (!res.ok) throw new Error(`Error ${res.status}`)
        const data: PaginatedResponse<AuditEvent> | AuditEvent[] = await res.json()

        if (!mountedRef.current) return

        const items = Array.isArray(data) ? data : data.items || []
        const more = Array.isArray(data) ? false : (data.has_more ?? items.length >= 50)

        setRows((prev) => (append ? [...prev, ...items] : items))
        setHasMore(more)
        setPage(pageNum)
      } catch (err) {
        if (mountedRef.current) {
          setError(err instanceof Error ? err.message : 'Failed to load')
        }
      } finally {
        if (mountedRef.current) setLoading(false)
      }
    },
    [range, eventType]
  )

  useEffect(() => {
    mountedRef.current = true
    fetchPage(1, false)
    return () => {
      mountedRef.current = false
    }
  }, [fetchPage])

  return (
    <div>
      <div style={S.toolbar}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' as const }}>
          <DateRangeSelector range={range} onRangeChange={setRange} />
          <div style={S.filterRow}>
            <span style={S.filterLabel}>Type</span>
            <select
              style={S.filterSelect}
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
            >
              <option value="">All Events</option>
              <option value="system">System</option>
              <option value="error">Error</option>
              <option value="circuit_breaker">Circuit Breaker</option>
              <option value="config_change">Config Change</option>
              <option value="gateway">Gateway</option>
            </select>
          </div>
        </div>
        <ExportButton range={range} eventType={eventType || undefined} />
      </div>
      <div style={S.contentWrap}>
        {error && <div style={S.error}>{error}</div>}
        {!error && rows.length === 0 && !loading && (
          <div style={S.empty}>No system events in this period</div>
        )}
        {rows.length > 0 && (
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Time</th>
                <th style={S.th}>Type</th>
                <th style={S.th}>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => {
                const isError =
                  (row.event_type || '').toLowerCase().includes('error') ||
                  (row.event_type || '').toLowerCase().includes('fail')
                return (
                  <tr key={row.id || `${row.timestamp}-${i}`}>
                    <td style={S.tdMono}>{formatTs(row.timestamp)}</td>
                    <td style={S.td}>
                      <span
                        style={{
                          ...S.badge,
                          ...(isError
                            ? { background: 'rgba(255, 82, 82, 0.12)', color: 'var(--accent-red, #ff5252)' }
                            : S.badgeEvent),
                        }}
                      >
                        {(row.event_type || '').replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td style={{ ...S.td, maxWidth: '400px', wordBreak: 'break-word' }}>
                      {row.details || '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {loading && <div style={S.loading}>Loading…</div>}
        <div style={{ padding: '0 10px 8px' }}>
          <LoadMoreButton
            loading={loading}
            hasMore={hasMore}
            onClick={() => fetchPage(page + 1, true)}
          />
        </div>
      </div>
    </div>
  )
}

// ── Tab: Equity ────────────────────────────────────────────────

function EquityTab() {
  const [range, setRange] = useState<DateRange>('30d')
  const [rows, setRows] = useState<EquitySnapshot[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { start_date, end_date } = getDateRange(range)
      const account = getAccountParam()
      const params = new URLSearchParams({ start_date, end_date })
      if (account) params.set('account', account)

      const res = await apiFetch(`/api/audit/equity-history?${params.toString()}`)
      if (!res.ok) throw new Error(`Error ${res.status}`)
      const data = await res.json()

      if (!mountedRef.current) return

      const items: EquitySnapshot[] = Array.isArray(data) ? data : data.items || data.snapshots || []
      setRows(items)
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load')
      }
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [range])

  useEffect(() => {
    mountedRef.current = true
    fetchData()
    return () => {
      mountedRef.current = false
    }
  }, [fetchData])

  return (
    <div>
      <div style={S.toolbar}>
        <DateRangeSelector range={range} onRangeChange={setRange} />
        <ExportButton range={range} eventType="equity" />
      </div>
      <div style={S.contentWrap}>
        {error && <div style={S.error}>{error}</div>}
        {!error && rows.length === 0 && !loading && (
          <div style={S.empty}>No equity data in this period</div>
        )}
        {rows.length > 0 && (
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Date</th>
                <th style={S.thRight}>Equity</th>
                <th style={S.thRight}>Cash</th>
                <th style={S.thRight}>Unrealized</th>
                <th style={S.thRight}>Realized</th>
                <th style={S.thRight}>Drawdown</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.date || i}>
                  <td style={S.tdMono}>{formatDate(row.date)}</td>
                  <td style={S.tdRight}>
                    {row.equity !== null && row.equity !== undefined
                      ? `$${row.equity.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                      : '—'}
                  </td>
                  <td style={S.tdRight}>
                    {row.cash !== null && row.cash !== undefined
                      ? `$${row.cash.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                      : '—'}
                  </td>
                  <td
                    style={{
                      ...S.tdRight,
                      ...(row.unrealized_pnl !== null && row.unrealized_pnl !== undefined
                        ? row.unrealized_pnl >= 0
                          ? S.positive
                          : S.negative
                        : S.muted),
                    }}
                  >
                    {formatUsd(row.unrealized_pnl)}
                  </td>
                  <td
                    style={{
                      ...S.tdRight,
                      ...(row.realized_pnl !== null && row.realized_pnl !== undefined
                        ? row.realized_pnl >= 0
                          ? S.positive
                          : S.negative
                        : S.muted),
                    }}
                  >
                    {formatUsd(row.realized_pnl)}
                  </td>
                  <td
                    style={{
                      ...S.tdRight,
                      ...(row.drawdown !== null && row.drawdown !== undefined
                        ? S.negative
                        : S.muted),
                    }}
                  >
                    {formatPct(row.drawdown)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {loading && <div style={S.loading}>Loading…</div>}
      </div>
    </div>
  )
}

// ── Tab: Reconciliation ────────────────────────────────────────

function ReconciliationTab() {
  const [range, setRange] = useState<DateRange>('7d')
  const [rows, setRows] = useState<ReconEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const mountedRef = useRef(true)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { start_date, end_date } = getDateRange(range)
      const account = getAccountParam()
      const params = new URLSearchParams({ start_date, end_date })
      if (account) params.set('account', account)

      const res = await apiFetch(`/api/audit/reconciliation?${params.toString()}`)
      if (!res.ok) throw new Error(`Error ${res.status}`)
      const data = await res.json()

      if (!mountedRef.current) return

      const items: ReconEntry[] = Array.isArray(data) ? data : data.items || data.entries || []
      setRows(items)
    } catch (err) {
      if (mountedRef.current) {
        setError(err instanceof Error ? err.message : 'Failed to load')
      }
    } finally {
      if (mountedRef.current) setLoading(false)
    }
  }, [range])

  useEffect(() => {
    mountedRef.current = true
    fetchData()
    return () => {
      mountedRef.current = false
    }
  }, [fetchData])

  const statusBadge = (status: string) => {
    const s = status.toLowerCase()
    if (s === 'match') return { ...S.badge, ...S.badgeMatch }
    if (s === 'mismatch') return { ...S.badge, ...S.badgeMismatch }
    if (s === 'warning') return { ...S.badge, ...S.badgeWarning }
    return { ...S.badge, ...S.badgeEvent }
  }

  const mismatchCount = rows.filter((r) => r.status === 'mismatch').length
  const warningCount = rows.filter((r) => r.status === 'warning').length

  return (
    <div>
      <div style={S.toolbar}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' as const }}>
          <DateRangeSelector range={range} onRangeChange={setRange} />
          {rows.length > 0 && (
            <div style={{ display: 'flex', gap: '8px', fontSize: '11px' }}>
              <span style={{ color: 'var(--accent-green, #00e676)', fontWeight: 700 }}>
                {rows.length - mismatchCount - warningCount} Match
              </span>
              {mismatchCount > 0 && (
                <span style={{ color: 'var(--accent-red, #ff5252)', fontWeight: 700 }}>
                  {mismatchCount} Mismatch
                </span>
              )}
              {warningCount > 0 && (
                <span style={{ color: 'var(--accent-yellow, #ffab00)', fontWeight: 700 }}>
                  {warningCount} Warning
                </span>
              )}
            </div>
          )}
        </div>
        <ExportButton range={range} eventType="reconciliation" />
      </div>
      <div style={S.contentWrap}>
        {error && <div style={S.error}>{error}</div>}
        {!error && rows.length === 0 && !loading && (
          <div style={S.empty}>No reconciliation data in this period</div>
        )}
        {rows.length > 0 && (
          <table style={S.table}>
            <thead>
              <tr>
                <th style={S.th}>Date</th>
                <th style={S.th}>Field</th>
                <th style={S.thRight}>Expected</th>
                <th style={S.thRight}>Actual</th>
                <th style={S.th}>Status</th>
                <th style={S.th}>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={`${row.field}-${row.date || row.timestamp || i}`}>
                  <td style={S.tdMono}>{formatDate(row.date || row.timestamp)}</td>
                  <td style={S.td}>{(row.field || '').replace(/_/g, ' ')}</td>
                  <td style={S.tdRight}>{String(row.expected)}</td>
                  <td
                    style={{
                      ...S.tdRight,
                      ...(row.status === 'mismatch' ? S.negative : {}),
                    }}
                  >
                    {String(row.actual)}
                  </td>
                  <td style={S.td}>
                    <span style={statusBadge(row.status)}>{row.status}</span>
                  </td>
                  <td style={{ ...S.td, maxWidth: '250px', wordBreak: 'break-word' }}>
                    {row.details || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {loading && <div style={S.loading}>Loading…</div>}
      </div>
    </div>
  )
}

// ── Main AuditPanel component ──────────────────────────────────

const TAB_LABELS: Record<AuditTab, string> = {
  ledger: 'Trade Ledger',
  signals: 'Signals',
  events: 'System Events',
  equity: 'Equity',
  recon: 'Reconciliation',
}

function AuditPanel() {
  const [activeTab, setActiveTab] = useState<AuditTab>('ledger')

  return (
    <DataPanel title="Audit" padding="none" className="audit-panel">
      {/* Tab bar */}
      <div style={S.tabs} role="tablist" aria-label="Audit sections">
        {(Object.keys(TAB_LABELS) as AuditTab[]).map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={activeTab === tab}
            style={{ ...S.tab, ...(activeTab === tab ? S.tabActive : {}) }}
            onClick={() => setActiveTab(tab)}
          >
            {TAB_LABELS[tab]}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'ledger' && <TradeLedgerTab />}
      {activeTab === 'signals' && <SignalsTab />}
      {activeTab === 'events' && <SystemEventsTab />}
      {activeTab === 'equity' && <EquityTab />}
      {activeTab === 'recon' && <ReconciliationTab />}
    </DataPanel>
  )
}

export default React.memo(AuditPanel)
