'use client'

import { memo, useMemo } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { InfoTooltip } from './ui'
import type { MarketRegime } from '@/stores'

interface MarketRegimePanelProps {
  regime: MarketRegime | null
}

function MarketRegimePanel({ regime }: MarketRegimePanelProps) {
  if (!regime) {
    return (
      <DataPanel title="Market Regime" icon="📈">
        <div className="no-data-message">No regime data available</div>
      </DataPanel>
    )
  }

  const isUnknown = regime.regime === 'unknown' || regime.confidence === 0
  const confidencePct = regime.confidence * 100

  const getRegimeClass = () => {
    switch (regime.regime) {
      case 'trending_up':
        return 'regime-trending-up'
      case 'trending_down':
        return 'regime-trending-down'
      case 'ranging':
        return 'regime-ranging'
      case 'volatile':
        return 'regime-volatile'
      default:
        return 'regime-unknown'
    }
  }

  const getRegimeLabel = () => {
    // Show "Insufficient Data" when confidence is 0
    if (regime.confidence === 0) {
      return 'INSUFFICIENT DATA'
    }
    switch (regime.regime) {
      case 'trending_up':
        return 'TRENDING UP'
      case 'trending_down':
        return 'TRENDING DOWN'
      case 'ranging':
        return 'RANGING'
      case 'volatile':
        return 'VOLATILE'
      case 'unknown':
        return 'INSUFFICIENT DATA'
      default:
        return regime.regime.toUpperCase().replace(/_/g, ' ')
    }
  }

  const getRegimeIcon = () => {
    if (regime.confidence === 0) return '⏳'
    switch (regime.regime) {
      case 'trending_up':
        return '📈'
      case 'trending_down':
        return '📉'
      case 'ranging':
        return '↔️'
      case 'volatile':
        return '⚡'
      default:
        return '⏳'
    }
  }

  const getDirectionClass = () => {
    switch (regime.allowed_direction) {
      case 'long':
        return 'direction-long'
      case 'short':
        return 'direction-short'
      default:
        return 'direction-both'
    }
  }

  const getDirectionLabel = () => {
    switch (regime.allowed_direction) {
      case 'long':
        return 'LONG ONLY'
      case 'short':
        return 'SHORT ONLY'
      default:
        return 'BOTH'
    }
  }

  return (
    <DataPanel title="Market Regime" icon="📈">
      <div className={`regime-panel-content ${isUnknown ? 'regime-panel-unknown' : ''}`}>
        {/* Regime Badge */}
        <div className="regime-header">
          <span className={`regime-badge ${getRegimeClass()}`}>
            <span className="regime-icon">{getRegimeIcon()}</span>
            {getRegimeLabel()}
            {isUnknown && <InfoTooltip text="Regime detection requires recent price action" />}
          </span>
        </div>

        {/* Confidence Bar */}
        <div className="regime-confidence">
          <div className="regime-confidence-header">
            <span className="regime-confidence-label">Confidence</span>
            <span className="regime-confidence-value">{confidencePct.toFixed(0)}%</span>
          </div>
          <div className="regime-confidence-bar">
            <div
              className="regime-confidence-fill"
              style={{ width: `${confidencePct}%` }}
            ></div>
          </div>
        </div>

        {/* Allowed Direction */}
        <div className="regime-direction">
          <span className="regime-direction-label">Allowed Direction</span>
          <span className={`regime-direction-badge ${getDirectionClass()}`}>
            {getDirectionLabel()}
          </span>
        </div>
      </div>
    </DataPanel>
  )
}

export default memo(MarketRegimePanel)
