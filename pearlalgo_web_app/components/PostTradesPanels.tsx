'use client'

import { useEffect, useState } from 'react'
import type { AgentState } from '@/stores'

import DataPanelsContainer from './DataPanelsContainer'
import SystemStatusPanel from './SystemStatusPanel'
import SignalActivityPanel from './SignalActivityPanel'
import SignalDecisionsPanel from './SignalDecisionsPanel'
import PerformancePanel from './PerformancePanel'
import RiskMetricsPanel from './RiskMetricsPanel'
import EquityCurvePanel from './EquityCurvePanel'
import ChallengePanel from './ChallengePanel'
import MarketPressurePanel from './MarketPressurePanel'
import MarketRegimePanel from './MarketRegimePanel'
import SystemHealthPanel from './SystemHealthPanel'
import AnalyticsPanel from './AnalyticsPanel'
import ConfigPanel from './ConfigPanel'
import HelpPanel from './HelpPanel'

interface PostTradesPanelsProps {
  agentState: AgentState
}

const LS_KEY = 'pearl.dashboard.showAdvancedPanels'

export default function PostTradesPanels({ agentState }: PostTradesPanelsProps) {
  const [showAdvanced, setShowAdvanced] = useState(false)

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(LS_KEY)
      if (raw === '1') setShowAdvanced(true)
    } catch {
      // ignore
    }
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(LS_KEY, showAdvanced ? '1' : '0')
    } catch {
      // ignore
    }
  }, [showAdvanced])

  return (
    <div className="post-trades-panels">
      {/* Core panels (signals + readiness) */}
      <DataPanelsContainer>
        <SignalActivityPanel
          signalActivity={agentState.signal_activity}
        />

        {(agentState.signal_rejections_24h || agentState.last_signal_decision) && (
          <SignalDecisionsPanel
            rejections={agentState.signal_rejections_24h || null}
            lastDecision={agentState.last_signal_decision || null}
          />
        )}

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

        {agentState.performance && (
          <div className="panel-span-all">
            <PerformancePanel
              performance={agentState.performance}
              expectancy={agentState.risk_metrics?.expectancy}
            />
          </div>
        )}
      </DataPanelsContainer>

      {/* Advanced (big) panels */}
      <div className="post-trades-advanced-toggle-wrap">
        <button
          type="button"
          className="post-trades-advanced-toggle"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          <span className="post-trades-advanced-label">More panels</span>
          <span className="post-trades-advanced-sub">risk • equity • config</span>
          <span className="post-trades-advanced-icon">{showAdvanced ? '▲' : '▼'}</span>
        </button>
      </div>

      {showAdvanced && (
        <DataPanelsContainer>
          {agentState.risk_metrics && <RiskMetricsPanel riskMetrics={agentState.risk_metrics} />}

          {agentState.equity_curve && agentState.equity_curve.length > 0 && (
            <EquityCurvePanel equityCurve={agentState.equity_curve} />
          )}

          {agentState.challenge && (
            <ChallengePanel challenge={agentState.challenge} equityCurve={agentState.equity_curve} />
          )}

          {agentState.buy_sell_pressure && <MarketPressurePanel pressure={agentState.buy_sell_pressure} />}

          {agentState.market_regime && <MarketRegimePanel regime={agentState.market_regime} />}

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
      )}

      <HelpPanel />
    </div>
  )
}

