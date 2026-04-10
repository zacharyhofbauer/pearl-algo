'use client'

import React from 'react'
import EquityCurveStrip from '@/components/info-strip/EquityCurveStrip'
import RiskChips from '@/components/info-strip/RiskChips'
import HealthDots from '@/components/info-strip/HealthDots'
import type { AgentState } from '@/stores/agentStore'
import type { Position } from '@/stores/chartStore'
import type { WebSocketStatus } from '@/hooks/useWebSocket'

interface InfoStripProps {
  agentState: AgentState | null
  positions: Position[]
  wsStatus: WebSocketStatus
}

/**
 * Always-visible Bloomberg-style status row sitting between the header and the chart.
 *
 * Composes three independent sections, each driven directly by agentState. Every
 * field rendered here is data that already streams in via /api/state or the WS
 * channel — this component does no fetching of its own.
 */
function InfoStrip({ agentState, positions, wsStatus }: InfoStripProps) {
  const equityCurve = agentState?.equity_curve ?? []
  const tradovate = agentState?.tradovate_account ?? null
  const lastExitTime = agentState?.recent_exits?.[0]?.exit_time ?? null
  const symbol = agentState?.config?.symbol

  return (
    <div className="info-strip" role="status" aria-label="Live system metrics">
      <EquityCurveStrip curve={equityCurve} tradovate={tradovate} />
      <RiskChips
        positions={positions}
        riskMetrics={agentState?.risk_metrics ?? null}
        circuitBreaker={agentState?.circuit_breaker ?? null}
        executionState={agentState?.execution_state ?? null}
        activePositions={agentState?.active_trades_count}
        defaultSymbol={symbol}
      />
      <HealthDots
        wsStatus={wsStatus}
        gateway={agentState?.gateway_status ?? null}
        connectionHealth={agentState?.connection_health ?? null}
        tradovate={agentState?.tradovate_account ?? null}
        dataQuality={agentState?.data_quality ?? null}
        lastExitTime={lastExitTime}
      />
    </div>
  )
}

export default React.memo(InfoStrip)
