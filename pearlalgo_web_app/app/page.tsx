'use client'

import { useState, useMemo, useCallback, useEffect } from 'react'
import Image from 'next/image'
import HelpPanel from '@/components/HelpPanel'
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
import { useViewportType } from '@/hooks/useViewportType'
import { useDashboardData } from '@/hooks/useDashboardData'
import { ChartSection, DashboardHeader, DataPanelsSection } from '@/components/dashboard'
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

  // Viewport detection for ultrawide layout
  const viewport = useViewportType()

  // Minimum bars to request
  const MIN_BARS = 500

  // Responsive bar spacing - smaller on mobile
  const getBarSpacing = useCallback(() => {
    if (typeof window === 'undefined') return 10
    return window.innerWidth < 768 ? 6 : 10
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
    onPositionsUpdate: setPositions,
  })

  // Convert positions to price lines for chart visualization
  // Groups lines at same/similar prices to avoid label clutter
  const positionLines = useMemo<PositionLine[]>(() => {
    // First collect all lines with their metadata
    const rawLines: Array<{
      price: number
      color: string
      title: string
      type: 'entry' | 'sl' | 'tp'
      direction: 'long' | 'short'
    }> = []

    positions.forEach((pos) => {
      // Entry price line
      rawLines.push({
        price: pos.entry_price,
        color: pos.direction === 'long' ? 'rgba(33, 150, 243, 0.55)' : 'rgba(156, 39, 176, 0.55)',
        title: pos.direction === 'long' ? '↑' : '↓',
        type: 'entry',
        direction: pos.direction as 'long' | 'short',
      })

      // Stop loss line
      if (pos.stop_loss) {
        rawLines.push({
          price: pos.stop_loss,
          color: 'rgba(244, 67, 54, 0.55)',
          title: '×',
          type: 'sl',
          direction: pos.direction as 'long' | 'short',
        })
      }

      // Take profit line
      if (pos.take_profit) {
        rawLines.push({
          price: pos.take_profit,
          color: 'rgba(76, 175, 80, 0.55)',
          title: '✓',
          type: 'tp',
          direction: pos.direction as 'long' | 'short',
        })
      }
    })

    // Group lines by price (within 0.25 point threshold for MNQ)
    const PRICE_THRESHOLD = 0.25
    const grouped: Array<{ price: number; items: typeof rawLines }> = []

    rawLines.forEach((line) => {
      // Find existing group within threshold
      const existingGroup = grouped.find(g => Math.abs(line.price - g.price) <= PRICE_THRESHOLD)
      if (existingGroup) {
        existingGroup.items.push(line)
      } else {
        grouped.push({ price: line.price, items: [line] })
      }
    })

    // Convert groups to position lines
    const lines: PositionLine[] = []
    grouped.forEach(({ price, items: group }) => {
      if (group.length === 1) {
        // Single line - use as-is
        const item = group[0]
        lines.push({
          price: item.price,
          color: item.color,
          title: item.title,
          lineStyle: 2,
          axisLabelVisible: true,
        })
      } else {
        // Multiple lines at same price - combine labels
        // Priority: Entry color if present, else use first item's color
        const hasEntry = group.some(g => g.type === 'entry')
        const hasSL = group.some(g => g.type === 'sl')
        const hasTP = group.some(g => g.type === 'tp')

        // Build combined title
        const titles: string[] = []
        if (hasEntry) {
          const entryItem = group.find(g => g.type === 'entry')
          titles.push(entryItem?.title || '●')
        }
        if (hasSL) titles.push('×')
        if (hasTP) titles.push('✓')

        // Choose color based on what's present (entry takes priority)
        let color = group[0].color
        if (hasEntry) {
          const entryItem = group.find(g => g.type === 'entry')
          color = entryItem?.color || color
        }

        // Average price for the group
        const avgPrice = group.reduce((sum, g) => sum + g.price, 0) / group.length

        lines.push({
          price: avgPrice,
          color,
          title: titles.join(''),
          lineStyle: 2,
          axisLabelVisible: true,
        })
      }
    })

    return lines
  }, [positions])

  // Track if chart is fully loaded (for screenshot detection)
  const isChartReady = !chartLoading && !chartError && candles.length > 0

  // Ultrawide layout for Xeneon Edge (2560x720)
  if (viewport.isUltrawide && agentState) {
    return (
      <div className={`dashboard ultrawide-mode`} data-chart-ready={isChartReady ? 'true' : 'false'}>
        {/* Market Closed Banner */}
        {marketStatus && !marketStatus.is_open && (
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
              onChartReady={setMainChartApi}
              onForceRefresh={forceRefresh}
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
              dailyPnL={agentState.daily_pnl}
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
      </div>
    )
  }

  // Standard layout (mobile, tablet, desktop)
  return (
    <div className="dashboard" data-chart-ready={isChartReady ? 'true' : 'false'}>
      {/* Market Closed Banner */}
      {marketStatus && !marketStatus.is_open && (
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
        onChartReady={setMainChartApi}
        onForceRefresh={forceRefresh}
      />

      {/* Data Panels */}
      {agentState && <DataPanelsSection agentState={agentState} />}

      {/* Help Panel - Quick Reference */}
      <HelpPanel />
    </div>
  )
}
