'use client'

import { ReactNode } from 'react'

interface UltrawideLayoutProps {
  // Left Column (30%): Header + Chart
  headerSection?: ReactNode
  chartSection: ReactNode
  /** Optional dock below chart (e.g., Positions/Trades) */
  belowChartSection?: ReactNode
  // Right Area (70%): All data panels
  pearlAISection?: ReactNode         // Pearl AI (includes ML filter performance)
  systemStatusSection?: ReactNode    // System readiness dashboard
  challengeSection?: ReactNode
  marketContextSection?: ReactNode
  riskEquitySection?: ReactNode
  analyticsSection?: ReactNode
  systemHealthSection?: ReactNode
  signalDecisionsSection?: ReactNode
  configSection?: ReactNode
}

/**
 * UltrawideLayout: 2-column layout for ultrawide displays (32:9)
 *
 * Layout:
 * ┌──────────────┬─────────────────────────────────────────────────────────────┐
 * │   HEADER     │  PEARL AI  │  STATUS  │  CHALLENGE  │  CONTEXT             │
 * │  (compact)   ├─────────────┴──────────┴─────────────┴──────────────────────┤
 * ├──────────────┤  RISK+EQ   │  ANALYTICS  │  HEALTH  │  SIGNALS            │
 * │    CHART     │                                                             │
 * ├──────────────┤                                                             │
 * └──────────────┴─────────────────────────────────────────────────────────────┘
 *      30%                                    70%
 */
export default function UltrawideLayout({
  headerSection,
  chartSection,
  belowChartSection,
  pearlAISection,
  systemStatusSection,
  challengeSection,
  marketContextSection,
  riskEquitySection,
  analyticsSection,
  systemHealthSection,
  signalDecisionsSection,
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
        {belowChartSection && (
          <div className="ultrawide-below-chart">
            {belowChartSection}
          </div>
        )}
      </div>

      {/* Right Area: All Panels Grid (70%) */}
      <div className="ultrawide-right">
        <div className="ultrawide-panels-grid">
          {/* Row 1: Core context */}
          {pearlAISection && <div className="panel-cell pearl-ai-cell">{pearlAISection}</div>}
          {systemStatusSection && <div className="panel-cell system-status-cell">{systemStatusSection}</div>}
          {challengeSection && <div className="panel-cell">{challengeSection}</div>}
          {marketContextSection && <div className="panel-cell">{marketContextSection}</div>}

          {/* Row 2: Ops & analytics */}
          {riskEquitySection && <div className="panel-cell">{riskEquitySection}</div>}
          {analyticsSection && <div className="panel-cell">{analyticsSection}</div>}
          {systemHealthSection && <div className="panel-cell">{systemHealthSection}</div>}
          {signalDecisionsSection && <div className="panel-cell">{signalDecisionsSection}</div>}
          {configSection && <div className="panel-cell">{configSection}</div>}
        </div>
      </div>
    </div>
  )
}
