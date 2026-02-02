'use client'

import DataPanelsContainer from '@/components/DataPanelsContainer'
import PerformancePanel from '@/components/PerformancePanel'
import ChallengePanel from '@/components/ChallengePanel'
import RecentTradesPanel from '@/components/RecentTradesPanel'
import EquityCurvePanel from '@/components/EquityCurvePanel'
import RiskMetricsPanel from '@/components/RiskMetricsPanel'
import MarketPressurePanel from '@/components/MarketPressurePanel'
import SystemHealthPanel from '@/components/SystemHealthPanel'
import ConfigPanel from '@/components/ConfigPanel'
import MarketRegimePanel from '@/components/MarketRegimePanel'
import SignalDecisionsPanel from '@/components/SignalDecisionsPanel'
import AnalyticsPanel from '@/components/AnalyticsPanel'
import ActivePositionsPanel from '@/components/ActivePositionsPanel'
import PnLCalendarPanel from '@/components/PnLCalendarPanel'
import SystemStatusPanel from '@/components/SystemStatusPanel'
import SignalActivityPanel from '@/components/SignalActivityPanel'
import { type AgentState } from '@/stores'

interface DataPanelsSectionProps {
  agentState: AgentState
}

export function DataPanelsSection({ agentState }: DataPanelsSectionProps) {
  return (
    <DataPanelsContainer>
      {/* System Status - Operational Readiness */}
      <SystemStatusPanel
        executionState={agentState.execution_state}
        circuitBreaker={agentState.circuit_breaker}
        marketRegime={agentState.market_regime}
        sessionContext={agentState.session_context}
        errorSummary={agentState.error_summary}
        isRunning={agentState.running}
        isPaused={agentState.paused}
      />

      {/* Signal Activity - Explain Trading Silence */}
      <SignalActivityPanel
        signalActivity={agentState.signal_activity}
        lastDecision={agentState.last_signal_decision}
      />

      {/* Performance Panel */}
      {agentState.performance && (
        <PerformancePanel
          performance={agentState.performance}
          expectancy={agentState.risk_metrics?.expectancy}
        />
      )}

      {/* Active Positions Panel */}
      <ActivePositionsPanel
        activeTradesCount={agentState.active_trades_count}
        recentExits={agentState.recent_exits}
        dailyPnL={agentState.daily_pnl}
      />

      {/* Risk Metrics Panel */}
      {agentState.risk_metrics && (
        <RiskMetricsPanel riskMetrics={agentState.risk_metrics} />
      )}

      {/* Equity Curve Panel */}
      {agentState.equity_curve && agentState.equity_curve.length > 0 && (
        <EquityCurvePanel equityCurve={agentState.equity_curve} />
      )}

      {/* Challenge Panel */}
      {agentState.challenge && (
        <ChallengePanel
          challenge={agentState.challenge}
          equityCurve={agentState.equity_curve}
        />
      )}

      {/* Market Pressure Panel */}
      {agentState.buy_sell_pressure && (
        <MarketPressurePanel pressure={agentState.buy_sell_pressure} />
      )}

      {/* Market Regime Panel */}
      {agentState.market_regime && (
        <MarketRegimePanel regime={agentState.market_regime} />
      )}

      {/* Signal Decisions Panel */}
      {(agentState.signal_rejections_24h || agentState.last_signal_decision) && (
        <SignalDecisionsPanel
          rejections={agentState.signal_rejections_24h || null}
          lastDecision={agentState.last_signal_decision || null}
        />
      )}

      {/* Config Panel */}
      {agentState.config && (
        <ConfigPanel config={agentState.config} />
      )}

      {/* System Health Panel */}
      {(agentState.cadence_metrics || agentState.gateway_status || agentState.connection_health || agentState.data_quality) && (
        <SystemHealthPanel
          cadenceMetrics={agentState.cadence_metrics || null}
          dataFresh={agentState.data_fresh || false}
          gatewayStatus={agentState.gateway_status}
          connectionHealth={agentState.connection_health}
          errorSummary={agentState.error_summary}
          dataQuality={agentState.data_quality}
        />
      )}

      {/* Recent Trades Panel */}
      {agentState.recent_exits && agentState.recent_exits.length > 0 && (
        <RecentTradesPanel
          recentExits={agentState.recent_exits}
          directionBreakdown={agentState.analytics?.direction_breakdown}
          statusBreakdown={agentState.analytics?.status_breakdown}
        />
      )}

      {/* Analytics Panel */}
      {agentState.analytics && (
        <AnalyticsPanel
          analytics={agentState.analytics}
          recentExits={agentState.recent_exits}
        />
      )}

      {/* P&L Calendar */}
      {agentState.recent_exits && agentState.recent_exits.length > 0 && (
        <PnLCalendarPanel recentExits={agentState.recent_exits} />
      )}
    </DataPanelsContainer>
  )
}

export default DataPanelsSection
