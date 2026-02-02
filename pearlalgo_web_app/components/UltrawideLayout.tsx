'use client'

import { ReactNode } from 'react'

interface UltrawideLayoutProps {
  // Left Column (30%): Header + Chart + RSI
  headerSection?: ReactNode
  chartSection: ReactNode
  rsiSection?: ReactNode
  // Right Area (70%): All data panels
  pearlAISection?: ReactNode
  performanceSection?: ReactNode
  activePositionsSection?: ReactNode
  challengeSection?: ReactNode
  regimeSection?: ReactNode
  riskMetricsSection?: ReactNode
  equityCurveSection?: ReactNode
  recentTradesSection?: ReactNode
  analyticsSection?: ReactNode
  systemHealthSection?: ReactNode
  signalDecisionsSection?: ReactNode
  marketPressureSection?: ReactNode
  configSection?: ReactNode
}

/**
 * UltrawideLayout: 2-column layout for ultrawide displays (32:9)
 *
 * Layout:
 * ┌──────────────┬─────────────────────────────────────────────────────────────┐
 * │   HEADER     │  PEARL AI  │  PERFORMANCE  │  POSITIONS  │  CHALLENGE      │
 * │  (compact)   ├─────────────┴───────────────┴─────────────┴─────────────────┤
 * ├──────────────┤  REGIME   │  RISK METRICS │  EQUITY CURVE │  TRADES        │
 * │              ├─────────────┴───────────────┴───────────────┴───────────────┤
 * │    CHART     │  ANALYTICS  │  HEALTH  │  SIGNALS  │  PRESSURE  │  CONFIG  │
 * │              │                                                             │
 * ├──────────────┤                                                             │
 * │     RSI      │                                                             │
 * └──────────────┴─────────────────────────────────────────────────────────────┘
 *      30%                                    70%
 */
export default function UltrawideLayout({
  headerSection,
  chartSection,
  rsiSection,
  pearlAISection,
  performanceSection,
  activePositionsSection,
  challengeSection,
  regimeSection,
  riskMetricsSection,
  equityCurveSection,
  recentTradesSection,
  analyticsSection,
  systemHealthSection,
  signalDecisionsSection,
  marketPressureSection,
  configSection,
}: UltrawideLayoutProps) {
  return (
    <div className="ultrawide-layout-v2">
      {/* Left Column: Header + Chart + RSI (30%) */}
      <div className="ultrawide-left">
        {headerSection && (
          <div className="ultrawide-header-compact">
            {headerSection}
          </div>
        )}
        <div className="ultrawide-chart-area">
          {chartSection}
        </div>
        {rsiSection && (
          <div className="ultrawide-rsi-area">
            {rsiSection}
          </div>
        )}
      </div>

      {/* Right Area: All Panels Grid (70%) */}
      <div className="ultrawide-right">
        <div className="ultrawide-panels-grid">
          {/* Row 1: Priority panels */}
          {pearlAISection && <div className="panel-cell pearl-ai-cell">{pearlAISection}</div>}
          {performanceSection && <div className="panel-cell">{performanceSection}</div>}
          {activePositionsSection && <div className="panel-cell">{activePositionsSection}</div>}
          {challengeSection && <div className="panel-cell">{challengeSection}</div>}

          {/* Row 2: Market state panels */}
          {regimeSection && <div className="panel-cell">{regimeSection}</div>}
          {riskMetricsSection && <div className="panel-cell">{riskMetricsSection}</div>}
          {equityCurveSection && <div className="panel-cell">{equityCurveSection}</div>}
          {recentTradesSection && <div className="panel-cell">{recentTradesSection}</div>}

          {/* Row 3: Secondary panels */}
          {analyticsSection && <div className="panel-cell">{analyticsSection}</div>}
          {systemHealthSection && <div className="panel-cell">{systemHealthSection}</div>}
          {signalDecisionsSection && <div className="panel-cell">{signalDecisionsSection}</div>}
          {marketPressureSection && <div className="panel-cell">{marketPressureSection}</div>}
          {configSection && <div className="panel-cell">{configSection}</div>}
        </div>
      </div>
    </div>
  )
}
