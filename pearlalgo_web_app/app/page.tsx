'use client'

import { useState, useMemo, useCallback, useEffect } from 'react'
import Image from 'next/image'
import HelpPanel from '@/components/HelpPanel'
import AdminAuthModal from '@/components/AdminAuthModal'
import UltrawideLayout from '@/components/UltrawideLayout'
import PerformancePanel from '@/components/PerformancePanel'
import ChallengePanel from '@/components/ChallengePanel'
import RecentTradesPanel from '@/components/RecentTradesPanel'
import EquityCurvePanel from '@/components/EquityCurvePanel'
import RiskMetricsPanel from '@/components/RiskMetricsPanel'
import MarketPressurePanel from '@/components/MarketPressurePanel'
import SystemHealthPanel from '@/components/SystemHealthPanel'
import MarketRegimePanel from '@/components/MarketRegimePanel'
import SignalDecisionsPanel from '@/components/SignalDecisionsPanel'
import AnalyticsPanel from '@/components/AnalyticsPanel'
import ActivePositionsPanel from '@/components/ActivePositionsPanel'
import SystemStatusPanel from '@/components/SystemStatusPanel'
import SignalActivityPanel from '@/components/SignalActivityPanel'
import DataPanelsContainer from '@/components/DataPanelsContainer'
import ConfigPanel from '@/components/ConfigPanel'
import TradesHistoryPanel from '@/components/TradesHistoryPanel'
import PnLCalendarPanel from '@/components/PnLCalendarPanel'
import PositionsStrip from '@/components/PositionsStrip'
import { useViewportType } from '@/hooks/useViewportType'
import { useDashboardData } from '@/hooks/useDashboardData'
import { ChartSection, DashboardHeader } from '@/components/dashboard'
import { useAgentStore, useChartStore, type Position, type PositionLine } from '@/stores'
import type { IChartApi } from 'lightweight-charts'

// Format next market open time
const formatNextOpen = (isoString: string | null) => {
  if (!isoString) return ''
  try {
    const date = new Date(isoString)
    return date.toLocaleString('en-US', {
      weekday: 'short',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    })
  } catch {
    return ''
  }
}

export default function PearlAlgoWebApp() {
  // Agent store
  const agentState = useAgentStore((s) => s.agentState)

  // Chart store
  const candles = useChartStore((s) => s.candles)
  const marketStatus = useChartStore((s) => s.marketStatus)
  const chartLoading = useChartStore((s) => s.isLoading)
  const chartError = useChartStore((s) => s.error)
  const barSpacing = useChartStore((s) => s.barSpacing)
  const setBarSpacing = useChartStore((s) => s.setBarSpacing)
  const barCount = useChartStore((s) => s.barCount)
  const setBarCount = useChartStore((s) => s.setBarCount)

  // Local state for chart API reference
  const [mainChartApi, setMainChartApi] = useState<IChartApi | null>(null)

  // Local state for active positions (for chart price lines)
  const [positions, setPositions] = useState<Position[]>([])
  const [latestPrice, setLatestPrice] = useState<number | null>(null)
  const [pointValue, setPointValue] = useState<number>(2.0)

  // Viewport detection for ultrawide layout
  const viewport = useViewportType()

  // Minimum bars to request
  const MIN_BARS = 500

  // Responsive bar spacing - smaller on mobile to show more candles
  const getBarSpacing = useCallback(() => {
    if (typeof window === 'undefined') return 10
    if (window.innerWidth < 400) return 3  // Very small phones - most candles
    if (window.innerWidth < 768) return 4  // Mobile - more candles
    return 10  // Desktop
  }, [])

  // Calculate bar count based on viewport width
  const calculateBarCount = useCallback(() => {
    if (typeof window === 'undefined') return MIN_BARS
    const width = window.innerWidth
    const spacing = getBarSpacing()
    const priceScaleWidth = 60
    const availableWidth = width - priceScaleWidth - 40
    const visibleBars = Math.floor(availableWidth / spacing)
    return Math.max(MIN_BARS, Math.floor(visibleBars * 1.5))
  }, [getBarSpacing])

  // Update bar count and spacing on resize
  useEffect(() => {
    const update = () => {
      setBarSpacing(getBarSpacing())
      setBarCount(calculateBarCount())
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [getBarSpacing, calculateBarCount, setBarSpacing, setBarCount])

  // Data fetching hook
  const { forceRefresh } = useDashboardData({
    onPositionsUpdate: (pos, price, pv) => {
      setPositions(pos)
      setLatestPrice(price)
      setPointValue(pv)
    },
  })

  // Convert positions to price lines for chart visualization
  // Limits to recent positions and groups nearby prices to reduce clutter
  const positionLines = useMemo<PositionLine[]>(() => {
    // Limit to most recent positions to avoid chart flooding
    const MAX_POSITIONS = 5
    const recentPositions = positions.slice(-MAX_POSITIONS)

    const lines: PositionLine[] = []

    recentPositions.forEach((pos) => {
      // Entry price line - show axis label
      lines.push({
        price: pos.entry_price,
        color: pos.direction === 'long' ? 'rgba(0, 212, 255, 0.6)' : 'rgba(255, 110, 199, 0.6)',
        title: pos.direction === 'long' ? '↑' : '↓',
        lineStyle: 2,
        axisLabelVisible: true,
      })

      // Stop loss line - no axis label to reduce clutter
      if (pos.stop_loss) {
        lines.push({
          price: pos.stop_loss,
          color: 'rgba(255, 82, 82, 0.4)',
          title: '',
          lineStyle: 2,
          axisLabelVisible: false,
        })
      }

      // Take profit line - no axis label to reduce clutter
      if (pos.take_profit) {
        lines.push({
          price: pos.take_profit,
          color: 'rgba(0, 230, 118, 0.4)',
          title: '',
          lineStyle: 2,
          axisLabelVisible: false,
        })
      }
    })

    return lines
  }, [positions])

  // Track if chart is fully loaded (for screenshot detection)
  const isChartReady = !chartLoading && !chartError && candles.length > 0

  // Derive banner visibility for conditional class (avoids :has() CSS)
  const showBanner = marketStatus && !marketStatus.is_open

  // Ultrawide layout for Xeneon Edge (2560x720)
  if (viewport.isUltrawide && agentState) {
    return (
      <div className={`dashboard ultrawide-mode${showBanner ? ' has-banner' : ''}`} data-chart-ready={isChartReady ? 'true' : 'false'}>
        {/* Market Closed Banner */}
        {showBanner && (
          <div className="market-closed-banner ultrawide-banner">
            <span className="market-closed-icon">🔴</span>
            <span className="market-closed-text">
              Market Closed ({marketStatus.close_reason})
              {marketStatus.next_open && <> — Opens {formatNextOpen(marketStatus.next_open)}</>}
            </span>
          </div>
        )}

        <UltrawideLayout
          headerSection={<DashboardHeader variant="ultrawide" />}
          chartSection={
            <ChartSection
              mainChartApi={mainChartApi}
              positionLines={positionLines}
              positions={positions}
              recentExits={agentState.recent_exits}
              onChartReady={setMainChartApi}
              onForceRefresh={forceRefresh}
              marketStatus={marketStatus}
            />
          }
          rsiSection={null}
          pearlAISection={null}
          systemStatusSection={
            <SystemStatusPanel
              executionState={agentState.execution_state}
              circuitBreaker={agentState.circuit_breaker}
              marketRegime={agentState.market_regime}
              sessionContext={agentState.session_context}
              errorSummary={agentState.error_summary}
              isRunning={agentState.running}
              isPaused={agentState.paused}
            />
          }
          signalActivitySection={
            <SignalActivityPanel
              signalActivity={agentState.signal_activity}
              lastDecision={agentState.last_signal_decision}
            />
          }
          performanceSection={
            agentState.performance && (
              <PerformancePanel
                performance={agentState.performance}
                expectancy={agentState.risk_metrics?.expectancy}
              />
            )
          }
          activePositionsSection={
            <ActivePositionsPanel
              activeTradesCount={agentState.active_trades_count}
              recentExits={agentState.recent_exits}
            />
          }
          challengeSection={
            agentState.challenge && (
              <ChallengePanel
                challenge={agentState.challenge}
                equityCurve={agentState.equity_curve}
              />
            )
          }
          regimeSection={
            agentState.market_regime && (
              <MarketRegimePanel regime={agentState.market_regime} />
            )
          }
          riskMetricsSection={
            agentState.risk_metrics && (
              <RiskMetricsPanel riskMetrics={agentState.risk_metrics} />
            )
          }
          equityCurveSection={
            agentState.equity_curve && agentState.equity_curve.length > 0 && (
              <EquityCurvePanel equityCurve={agentState.equity_curve} />
            )
          }
          recentTradesSection={
            agentState.recent_exits && agentState.recent_exits.length > 0 && (
              <RecentTradesPanel
                recentExits={agentState.recent_exits}
                maxItems={8}
              />
            )
          }
          analyticsSection={
            agentState.analytics && (
              <AnalyticsPanel
                analytics={agentState.analytics}
                recentExits={agentState.recent_exits}
              />
            )
          }
          systemHealthSection={
            (agentState.cadence_metrics || agentState.gateway_status) && (
              <SystemHealthPanel
                cadenceMetrics={agentState.cadence_metrics || null}
                dataFresh={agentState.data_fresh || false}
                gatewayStatus={agentState.gateway_status}
                connectionHealth={agentState.connection_health}
                errorSummary={agentState.error_summary}
                dataQuality={agentState.data_quality}
              />
            )
          }
          signalDecisionsSection={
            (agentState.signal_rejections_24h || agentState.last_signal_decision) && (
              <SignalDecisionsPanel
                rejections={agentState.signal_rejections_24h || null}
                lastDecision={agentState.last_signal_decision || null}
              />
            )
          }
          marketPressureSection={
            agentState.buy_sell_pressure && (
              <MarketPressurePanel pressure={agentState.buy_sell_pressure} />
            )
          }
        />

        {/* Admin Auth Modal */}
        <AdminAuthModal />
      </div>
    )
  }

  // Standard layout (mobile, tablet, desktop)
  return (
    <div className={`dashboard${showBanner ? ' has-banner' : ''}`} data-chart-ready={isChartReady ? 'true' : 'false'}>
      {/* Market Closed Banner */}
      {showBanner && (
        <div className="market-closed-banner">
          <span className="market-closed-icon">🔴</span>
          <span className="market-closed-text">
            Market Closed ({marketStatus.close_reason})
            {marketStatus.next_open && (
              <> — Opens {formatNextOpen(marketStatus.next_open)}</>
            )}
          </span>
        </div>
      )}

      <DashboardHeader variant="standard" />

      <ChartSection
        mainChartApi={mainChartApi}
        positionLines={positionLines}
        positions={positions}
        recentExits={agentState?.recent_exits}
        onChartReady={setMainChartApi}
        onForceRefresh={forceRefresh}
        marketStatus={marketStatus}
      />

      {/* Positions Strip - detailed view of open positions */}
      {positions.length > 0 && (
        <PositionsStrip
          positions={positions}
          latestPrice={latestPrice}
          pointValue={pointValue}
        />
      )}

      {/* Data Panels */}
      {agentState && (
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

          {/* Full Trade History Panel */}
          {agentState.recent_exits && agentState.recent_exits.length > 0 && (
            <TradesHistoryPanel recentExits={agentState.recent_exits} />
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
      )}

      {/* Help Panel - Quick Reference */}
      <HelpPanel />

      {/* Admin Auth Modal */}
      <AdminAuthModal />
    </div>
  )
}
