'use client'

import { useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import type { PearlInsights, PearlSuggestion } from '@/stores'

interface PearlInsightsPanelProps {
  insights: PearlInsights | null
  suggestion: PearlSuggestion | null
  onAccept?: () => void
  onDismiss?: () => void
}

export default function PearlInsightsPanel({
  insights,
  suggestion,
  onAccept,
  onDismiss,
}: PearlInsightsPanelProps) {
  const [showHistory, setShowHistory] = useState(false)

  const metrics = insights?.shadow_metrics
  const activeSuggestion = suggestion || metrics?.active_suggestion

  // Calculate display values
  const totalWouldHaveSaved = metrics?.total_would_have_saved || 0
  const totalWouldHaveMade = metrics?.total_would_have_made || 0
  const netImpact = metrics?.net_shadow_impact || 0
  const accuracyRate = metrics?.accuracy_rate || 0
  const totalSuggestions = metrics?.total_suggestions || 0
  const suggestionsFollowed = metrics?.suggestions_followed || 0
  const suggestionsDismissed = metrics?.suggestions_dismissed || 0

  // Format currency
  const formatCurrency = (val: number) => {
    if (val >= 1000) return `$${(val / 1000).toFixed(1)}k`
    return `$${val.toFixed(0)}`
  }

  // Format percentage
  const formatPct = (val: number) => `${val.toFixed(0)}%`

  return (
    <DataPanel
      title="Pearl AI"
      icon="🦪"
      className="pearl-insights-panel"
      badge={metrics?.mode === 'shadow' ? 'SHADOW' : undefined}
      badgeColor="var(--color-warning)"
    >
      <div className="pearl-insights">
        {/* Current Insight / Suggestion */}
        {activeSuggestion && (
          <div className="pearl-current-insight">
            <div className="insight-header">
              <span className="insight-icon">💡</span>
              <span className="insight-label">Current Insight</span>
            </div>
            <div className="insight-message">{activeSuggestion.message}</div>
            {activeSuggestion.action && (
              <div className="insight-action">
                <span className="action-label">Suggestion:</span>
                <span className="action-value">{activeSuggestion.action}</span>
              </div>
            )}
            <div className="insight-buttons">
              <button
                className="pearl-btn pearl-btn-accept"
                onClick={onAccept}
              >
                Accept
              </button>
              <button
                className="pearl-btn pearl-btn-dismiss"
                onClick={onDismiss}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* No Active Suggestion State */}
        {!activeSuggestion && (
          <div className="pearl-no-insight">
            <span className="no-insight-icon">✨</span>
            <span className="no-insight-text">Watching for opportunities...</span>
          </div>
        )}

        {/* Shadow Tracking Metrics */}
        {metrics && totalSuggestions > 0 && (
          <div className="pearl-shadow-metrics">
            <div className="shadow-header">
              <span className="shadow-title">Shadow Tracking</span>
              <span className="shadow-badge">
                {totalSuggestions} insights
              </span>
            </div>

            {/* Impact Summary */}
            <div className="shadow-impact-grid">
              {/* Would Have Saved */}
              <div className="impact-card impact-saved">
                <div className="impact-label">Would Have Saved</div>
                <div className="impact-value positive">
                  {formatCurrency(totalWouldHaveSaved)}
                </div>
                <div className="impact-subtext">
                  avoided losses
                </div>
              </div>

              {/* Would Have Made */}
              <div className="impact-card impact-made">
                <div className="impact-label">Would Have Made</div>
                <div className="impact-value positive">
                  {formatCurrency(totalWouldHaveMade)}
                </div>
                <div className="impact-subtext">
                  extra gains
                </div>
              </div>

              {/* Net Impact */}
              <div className="impact-card impact-net">
                <div className="impact-label">Net Impact</div>
                <div className={`impact-value ${netImpact >= 0 ? 'positive' : 'negative'}`}>
                  {netImpact >= 0 ? '+' : ''}{formatCurrency(netImpact)}
                </div>
                <div className="impact-subtext">
                  if followed
                </div>
              </div>

              {/* Accuracy */}
              <div className="impact-card impact-accuracy">
                <div className="impact-label">Accuracy</div>
                <div className={`impact-value ${accuracyRate >= 60 ? 'positive' : accuracyRate >= 40 ? 'neutral' : 'negative'}`}>
                  {formatPct(accuracyRate)}
                </div>
                <div className="impact-subtext">
                  {metrics.correct_suggestions}/{metrics.correct_suggestions + metrics.incorrect_suggestions} correct
                </div>
              </div>
            </div>

            {/* Suggestion Stats */}
            <div className="shadow-stats">
              <div className="stat-row">
                <span className="stat-label">Followed:</span>
                <span className="stat-value">{suggestionsFollowed}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Dismissed:</span>
                <span className="stat-value">{suggestionsDismissed}</span>
              </div>
              <div className="stat-row">
                <span className="stat-label">Expired:</span>
                <span className="stat-value">{metrics.suggestions_expired}</span>
              </div>
            </div>

            {/* History Toggle */}
            {metrics.recent_suggestions && metrics.recent_suggestions.length > 0 && (
              <div className="shadow-history-toggle">
                <button
                  className="history-toggle-btn"
                  onClick={() => setShowHistory(!showHistory)}
                >
                  {showHistory ? 'Hide History' : 'Show History'}
                  <span className="toggle-icon">{showHistory ? '▲' : '▼'}</span>
                </button>
              </div>
            )}

            {/* Recent Suggestions History */}
            {showHistory && metrics.recent_suggestions && (
              <div className="shadow-history">
                <div className="history-header">Recent Insights</div>
                <div className="history-list">
                  {metrics.recent_suggestions.slice(-5).reverse().map((s) => (
                    <div key={s.id} className={`history-item outcome-${s.outcome}`}>
                      <div className="history-type">{getTypeIcon(s.type)}</div>
                      <div className="history-content">
                        <div className="history-message">{s.message}</div>
                        <div className="history-meta">
                          <span className={`outcome-badge ${s.outcome}`}>
                            {s.outcome}
                          </span>
                          {s.would_have_saved && s.would_have_saved > 0 && (
                            <span className="would-have saved">
                              +${s.would_have_saved.toFixed(0)} saved
                            </span>
                          )}
                          {s.would_have_made && s.would_have_made > 0 && (
                            <span className="would-have made">
                              +${s.would_have_made.toFixed(0)} made
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Empty State - No Metrics Yet */}
        {(!metrics || totalSuggestions === 0) && !activeSuggestion && (
          <div className="pearl-empty-state">
            <div className="empty-icon">🔮</div>
            <div className="empty-title">Shadow Mode Active</div>
            <div className="empty-text">
              Pearl is learning your patterns. Insights will appear as trading continues.
            </div>
          </div>
        )}

        {/* Shadow Mode Indicator */}
        <div className="pearl-mode-indicator">
          <span className="mode-dot shadow"></span>
          <span className="mode-text">Shadow Mode - Tracking only, not affecting trades</span>
        </div>
      </div>
    </DataPanel>
  )
}

// Helper function to get icon for suggestion type
function getTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    risk_alert: '⚠️',
    pattern_insight: '📊',
    direction_bias: '↗️',
    size_reduction: '📉',
    pause_trading: '⏸️',
    opportunity: '🎯',
    session_advice: '🕐',
  }
  return icons[type] || '💡'
}
