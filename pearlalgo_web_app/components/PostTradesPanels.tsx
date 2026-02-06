'use client'

import type { AgentState } from '@/stores'

import DataPanelsContainer from './DataPanelsContainer'
import SystemStatusPanel from './SystemStatusPanel'
import SignalDecisionsPanel from './SignalDecisionsPanel'
import RiskEquityPanel from './RiskEquityPanel'
import ChallengePanel from './ChallengePanel'
import MarketContextPanel from './MarketContextPanel'
import SystemHealthPanel from './SystemHealthPanel'
import AnalyticsPanel from './AnalyticsPanel'
import ConfigPanel from './ConfigPanel'
import HelpPanel from './HelpPanel'

interface PostTradesPanelsProps {
  agentState: AgentState
}

export default function PostTradesPanels({ agentState }: PostTradesPanelsProps) {
  return (
    <div className="post-trades-panels">
      {/* MFFU Eval panel -- first, right below trades */}
      {agentState.challenge && (
        <DataPanelsContainer>
          <ChallengePanel challenge={agentState.challenge} equityCurve={agentState.equity_curve} />
        </DataPanelsContainer>
      )}

      {/* Core panels (signals + readiness) */}
      <DataPanelsContainer>
        <div className="panel-span-all">
          <SystemStatusPanel
            executionState={agentState.execution_state}
            circuitBreaker={agentState.circuit_breaker}
            marketRegime={agentState.market_regime}
            sessionContext={agentState.session_context}
            errorSummary={agentState.error_summary}
            isRunning={agentState.running}
            isPaused={agentState.paused}
          />
        </div>

        {agentState.analytics && (
          <div className="panel-span-all">
            <AnalyticsPanel analytics={agentState.analytics} recentExits={agentState.recent_exits} />
          </div>
        )}

        {(agentState.signal_rejections_24h || agentState.last_signal_decision) && (
          <SignalDecisionsPanel
            rejections={agentState.signal_rejections_24h || null}
            lastDecision={agentState.last_signal_decision || null}
          />
        )}
      </DataPanelsContainer>

      {/* All panels visible (no toggle) */}
      <DataPanelsContainer>
        {(agentState.risk_metrics || (agentState.equity_curve && agentState.equity_curve.length > 0)) && (
          <RiskEquityPanel riskMetrics={agentState.risk_metrics} equityCurve={agentState.equity_curve || []} />
        )}

        {(agentState.market_regime || agentState.buy_sell_pressure) && (
          <MarketContextPanel regime={agentState.market_regime} pressure={agentState.buy_sell_pressure} />
        )}

        {(agentState.cadence_metrics ||
          agentState.gateway_status ||
          agentState.connection_health ||
          agentState.data_quality) && (
          <SystemHealthPanel
            cadenceMetrics={agentState.cadence_metrics || null}
            dataFresh={agentState.data_fresh || false}
            gatewayStatus={agentState.gateway_status}
            connectionHealth={agentState.connection_health}
            errorSummary={agentState.error_summary}
            dataQuality={agentState.data_quality}
          />
        )}

        {agentState.config && <ConfigPanel config={agentState.config} />}
      </DataPanelsContainer>

      <HelpPanel />
    </div>
  )
}
