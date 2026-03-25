'use client'

import { useState, useCallback } from 'react'
import { useChartSettingsStore, type IndicatorVisibility } from '@/stores'

/**
 * TradingView-style chart legend overlay — sits top-left of chart.
 * Shows active indicators with color swatches, values, eye toggle, and gear icon.
 */

interface IndicatorConfig {
  key: keyof IndicatorVisibility
  label: string
  color: string
  /** Also toggles this key when toggled (e.g. ema21 with ema9) */
  linkedKey?: keyof IndicatorVisibility
  group: 'trend' | 'volatility' | 'levels' | 'pane'
}

const INDICATORS: IndicatorConfig[] = [
  { key: 'ema9', label: 'EMA Cross', color: '#00d4ff', linkedKey: 'ema21', group: 'trend' },
  { key: 'vwap', label: 'VWAP', color: 'rgba(100,181,246,0.85)', group: 'trend' },
  { key: 'vwapBands', label: 'VWAP Bands', color: 'rgba(76,175,80,0.5)', group: 'volatility' },
  { key: 'bollingerBands', label: 'BB(20,2)', color: 'rgba(41,98,255,0.7)', group: 'volatility' },
  { key: 'atrBands', label: 'ATR(14)', color: 'rgba(255,152,0,0.5)', group: 'volatility' },
  { key: 'keyLevels', label: 'Key Levels', color: '#08bcd4', group: 'levels' },
  { key: 'sessions', label: 'Sessions', color: 'rgba(8,153,129,0.5)', group: 'levels' },
  { key: 'srPowerZones', label: 'S&R Power', color: '#ab47bc', group: 'levels' },
  { key: 'sdZones', label: 'S/D Zones', color: 'rgba(255,193,7,0.4)', group: 'levels' },
  { key: 'tbtTrendlines', label: 'Trendlines', color: '#ff9800', group: 'levels' },
  { key: 'rsi', label: 'RSI(14)', color: '#7c4dff', group: 'pane' },
  { key: 'volume', label: 'Volume', color: 'rgba(38,166,154,0.35)', group: 'pane' },
]

interface ChartLegendProps {
  collapsed?: boolean
}

export default function ChartLegend({ collapsed = false }: ChartLegendProps) {
  const indicators = useChartSettingsStore((s) => s.indicators)
  const toggleIndicator = useChartSettingsStore((s) => s.toggleIndicator)
  const [isExpanded, setIsExpanded] = useState(!collapsed)
  const [activeGroup, setActiveGroup] = useState<string | null>(null)

  const handleToggle = useCallback((ind: IndicatorConfig) => {
    toggleIndicator(ind.key)
    if (ind.linkedKey) toggleIndicator(ind.linkedKey)
  }, [toggleIndicator])

  const activeIndicators = INDICATORS.filter(ind => indicators[ind.key])
  const groups = [
    { id: 'trend', label: 'Trend' },
    { id: 'volatility', label: 'Bands' },
    { id: 'levels', label: 'Levels' },
    { id: 'pane', label: 'Panes' },
  ]

  return (
    <div className="chart-legend">
      {/* Compact: just show indicator count + expand button */}
      <button
        className="legend-toggle"
        onClick={() => setIsExpanded(!isExpanded)}
        title={isExpanded ? 'Collapse indicators' : 'Expand indicators'}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="1,12 4,4 8,10 12,2 15,8" />
        </svg>
        <span className="legend-count">{activeIndicators.length}</span>
        <svg className={`legend-chevron ${isExpanded ? 'open' : ''}`} width="10" height="10" viewBox="0 0 10 10" fill="none" stroke="currentColor" strokeWidth="1.5">
          <polyline points="2,3.5 5,6.5 8,3.5" />
        </svg>
      </button>

      {isExpanded && (
        <div className="legend-body">
          {/* Active indicators - inline row */}
          <div className="legend-active">
            {activeIndicators.map(ind => (
              <span key={ind.key} className="legend-item">
                <span className="legend-swatch" style={{ background: ind.color }} />
                <span className="legend-label">{ind.label}</span>
                <button
                  className="legend-eye"
                  onClick={() => handleToggle(ind)}
                  title={`Hide ${ind.label}`}
                >
                  <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M1 8s3-5 7-5 7 5 7 5-3 5-7 5-7-5-7-5z" />
                    <circle cx="8" cy="8" r="2" />
                  </svg>
                </button>
              </span>
            ))}
          </div>

          {/* Group tabs for adding/removing indicators */}
          <div className="legend-groups">
            {groups.map(g => (
              <button
                key={g.id}
                className={`legend-group-btn ${activeGroup === g.id ? 'active' : ''}`}
                onClick={() => setActiveGroup(activeGroup === g.id ? null : g.id)}
              >
                {g.label}
              </button>
            ))}
          </div>

          {/* Expanded group panel */}
          {activeGroup && (
            <div className="legend-group-panel">
              {INDICATORS.filter(ind => ind.group === activeGroup).map(ind => (
                <div
                  key={ind.key}
                  className={`legend-group-item ${indicators[ind.key] ? 'active' : ''}`}
                  onClick={() => handleToggle(ind)}
                >
                  <span className="legend-swatch" style={{ background: ind.color }} />
                  <span className="legend-group-label">{ind.label}</span>
                  <span className={`legend-check ${indicators[ind.key] ? 'on' : ''}`}>
                    {indicators[ind.key] ? '\u2713' : ''}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
