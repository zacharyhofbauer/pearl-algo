'use client'

import { DataPanel } from './DataPanelsContainer'

interface BuySellPressure {
  bias: 'buyers' | 'sellers' | 'mixed'
  strength: 'flat' | 'light' | 'moderate' | 'strong'
  score: number
  score_pct: number
  lookback_bars: number
  total_volume: number
  volume_ratio: number
}

interface MarketPressurePanelProps {
  pressure: BuySellPressure | null
}

export default function MarketPressurePanel({ pressure }: MarketPressurePanelProps) {
  if (!pressure) {
    return (
      <DataPanel title="Market Pressure" icon="📊">
        <div className="no-data-message">No pressure data available</div>
      </DataPanel>
    )
  }

  const getBiasClass = () => {
    switch (pressure.bias) {
      case 'buyers':
        return 'bias-buyers'
      case 'sellers':
        return 'bias-sellers'
      default:
        return 'bias-mixed'
    }
  }

  const getBiasLabel = () => {
    switch (pressure.bias) {
      case 'buyers':
        return 'BUYERS'
      case 'sellers':
        return 'SELLERS'
      default:
        return 'MIXED'
    }
  }

  const getStrengthArrows = () => {
    switch (pressure.strength) {
      case 'strong':
        return pressure.bias === 'buyers' ? '▲▲▲' : '▼▼▼'
      case 'moderate':
        return pressure.bias === 'buyers' ? '▲▲' : '▼▼'
      case 'light':
        return pressure.bias === 'buyers' ? '▲' : '▼'
      default:
        return '—'
    }
  }

  const getStrengthClass = () => {
    if (pressure.bias === 'mixed' || pressure.strength === 'flat') return 'strength-neutral'
    return pressure.bias === 'buyers' ? 'strength-positive' : 'strength-negative'
  }

  // Calculate bar position (0 = full sellers, 50 = neutral, 100 = full buyers)
  // score_pct ranges from -100 to +100, we need to map to 0-100
  const barPosition = Math.max(0, Math.min(100, (pressure.score_pct + 100) / 2))

  const formatVolumeRatio = (ratio: number) => {
    if (ratio >= 1) {
      return `${ratio.toFixed(1)}x`
    }
    return `${ratio.toFixed(2)}x`
  }

  return (
    <DataPanel title="Market Pressure" icon="📊">
      <div className="pressure-panel-content">
        {/* Bias Badge and Strength */}
        <div className="pressure-header">
          <span className={`pressure-bias-badge ${getBiasClass()}`}>
            {getBiasLabel()}
          </span>
          <span className={`pressure-strength ${getStrengthClass()}`}>
            {getStrengthArrows()}
            <span className="strength-label">{pressure.strength}</span>
          </span>
        </div>

        {/* Score Pressure Bar */}
        <div className="pressure-bar-container">
          <div className="pressure-bar-labels">
            <span className="pressure-bar-label sellers">Sellers</span>
            <span className="pressure-bar-label buyers">Buyers</span>
          </div>
          <div className="pressure-bar">
            <div className="pressure-bar-gradient"></div>
            <div
              className="pressure-bar-marker"
              style={{ left: `${barPosition}%` }}
            >
              <div className="pressure-marker-dot">
                <span className="pressure-marker-label">
                  {pressure.score_pct >= 0 ? '+' : ''}{pressure.score_pct.toFixed(0)}%
                </span>
              </div>
            </div>
          </div>
        </div>

        {/* Stats Row */}
        <div className="pressure-stats">
          <div className="pressure-stat">
            <span className="pressure-stat-label">Volume</span>
            <span className="pressure-stat-value">
              {formatVolumeRatio(pressure.volume_ratio)} baseline
            </span>
          </div>
          <div className="pressure-stat">
            <span className="pressure-stat-label">Lookback</span>
            <span className="pressure-stat-value">{pressure.lookback_bars} bars</span>
          </div>
        </div>
      </div>
    </DataPanel>
  )
}
