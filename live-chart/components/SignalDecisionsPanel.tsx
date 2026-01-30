'use client'

import { DataPanel } from './DataPanelsContainer'

interface SignalRejections {
  direction_gating: number
  ml_filter: number
  circuit_breaker: number
  session_filter: number
  max_positions: number
}

interface LastSignalDecision {
  signal_type: string
  ml_probability: number
  action: 'execute' | 'skip'
  reason: string
  timestamp: string | null
}

interface SignalDecisionsPanelProps {
  rejections: SignalRejections | null
  lastDecision: LastSignalDecision | null
}

export default function SignalDecisionsPanel({ rejections, lastDecision }: SignalDecisionsPanelProps) {
  const formatSignalType = (type: string) => {
    if (!type) return 'Unknown'
    return type
      .replace(/_/g, ' ')
      .replace(/pearlbot /i, '')
      .split(' ')
      .map(word => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  }

  const formatTime = (timestamp: string | null) => {
    if (!timestamp) return '--:--'
    try {
      const date = new Date(timestamp)
      return date.toLocaleTimeString('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      })
    } catch {
      return '--:--'
    }
  }

  const totalRejections = rejections
    ? rejections.direction_gating +
      rejections.ml_filter +
      rejections.circuit_breaker +
      rejections.session_filter +
      rejections.max_positions
    : 0

  return (
    <DataPanel title="Signal Decisions" icon="🎯">
      <div className="signal-decisions-content">
        {/* Last Signal Info */}
        {lastDecision && (
          <div className="last-signal-section">
            <div className="last-signal-header">
              <span className="last-signal-label">Last Signal</span>
              <span className="last-signal-time">{formatTime(lastDecision.timestamp)}</span>
            </div>
            <div className="last-signal-details">
              <span className="signal-type">{formatSignalType(lastDecision.signal_type)}</span>
              <span className="signal-probability">
                ML: {(lastDecision.ml_probability * 100).toFixed(0)}%
              </span>
              <span className={`signal-action ${lastDecision.action}`}>
                {lastDecision.action === 'execute' ? '✓ Execute' : '✗ Skip'}
              </span>
            </div>
          </div>
        )}

        {/* Rejections Breakdown */}
        {rejections && totalRejections > 0 && (
          <div className="rejections-section">
            <div className="rejections-header">
              <span className="rejections-label">Rejections (24h)</span>
              <span className="rejections-total">{totalRejections}</span>
            </div>
            <div className="rejections-breakdown">
              {rejections.direction_gating > 0 && (
                <div className="rejection-item">
                  <span className="rejection-reason">Direction Gating</span>
                  <span className="rejection-count">{rejections.direction_gating}</span>
                </div>
              )}
              {rejections.circuit_breaker > 0 && (
                <div className="rejection-item">
                  <span className="rejection-reason">Circuit Breaker</span>
                  <span className="rejection-count">{rejections.circuit_breaker}</span>
                </div>
              )}
              {rejections.max_positions > 0 && (
                <div className="rejection-item">
                  <span className="rejection-reason">Max Positions</span>
                  <span className="rejection-count">{rejections.max_positions}</span>
                </div>
              )}
              {rejections.ml_filter > 0 && (
                <div className="rejection-item">
                  <span className="rejection-reason">ML Filter</span>
                  <span className="rejection-count">{rejections.ml_filter}</span>
                </div>
              )}
              {rejections.session_filter > 0 && (
                <div className="rejection-item">
                  <span className="rejection-reason">Session Filter</span>
                  <span className="rejection-count">{rejections.session_filter}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {!lastDecision && (!rejections || totalRejections === 0) && (
          <div className="no-data-message">No signal data available</div>
        )}
      </div>
    </DataPanel>
  )
}
