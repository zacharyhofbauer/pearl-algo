'use client'

import { useMemo, useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { InfoTooltip, StatDisplay } from './ui'
import type { BuySellPressure, MarketRegime } from '@/stores'

interface MarketContextPanelProps {
  regime: MarketRegime | null
  pressure: BuySellPressure | null
}

type Tab = 'regime' | 'pressure'

export default function MarketContextPanel({ regime, pressure }: MarketContextPanelProps) {
  const availableTabs = useMemo<Tab[]>(() => {
    const tabs: Tab[] = []
    if (regime) tabs.push('regime')
    if (pressure) tabs.push('pressure')
    // If both are missing, default to both so user sees explicit “no data” messages.
    if (tabs.length === 0) return ['regime', 'pressure']
    return tabs
  }, [pressure, regime])

  const [tab, setTab] = useState<Tab>(() => {
    if (regime) return 'regime'
    if (pressure) return 'pressure'
    return 'regime'
  })

  const showTabs = availableTabs.length > 1

  const renderRegime = () => {
    if (!regime) {
      return <div className="no-data-message">No regime data available</div>
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
      if (regime.confidence === 0) return 'INSUFFICIENT DATA'
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
      <div className={`regime-panel-content ${isUnknown ? 'regime-panel-unknown' : ''}`}>
        <div className="regime-header">
          <span className={`regime-badge ${getRegimeClass()}`}>
            <span className="regime-icon">{getRegimeIcon()}</span>
            {getRegimeLabel()}
            {isUnknown && <InfoTooltip text="Regime detection requires recent price action" />}
          </span>
        </div>

        <div className="regime-confidence">
          <div className="regime-confidence-header">
            <span className="regime-confidence-label">Confidence</span>
            <span className="regime-confidence-value">{confidencePct.toFixed(0)}%</span>
          </div>
          <div className="regime-confidence-bar">
            <div className="regime-confidence-fill" style={{ width: `${confidencePct}%` }} />
          </div>
        </div>

        <div className="regime-direction">
          <span className="regime-direction-label">Allowed Direction</span>
          <span className={`regime-direction-badge ${getDirectionClass()}`}>{getDirectionLabel()}</span>
        </div>
      </div>
    )
  }

  const renderPressure = () => {
    if (!pressure) {
      return <div className="no-data-message">No pressure data available</div>
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

    const barPosition = Math.max(0, Math.min(100, (pressure.score_pct + 100) / 2))

    const formatVolumeRatio = (ratio: number) => {
      if (ratio >= 1) return `${ratio.toFixed(1)}x`
      return `${ratio.toFixed(2)}x`
    }

    return (
      <div className="pressure-panel-content">
        <div className="pressure-header">
          <span className={`pressure-bias-badge ${getBiasClass()}`}>{getBiasLabel()}</span>
          <span className={`pressure-strength ${getStrengthClass()}`}>
            {getStrengthArrows()}
            <span className="strength-label">{pressure.strength}</span>
          </span>
        </div>

        <div className="pressure-bar-container">
          <div className="pressure-bar-labels">
            <span className="pressure-bar-label sellers">Sellers</span>
            <span className="pressure-bar-label buyers">Buyers</span>
          </div>
          <div className="pressure-bar">
            <div className="pressure-bar-gradient" />
            <div className="pressure-bar-marker" style={{ left: `${barPosition}%` }}>
              <div className="pressure-marker-dot">
                <span className="pressure-marker-label">
                  {pressure.score_pct >= 0 ? '+' : ''}
                  {pressure.score_pct.toFixed(0)}%
                </span>
              </div>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-sm">
          <StatDisplay
            label="Volume"
            value={`${formatVolumeRatio(pressure.volume_ratio)} baseline`}
            variant="compact"
          />
          <StatDisplay label="Lookback" value={`${pressure.lookback_bars} bars`} variant="compact" />
        </div>
      </div>
    )
  }

  return (
    <DataPanel title="Market Context">
      {showTabs && (
        <div className="perf-tabs" role="tablist" aria-label="Market context tabs">
          {availableTabs.includes('regime') && (
            <button
              type="button"
              className={`perf-tab ${tab === 'regime' ? 'active' : ''}`}
              onClick={() => setTab('regime')}
              role="tab"
              aria-selected={tab === 'regime'}
            >
              Regime
            </button>
          )}
          {availableTabs.includes('pressure') && (
            <button
              type="button"
              className={`perf-tab ${tab === 'pressure' ? 'active' : ''}`}
              onClick={() => setTab('pressure')}
              role="tab"
              aria-selected={tab === 'pressure'}
            >
              Pressure
            </button>
          )}
        </div>
      )}

      {tab === 'pressure' ? renderPressure() : renderRegime()}
    </DataPanel>
  )
}

