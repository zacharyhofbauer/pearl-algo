'use client'

import React from 'react'
import type {
  GatewayStatus,
  ConnectionHealth,
  TradovateAccount,
  DataQuality,
} from '@/stores/agentStore'
import type { WebSocketStatus } from '@/hooks/useWebSocket'
import { formatRelativeTime } from '@/lib/formatters'

interface HealthDotsProps {
  wsStatus: WebSocketStatus
  gateway: GatewayStatus | null
  connectionHealth: ConnectionHealth | null
  tradovate: TradovateAccount | null
  dataQuality: DataQuality | null
  /** Optional: timestamp of the most recent trade exit, used as a DB-writer proxy */
  lastExitTime?: string | null
}

type Health = 'ok' | 'warn' | 'offline' | 'unknown'

interface DotSpec {
  id: string
  label: string
  status: Health
  detail: string
}

function wsHealth(status: WebSocketStatus): Health {
  if (status === 'connected') return 'ok'
  if (status === 'connecting') return 'warn'
  return 'offline'
}

function gatewayHealth(g: GatewayStatus | null, c: ConnectionHealth | null): Health {
  if (!g) return 'unknown'
  if (g.status === 'online' && (c?.consecutive_errors ?? 0) === 0) return 'ok'
  if (g.status === 'degraded' || (c?.consecutive_errors ?? 0) > 0) return 'warn'
  return 'offline'
}

function dataHealth(d: DataQuality | null): Health {
  if (!d) return 'unknown'
  if (d.is_stale && !d.is_expected_stale) return 'offline'
  const ageM = d.latest_bar_age_minutes
  if (ageM == null) return 'unknown'
  if (ageM > (d.stale_threshold_minutes ?? 5)) return 'warn'
  return 'ok'
}

function tradovateHealth(t: TradovateAccount | null): Health {
  if (!t) return 'unknown'
  // Treat presence of equity as a heartbeat: backend only populates after a successful poll.
  if (typeof t.equity === 'number') return 'ok'
  return 'warn'
}

function dbWriterHealth(lastExitTime?: string | null): Health {
  if (!lastExitTime) return 'unknown'
  const t = Date.parse(lastExitTime)
  if (!Number.isFinite(t)) return 'unknown'
  const ageMin = (Date.now() - t) / 60000
  // Proxy: if last write < 24h ago we know the DB writer is still ticking.
  if (ageMin < 24 * 60) return 'ok'
  return 'warn'
}

function HealthDots({
  wsStatus,
  gateway,
  connectionHealth,
  tradovate,
  dataQuality,
  lastExitTime,
}: HealthDotsProps) {
  const dots: DotSpec[] = [
    {
      id: 'ws',
      label: 'WS',
      status: wsHealth(wsStatus),
      detail:
        wsStatus === 'connected'
          ? 'WebSocket connected — streaming live state'
          : wsStatus === 'connecting'
            ? 'WebSocket reconnecting'
            : 'WebSocket offline — falling back to HTTP polling',
    },
    {
      id: 'gw',
      label: 'GW',
      status: gatewayHealth(gateway, connectionHealth),
      detail: gateway
        ? `IBKR gateway ${gateway.status} on port ${gateway.port}${
            connectionHealth?.consecutive_errors
              ? ` · ${connectionHealth.consecutive_errors} consecutive errors`
              : ''
          }`
        : 'Gateway status unknown',
    },
    {
      id: 'data',
      label: 'DATA',
      status: dataHealth(dataQuality),
      detail: dataQuality
        ? `Latest bar ${dataQuality.latest_bar_age_minutes ?? '—'}m old (stale > ${
            dataQuality.stale_threshold_minutes ?? 5
          }m)${dataQuality.quiet_reason ? ` · ${dataQuality.quiet_reason}` : ''}`
        : 'Data quality unknown',
    },
    {
      id: 'tv',
      label: 'TV',
      status: tradovateHealth(tradovate),
      detail: tradovate
        ? `Tradovate ${tradovate.account ?? ''} (${tradovate.env ?? 'demo'})${
            typeof tradovate.equity === 'number' ? ` · equity $${tradovate.equity.toFixed(2)}` : ''
          }`
        : 'Tradovate not connected',
    },
    {
      id: 'db',
      label: 'DB',
      status: dbWriterHealth(lastExitTime),
      detail: lastExitTime
        ? `Last trade write ${formatRelativeTime(lastExitTime)}`
        : 'No DB writes seen this session',
    },
  ]

  return (
    <section className="info-strip-section info-strip-health" aria-label="System health">
      {dots.map((dot) => (
        <span
          key={dot.id}
          className={`info-strip-health-dot health-${dot.status}`}
          title={dot.detail}
          role="img"
          aria-label={`${dot.label}: ${dot.status}`}
        >
          <span className="info-strip-health-marker" aria-hidden />
          <span className="info-strip-health-label">{dot.label}</span>
        </span>
      ))}
    </section>
  )
}

export default React.memo(HealthDots)
