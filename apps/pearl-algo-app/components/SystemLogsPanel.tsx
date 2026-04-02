'use client'

import React, { useMemo } from 'react'
import type { RecentSignalEvent } from '@/components/TradeDockPanel'
import type { PearlFeedMessage, SignalRejections, AgentState } from '@/stores/agentStore'

interface SystemLogsPanelProps {
  recentSignals: RecentSignalEvent[]
  pearlFeed: PearlFeedMessage[]
  signalRejections: SignalRejections | null
  agentState?: AgentState | null
}

interface LogEntry {
  time: Date
  type: 'entry' | 'exit' | 'reject' | 'ai' | 'system'
  message: string
  isLoss?: boolean
}

function formatTime(d: Date): string {
  return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: 'America/New_York' })
}

function parseTime(ts: string | null | undefined): Date {
  if (!ts) return new Date(0)
  try {
    return new Date(ts)
  } catch {
    return new Date(0)
  }
}

function typeLabel(type: LogEntry['type']): string {
  switch (type) {
    case 'entry': return 'ENTRY'
    case 'exit': return 'EXIT'
    case 'reject': return 'SKIP'
    case 'ai': return 'AI'
    case 'system': return 'SYS'
  }
}

interface StatusRow {
  label: string
  color: string
  text: string
}

function getSystemStatusRows(agentState: AgentState | null | undefined): StatusRow[] {
  if (!agentState) return []

  const rows: StatusRow[] = []

  // Gateway
  const gwStatus = agentState.gateway_status?.status
  rows.push({
    label: 'Gateway',
    color: gwStatus === 'online' ? '#4caf50' : '#f44336',
    text: gwStatus === 'online' ? 'Online' : 'Offline',
  })

  // IBKR Data
  const dataFresh = agentState.data_fresh
  const barAge = agentState.data_quality?.latest_bar_age_minutes
  const barAgeSeconds = barAge != null ? barAge * 60 : null
  if (dataFresh) {
    if (barAgeSeconds != null && barAgeSeconds > 120) {
      rows.push({ label: 'IBKR Data', color: '#ffb74d', text: `Stale (${Math.round(barAgeSeconds)}s)` })
    } else {
      rows.push({ label: 'IBKR Data', color: '#4caf50', text: 'Fresh' })
    }
  } else {
    rows.push({ label: 'IBKR Data', color: '#f44336', text: 'No Data' })
  }

  // Tradovate
  const exec = agentState.execution_state
  if (exec) {
    if (exec.enabled && exec.armed) {
      rows.push({ label: 'Tradovate', color: '#4caf50', text: 'Armed' })
    } else if (exec.enabled && !exec.armed) {
      rows.push({ label: 'Tradovate', color: '#ffb74d', text: 'Disarmed' })
    } else {
      rows.push({ label: 'Tradovate', color: '#f44336', text: 'Disabled' })
    }
  } else {
    rows.push({ label: 'Tradovate', color: '#666', text: 'Unknown' })
  }

  // Agent
  if (agentState.running && !agentState.paused) {
    rows.push({ label: 'Agent', color: '#4caf50', text: 'Running' })
  } else if (agentState.paused) {
    rows.push({ label: 'Agent', color: '#ffb74d', text: 'Paused' })
  } else {
    rows.push({ label: 'Agent', color: '#f44336', text: 'Stopped' })
  }

  // OpenClaw
  const ocStatus = agentState.openclaw_status?.status
  rows.push({
    label: 'OpenClaw',
    color: ocStatus === 'online' ? '#4caf50' : '#f44336',
    text: ocStatus === 'online' ? 'Online' : 'Offline',
  })

  return rows
}

export default function SystemLogsPanel({
  recentSignals,
  pearlFeed,
  signalRejections,
  agentState,
}: SystemLogsPanelProps) {
  const entries = useMemo<LogEntry[]>(() => {
    const logs: LogEntry[] = []

    // Signal events
    for (const sig of recentSignals) {
      const time = parseTime(sig.timestamp)
      const dir = (sig.direction || '?').toUpperCase()
      const price = sig.entry_price != null ? sig.entry_price.toFixed(2) : '?'

      if (sig.status === 'entered' || sig.status === 'active') {
        logs.push({
          time,
          type: 'entry',
          message: `${dir} @ ${price}`,
        })
      } else if (sig.status === 'exited' || sig.status === 'closed') {
        const pnl = sig.pnl != null ? ` P&L: ${sig.pnl >= 0 ? '+' : ''}$${sig.pnl.toFixed(2)}` : ''
        const reason = sig.exit_reason ? ` (${sig.exit_reason})` : ''
        logs.push({
          time,
          type: 'exit',
          message: `${dir} closed${reason}${pnl}`,
          isLoss: sig.pnl != null && sig.pnl < 0,
        })
      } else if (sig.status === 'rejected' || sig.status === 'skipped') {
        const reason = sig.reason || sig.exit_reason || 'filtered'
        logs.push({
          time,
          type: 'reject',
          message: `${dir} @ ${price} — ${reason}`,
        })
      }
    }

    // Pearl feed messages
    for (const msg of pearlFeed) {
      const time = parseTime(msg.timestamp)
      logs.push({
        time,
        type: 'ai',
        message: msg.content,
      })
    }

    // Sort reverse chronological
    logs.sort((a, b) => b.time.getTime() - a.time.getTime())

    return logs
  }, [recentSignals, pearlFeed])

  const statusRows = useMemo(() => getSystemStatusRows(agentState), [agentState])

  return (
    <>
      {entries.length === 0 ? (
        <div className="logs-empty">No log entries yet</div>
      ) : (
        entries.map((entry, i) => (
          <div key={i} className="logs-entry">
            <span className="logs-time">{formatTime(entry.time)}</span>
            <span className={`logs-type-badge ${entry.type}${entry.isLoss ? ' loss' : ''}`}>
              {typeLabel(entry.type)}
            </span>
            <span className="logs-message">{entry.message}</span>
          </div>
        ))
      )}

      {statusRows.length > 0 && (
        <>
          <div className="system-status-divider" />
          <div className="system-status-title">System Status</div>
          {statusRows.map((row) => (
            <div key={row.label} className="system-status-row">
              <span className="system-status-dot" style={{ backgroundColor: row.color }} />
              <span className="system-status-label">{row.label}</span>
              <span className="system-status-text">{row.text}</span>
            </div>
          ))}
        </>
      )}
    </>
  )
}
