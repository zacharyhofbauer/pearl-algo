'use client'

import { ReactNode } from 'react'

interface UltrawideLayoutProps {
  // Left Column (30%): Header + Chart
  headerSection?: ReactNode
  chartSection: ReactNode
  // Right Area (70%): All data panels
  pearlAISection?: ReactNode         // Pearl AI (includes ML filter performance)
  systemStatusSection?: ReactNode    // System readiness dashboard
  signalActivitySection?: ReactNode  // Signal generation dashboard
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
 * └──────────────┴─────────────────────────────────────────────────────────────┘
 *      30%                                    70%
 */
export default function UltrawideLayout({
  headerSection,
  chartSection,
  pearlAISection,
  systemStatusSection,
  signalActivitySection,
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
      {/* Left Column: Header + Chart (30%) */}
      <div className="ultrawide-left">
        {headerSection && (
          <div className="ultrawide-header-compact">
            {headerSection}
          </div>
        )}
        <div className="ultrawide-chart-area">
          {chartSection}
        </div>
      </div>

      {/* Right Area: All Panels Grid (70%) */}
      <div className="ultrawide-right">
        <div className="ultrawide-panels-grid">
          {/* Row 1: Pearl AI & System Status (High Priority) */}
          {pearlAISection && <div className="panel-cell pearl-ai-cell">{pearlAISection}</div>}
          {systemStatusSection && <div className="panel-cell system-status-cell">{systemStatusSection}</div>}
          {signalActivitySection && <div className="panel-cell">{signalActivitySection}</div>}

          {/* Row 2: Performance & Positions */}
          {performanceSection && <div className="panel-cell">{performanceSection}</div>}
          {activePositionsSection && <div className="panel-cell">{activePositionsSection}</div>}
          {challengeSection && <div className="panel-cell">{challengeSection}</div>}
          {regimeSection && <div className="panel-cell">{regimeSection}</div>}

          {/* Row 3: Risk & Trading */}
          {riskMetricsSection && <div className="panel-cell">{riskMetricsSection}</div>}
          {equityCurveSection && <div className="panel-cell">{equityCurveSection}</div>}
          {recentTradesSection && <div className="panel-cell">{recentTradesSection}</div>}
          {analyticsSection && <div className="panel-cell">{analyticsSection}</div>}

          {/* Row 4: System & Config */}
          {systemHealthSection && <div className="panel-cell">{systemHealthSection}</div>}
          {signalDecisionsSection && <div className="panel-cell">{signalDecisionsSection}</div>}
          {marketPressureSection && <div className="panel-cell">{marketPressureSection}</div>}
          {configSection && <div className="panel-cell">{configSection}</div>}
        </div>
      </div>
    </div>
  )
}
