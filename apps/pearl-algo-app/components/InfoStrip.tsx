'use client'

import React from 'react'
import EquityCurveStrip from '@/components/info-strip/EquityCurveStrip'
import RiskChips from '@/components/info-strip/RiskChips'
import type { AgentState } from '@/stores/agentStore'
import type { Position } from '@/stores/chartStore'
import type { WebSocketStatus } from '@/hooks/useWebSocket'

interface InfoStripProps {
  agentState: AgentState | null
  positions: Position[]
  /** Kept in the props for API stability with DashboardPageInner — health
   *  dots themselves now render in the header, not here. */
  wsStatus?: WebSocketStatus
}

/**
 * Always-visible Bloomberg-style status row sitting between the header and the chart.
 *
 * Composes equity + risk; health dots moved to the header so they can sit
 * next to the RUN/OPN badges and free up the row that used to hold them.
 */
function InfoStrip({ agentState, positions }: InfoStripProps) {
  const equityCurve = agentState?.equity_curve ?? []
  const tradovate = agentState?.tradovate_account ?? null
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
    </div>
  )
}

export default React.memo(InfoStrip)
