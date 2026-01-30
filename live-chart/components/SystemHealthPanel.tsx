'use client'

import { DataPanel } from './DataPanelsContainer'

interface CadenceMetrics {
  cycle_duration_ms: number
  duration_p50_ms: number
  duration_p95_ms: number
  velocity_mode_active: boolean
  velocity_reason: string
  missed_cycles: number
  current_interval_seconds: number
  cadence_lag_ms: number
}

interface SystemHealthPanelProps {
  cadenceMetrics: CadenceMetrics | null
  dataFresh: boolean
}

export default function SystemHealthPanel({ cadenceMetrics, dataFresh }: SystemHealthPanelProps) {
  if (!cadenceMetrics) {
    return (
      <DataPanel title="System Health" icon="🔧">
        <div className="no-data-message">No system data available</div>
      </DataPanel>
    )
  }

  const formatMs = (ms: number) => {
    if (ms < 1000) {
      return `${ms.toFixed(0)}ms`
    }
    return `${(ms / 1000).toFixed(1)}s`
  }

  const getCycleHealthClass = () => {
    if (cadenceMetrics.cycle_duration_ms > cadenceMetrics.duration_p95_ms) {
      return 'health-warning'
    }
    if (cadenceMetrics.cadence_lag_ms > 1000) {
      return 'health-warning'
    }
    return 'health-ok'
  }

  return (
    <DataPanel title="System Health" icon="🔧">
      <div className="health-panel-content">
        {/* Data Freshness Indicator */}
        <div className="health-indicator-row">
          <div className="health-indicator">
            <span className={`health-dot ${dataFresh ? 'fresh' : 'stale'}`}></span>
            <span className="health-indicator-label">
              Data {dataFresh ? 'Fresh' : 'Stale'}
            </span>
          </div>
          <div className="health-indicator">
            <span className={`health-dot ${cadenceMetrics.velocity_mode_active ? 'active' : 'inactive'}`}></span>
            <span className="health-indicator-label">
              Velocity {cadenceMetrics.velocity_mode_active ? 'ON' : 'OFF'}
            </span>
          </div>
        </div>

        {/* Cycle Time Stats */}
        <div className="health-stats">
          <div className="health-stat">
            <span className="health-stat-label">Last Cycle</span>
            <span className={`health-stat-value ${getCycleHealthClass()}`}>
              {formatMs(cadenceMetrics.cycle_duration_ms)}
            </span>
          </div>
          <div className="health-stat">
            <span className="health-stat-label">p50 / p95</span>
            <span className="health-stat-value">
              {formatMs(cadenceMetrics.duration_p50_ms)} / {formatMs(cadenceMetrics.duration_p95_ms)}
            </span>
          </div>
          <div className="health-stat">
            <span className="health-stat-label">Interval</span>
            <span className="health-stat-value">
              {cadenceMetrics.current_interval_seconds}s
            </span>
          </div>
          <div className="health-stat">
            <span className="health-stat-label">Missed</span>
            <span className={`health-stat-value ${cadenceMetrics.missed_cycles > 0 ? 'health-warning' : ''}`}>
              {cadenceMetrics.missed_cycles}
            </span>
          </div>
        </div>

        {/* Cadence Lag */}
        {cadenceMetrics.cadence_lag_ms > 100 && (
          <div className="health-lag">
            <span className="health-lag-label">Lag:</span>
            <span className={`health-lag-value ${cadenceMetrics.cadence_lag_ms > 500 ? 'health-warning' : ''}`}>
              {formatMs(cadenceMetrics.cadence_lag_ms)}
            </span>
          </div>
        )}

        {/* Velocity Reason (if active) */}
        {cadenceMetrics.velocity_mode_active && cadenceMetrics.velocity_reason && (
          <div className="health-velocity-reason">
            {cadenceMetrics.velocity_reason}
          </div>
        )}
      </div>
    </DataPanel>
  )
}
