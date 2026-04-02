'use client'

// ADDED 2026-03-25: live log streaming for dashboard

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { getApiUrl } from '@/lib/api'

interface LogEntry {
  ts: string
  level: 'info' | 'warn' | 'error' | 'debug'
  message: string
  id: number
}

const LEVEL_COLORS: Record<string, string> = {
  error: '#f44336',
  warn: '#ff9800',
  info: '#b0bec5',
  debug: '#546e7a',
}

export default function LiveLogsPanel() {
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [filter, setFilter] = useState<'all' | 'info' | 'warn' | 'error'>('all')
  const [paused, setPaused] = useState(false)
  const [connected, setConnected] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const atBottomRef = useRef(true)
  const counterRef = useRef(0)
  const pausedRef = useRef(false)

  pausedRef.current = paused

  const appendLog = useCallback((entry: Omit<LogEntry, 'id'>) => {
    if (pausedRef.current) return
    setLogs(prev => {
      const next = [...prev, { ...entry, id: ++counterRef.current }]
      return next.length > 500 ? next.slice(-500) : next
    })
  }, [])

  // Auto-scroll to bottom when new logs arrive
  useEffect(() => {
    const el = scrollRef.current
    if (!el || !atBottomRef.current) return
    el.scrollTop = el.scrollHeight
  }, [logs])

  const handleScroll = useCallback(() => {
    const el = scrollRef.current
    if (!el) return
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40
  }, [])

  // SSE connection
  useEffect(() => {
    const apiBase = getApiUrl()
    const apiKey =
      process.env.NEXT_PUBLIC_READONLY_API_KEY ||
      process.env.NEXT_PUBLIC_API_KEY ||
      ''
    const levelParam = filter === 'all' ? 'all' : filter
    const url = `${apiBase}/api/logs/stream?api_key=${encodeURIComponent(apiKey)}&lines=150&level=${levelParam}`

    let es: EventSource
    let reconnectTimer: ReturnType<typeof setTimeout>

    const connect = () => {
      es = new EventSource(url)
      es.onopen = () => setConnected(true)
      es.onerror = () => {
        setConnected(false)
        es.close()
        reconnectTimer = setTimeout(connect, 5000)
      }
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data)
          appendLog({ ts: data.ts, level: data.level, message: data.message })
        } catch {}
      }
    }

    connect()

    return () => {
      clearTimeout(reconnectTimer)
      if (es) es.close()
      setConnected(false)
    }
  }, [filter, appendLog])

  const filtered = filter === 'all' ? logs : logs.filter(l => l.level === filter)

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100%',
      background: '#0f1117',
      fontFamily: "'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
      fontSize: '11px',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '6px',
        padding: '8px 12px',
        borderBottom: '1px solid #1e2530',
        flexShrink: 0,
      }}>
        <span style={{ color: '#64748b', fontSize: '10px', fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase' }}>
          Agent Logs
        </span>
        {/* Connection dot */}
        <span style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: connected ? '#4caf50' : '#f44336',
          display: 'inline-block',
          marginLeft: 4,
        }} />
        <div style={{ flex: 1 }} />
        {/* Filter buttons */}
        {(['all', 'info', 'warn', 'error'] as const).map(lvl => (
          <button
            key={lvl}
            onClick={() => { setLogs([]); setFilter(lvl) }}
            style={{
              padding: '2px 7px',
              borderRadius: 3,
              border: 'none',
              background: filter === lvl ? '#1e2d40' : 'transparent',
              color: filter === lvl ? '#90caf9' : '#546e7a',
              cursor: 'pointer',
              fontSize: '10px',
              fontWeight: 600,
              textTransform: 'uppercase',
            }}
          >
            {lvl}
          </button>
        ))}
        {/* Pause button */}
        <button
          onClick={() => setPaused(p => !p)}
          style={{
            padding: '2px 7px',
            borderRadius: 3,
            border: 'none',
            background: paused ? '#2d1f1f' : 'transparent',
            color: paused ? '#f44336' : '#546e7a',
            cursor: 'pointer',
            fontSize: '10px',
            fontWeight: 600,
          }}
        >
          {paused ? '▶ RESUME' : '⏸ PAUSE'}
        </button>
      </div>

      {/* Log lines */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '4px 0',
        }}
      >
        {filtered.map(log => (
          <div
            key={log.id}
            style={{
              display: 'flex',
              gap: '8px',
              padding: '1px 12px',
              lineHeight: '1.5',
              borderLeft:
                log.level === 'error' ? '2px solid #f44336' :
                log.level === 'warn'  ? '2px solid #ff9800' :
                '2px solid transparent',
            }}
          >
            <span style={{ color: '#37474f', flexShrink: 0, minWidth: '58px' }}>{log.ts}</span>
            <span style={{ color: LEVEL_COLORS[log.level] || '#b0bec5', wordBreak: 'break-all' }}>
              {log.message}
            </span>
          </div>
        ))}
        {filtered.length === 0 && (
          <div style={{ color: '#37474f', padding: '20px 12px', textAlign: 'center' }}>
            {connected ? 'Waiting for logs...' : 'Connecting...'}
          </div>
        )}
      </div>
    </div>
  )
}
