'use client'

import { DataPanel } from './DataPanelsContainer'
import type { SignalRejections, LastSignalDecision } from '@/stores'

interface SignalDecisionsPanelProps {
  rejections: SignalRejections | null
  lastDecision: LastSignalDecision | null
}

// Bar chart item for rejection visualization
interface RejectionBarItem {
  label: string
  count: number
  percentage: number
  isTopBlocker: boolean
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

  // Build rejection bar items sorted by count
  const buildRejectionBars = (): RejectionBarItem[] => {
    if (!rejections || totalRejections === 0) return []

    const items: RejectionBarItem[] = [
      { label: 'Circuit Breaker', count: rejections.circuit_breaker, percentage: 0, isTopBlocker: false },
      { label: 'Direction Gating', count: rejections.direction_gating, percentage: 0, isTopBlocker: false },
      { label: 'ML Filter', count: rejections.ml_filter, percentage: 0, isTopBlocker: false },
      { label: 'Max Positions', count: rejections.max_positions, percentage: 0, isTopBlocker: false },
      { label: 'Session Filter', count: rejections.session_filter, percentage: 0, isTopBlocker: false },
    ]
      .filter(item => item.count > 0)
      .map(item => ({
        ...item,
        percentage: Math.round((item.count / totalRejections) * 100)
      }))
      .sort((a, b) => b.count - a.count)

    // Mark the top blocker
    if (items.length > 0) {
      items[0].isTopBlocker = true
    }

    return items
  }

  const rejectionBars = buildRejectionBars()

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

        {/* Rejections Breakdown with Bar Chart */}
        {rejections && totalRejections > 0 && (
          <div className="rejections-section">
            <div className="rejections-header">
              <span className="rejections-label">Rejections (24h)</span>
              <span className="rejections-total">{totalRejections}</span>
            </div>
            <div className="rejection-bar-chart">
              {rejectionBars.map((item) => (
                <div key={item.label} className="rejection-bar-item">
                  <span className="rejection-bar-label">{item.label}</span>
                  <div className="rejection-bar-track">
                    <div
                      className={`rejection-bar-fill ${item.isTopBlocker ? 'top-blocker' : ''}`}
                      style={{ width: `${item.percentage}%` }}
                    />
                  </div>
                  <span className={`rejection-bar-value ${item.isTopBlocker ? 'top-blocker' : ''}`}>
                    {item.count} ({item.percentage}%)
                  </span>
                </div>
              ))}
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
