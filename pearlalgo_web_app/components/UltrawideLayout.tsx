'use client'

import { ReactNode } from 'react'

interface UltrawideLayoutProps {
  // Column 1: Chart (60%)
  chartSection: ReactNode
  rsiSection?: ReactNode
  // Column 2: Key Metrics (20%)
  performanceSection?: ReactNode
  challengeSection?: ReactNode
  // Column 3: Status & Trades (20%)
  regimeSection?: ReactNode
  aiStatusSection?: ReactNode
  recentTradesSection?: ReactNode
}

/**
 * UltrawideLayout: Clean 3-column layout for 2560x720 (32:9) displays
 *
 * Layout (simplified for readability):
 * ┌────────────────────────────────────────────────────────────────────────────────┐
 * │                                 │  PERFORMANCE    │  REGIME + AI STATUS       │
 * │   TRADINGVIEW CHART             │  (P&L, Stats)   │  (Market state badges)    │
 * │   (Full candlestick + volume)   │                 │                           │
 * │                                 │  CHALLENGE      │  RECENT TRADES            │
 * │   [1m][5m][15m][1h]             │  (Balance/PnL)  │  (Last 5 trades)          │
 * │                                 │                 │                           │
 * │   [RSI Panel]                   │                 │                           │
 * └─────────────────────────────────┴─────────────────┴───────────────────────────┘
 *          ~60% width                    ~20% width           ~20% width
 */
export default function UltrawideLayout({
  chartSection,
  rsiSection,
  performanceSection,
  challengeSection,
  regimeSection,
  aiStatusSection,
  recentTradesSection,
}: UltrawideLayoutProps) {
  return (
    <div className="ultrawide-layout">
      {/* Column 1: Chart Area (60%) */}
      <div className="ultrawide-chart-column">
        {chartSection}
        {rsiSection}
      </div>

      {/* Column 2: Key Metrics (20%) */}
      <div className="ultrawide-metrics-column">
        {performanceSection}
        {challengeSection}
      </div>

      {/* Column 3: Status & Trades (20%) */}
      <div className="ultrawide-status-column">
        <div className="ultrawide-status-badges">
          {regimeSection}
          {aiStatusSection}
        </div>
        <div className="ultrawide-trades-section">
          {recentTradesSection}
        </div>
      </div>
    </div>
  )
}

/**
 * Compact wrapper for data panels in ultrawide mode
 * Reduces padding and font sizes for higher information density
 */
interface CompactPanelProps {
  children: ReactNode
  className?: string
}

export function CompactPanel({ children, className = '' }: CompactPanelProps) {
  return (
    <div className={`compact-panel ${className}`}>
      {children}
    </div>
  )
}
