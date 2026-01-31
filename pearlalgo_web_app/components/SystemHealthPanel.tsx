'use client'

import { DataPanel } from './DataPanelsContainer'
import { StatDisplay } from './ui'
import type {
  CadenceMetrics,
  GatewayStatus,
  ConnectionHealth,
  ErrorSummary,
  DataQuality
} from '@/stores'

interface SystemHealthPanelProps {
  cadenceMetrics: CadenceMetrics | null
  dataFresh: boolean
  gatewayStatus?: GatewayStatus | null
  connectionHealth?: ConnectionHealth | null
  errorSummary?: ErrorSummary | null
  dataQuality?: DataQuality | null
}

export default function SystemHealthPanel({
  cadenceMetrics,
  dataFresh,
  gatewayStatus,
  connectionHealth,
  errorSummary,
  dataQuality,
}: SystemHealthPanelProps) {
  const formatMs = (ms: number) => {
    if (ms < 1000) {
      return `${ms.toFixed(0)}ms`
    }
    return `${(ms / 1000).toFixed(1)}s`
  }

  const getCycleHealthClass = () => {
    if (!cadenceMetrics) return ''
    if (cadenceMetrics.cycle_duration_ms > cadenceMetrics.duration_p95_ms) {
      return 'health-warning'
    }
    if (cadenceMetrics.cadence_lag_ms > 1000) {
      return 'health-warning'
    }
    return 'health-ok'
  }

  const getGatewayStatusClass = () => {
    if (!gatewayStatus) return 'inactive'
    switch (gatewayStatus.status) {
      case 'online': return 'fresh'
      case 'degraded': return 'warning'
      case 'offline': return 'stale'
      default: return 'inactive'
    }
  }

  const getConnectionStatusClass = () => {
    if (!connectionHealth) return 'inactive'
    if (connectionHealth.consecutive_errors > 3) return 'stale'
    if (connectionHealth.consecutive_errors > 0) return 'warning'
    return 'fresh'
  }

  const getDataQualityClass = () => {
    if (!dataQuality) return 'inactive'
    if (dataQuality.is_stale && !dataQuality.is_expected_stale) return 'stale'
    if (dataQuality.is_stale && dataQuality.is_expected_stale) return 'warning'
    return 'fresh'
  }

  // Show loading state if no data at all
  if (!cadenceMetrics && !gatewayStatus && !connectionHealth && !errorSummary && !dataQuality) {
    return (
      <DataPanel title="System Health" icon="🔧" variant="status">
        <div className="no-data-message">No system data available</div>
      </DataPanel>
    )
  }

  return (
    <DataPanel title="System Health" icon="🔧" variant="status">
      <div className="health-panel-content">
        {/* Gateway Status Section */}
        {gatewayStatus && (
          <div className="health-section">
            <div className="health-section-header">
              <span className={`health-dot ${getGatewayStatusClass()}`}></span>
              <span className="health-section-title">Gateway</span>
              <span className={`health-section-status ${gatewayStatus.status}`}>
                {gatewayStatus.status === 'online' ? 'Online' :
                 gatewayStatus.status === 'degraded' ? 'Degraded' : 'Offline'}
              </span>
            </div>
            <div className="health-section-details">
              <span className="health-check-item">
                <span className={gatewayStatus.process_running ? 'check-ok' : 'check-fail'}>
                  {gatewayStatus.process_running ? '✓' : '✗'}
                </span>
                Process
              </span>
              <span className="health-check-item">
                <span className={gatewayStatus.port_listening ? 'check-ok' : 'check-fail'}>
                  {gatewayStatus.port_listening ? '✓' : '✗'}
                </span>
                Port {gatewayStatus.port}
              </span>
            </div>
          </div>
        )}

        {/* Connection Status Section */}
        {connectionHealth && (
          <div className="health-section">
            <div className="health-section-header">
              <span className={`health-dot ${getConnectionStatusClass()}`}></span>
              <span className="health-section-title">Connection</span>
              <span className={`health-section-status ${connectionHealth.consecutive_errors > 0 ? 'warning' : 'online'}`}>
                {connectionHealth.consecutive_errors > 0 ? 'Issues' : 'Healthy'}
              </span>
            </div>
            <div className="health-section-details">
              <span className="health-detail-item">
                Failures: <span className={connectionHealth.connection_failures > 0 ? 'value-warning' : 'value-ok'}>
                  {connectionHealth.connection_failures}
                </span>
              </span>
              <span className="health-detail-item">
                Errors: <span className={connectionHealth.data_fetch_errors > 0 ? 'value-warning' : 'value-ok'}>
                  {connectionHealth.data_fetch_errors}
                </span>
              </span>
              <span className="health-detail-item">
                Level: <span className="value-neutral">{connectionHealth.data_level}</span>
              </span>
            </div>
          </div>
        )}

        {/* Data Quality Section */}
        {dataQuality && (
          <div className="health-section">
            <div className="health-section-header">
              <span className={`health-dot ${getDataQualityClass()}`}></span>
              <span className="health-section-title">Data</span>
              <span className={`health-section-status ${dataQuality.is_stale ? (dataQuality.is_expected_stale ? 'warning' : 'offline') : 'online'}`}>
                {dataQuality.is_stale
                  ? (dataQuality.is_expected_stale ? 'Expected Stale' : 'Stale')
                  : 'Fresh'}
                {dataQuality.latest_bar_age_minutes !== null &&
                  ` (${dataQuality.latest_bar_age_minutes.toFixed(1)}m)`}
              </span>
            </div>
            <div className="health-section-details">
              {dataQuality.latest_bar_age_minutes !== null && (
                <span className="health-detail-item">
                  Age: <span className="value-neutral">
                    {dataQuality.latest_bar_age_minutes.toFixed(1)}m / {dataQuality.stale_threshold_minutes}m
                  </span>
                </span>
              )}
              {dataQuality.buffer_size !== null && (
                <span className="health-detail-item">
                  Buffer: <span className="value-neutral">
                    {dataQuality.buffer_size}/{dataQuality.buffer_target}
                  </span>
                </span>
              )}
              {dataQuality.quiet_reason && (
                <span className="health-detail-item quiet-reason">
                  {dataQuality.quiet_reason}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Cadence/Cycle Stats Section */}
        {cadenceMetrics && (
          <div className="health-section">
            <div className="health-section-header">
              <span className={`health-dot ${dataFresh ? 'fresh' : 'stale'}`}></span>
              <span className="health-section-title">Cadence</span>
              <span className={`health-section-status ${cadenceMetrics.velocity_mode_active ? 'active' : 'online'}`}>
                {cadenceMetrics.velocity_mode_active ? 'Velocity ON' : 'Normal'}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-sm">
              <StatDisplay
                label="Last Cycle"
                value={formatMs(cadenceMetrics.cycle_duration_ms)}
                variant="compact"
                colorMode="status"
                status={getCycleHealthClass() === 'health-warning' ? 'warning' : 'ok'}
              />
              <StatDisplay
                label="p50 / p95"
                value={`${formatMs(cadenceMetrics.duration_p50_ms)} / ${formatMs(cadenceMetrics.duration_p95_ms)}`}
                variant="compact"
              />
              <StatDisplay
                label="Interval"
                value={`${cadenceMetrics.current_interval_seconds}s`}
                variant="compact"
              />
              <StatDisplay
                label="Missed"
                value={cadenceMetrics.missed_cycles}
                variant="compact"
                colorMode="status"
                status={cadenceMetrics.missed_cycles > 0 ? 'warning' : 'ok'}
              />
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
        )}

        {/* Error Summary Section */}
        {errorSummary && errorSummary.session_error_count > 0 && (
          <div className="health-section error-section">
            <div className="health-section-header">
              <span className="health-dot stale"></span>
              <span className="health-section-title">Errors</span>
              <span className="health-section-status offline">
                Session: {errorSummary.session_error_count}
              </span>
            </div>
            {errorSummary.last_error && (
              <div className="health-error-message">
                {errorSummary.last_error}
              </div>
            )}
          </div>
        )}
      </div>
    </DataPanel>
  )
}
