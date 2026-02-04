'use client'

import { useEffect, useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { InfoTooltip } from './ui'
import { apiFetch, apiFetchJson } from '@/lib/api'
import { useOperatorStore } from '@/stores'
import type { PearlInsights, PearlSuggestion, AIStatus, ShadowCounters, MLFilterPerformance } from '@/stores'

interface PearlInsightsPanelProps {
  insights: PearlInsights | null
  suggestion: PearlSuggestion | null
  aiStatus?: AIStatus | null
  shadowCounters?: ShadowCounters | null
  mlFilterPerformance?: MLFilterPerformance | null
  /** Whether the LLM chat endpoint is mounted/available on the API server */
  chatAvailable?: boolean
  /** Whether operator passphrase locking is configured on the API server (null = unknown) */
  operatorLockEnabled?: boolean | null
  initialChatOpen?: boolean
}

type Mode = 'off' | 'shadow' | 'live'

type PearlChatResponse = {
  response: string
  timestamp: string
  complexity: string
  source?: string
}

type ChatMessage = {
  role: 'user' | 'pearl'
  text: string
  meta?: {
    complexity?: string
    source?: string
  }
}

function ModePill({ label, mode }: { label: string; mode: Mode }) {
  const getModeClass = () => {
    switch (mode) {
      case 'live':
        return 'ai-pill-live'
      case 'shadow':
        return 'ai-pill-shadow'
      default:
        return 'ai-pill-off'
    }
  }

  const getModeLabel = () => {
    switch (mode) {
      case 'live':
        return 'LIVE'
      case 'shadow':
        return 'SHADOW'
      default:
        return 'OFF'
    }
  }

  return (
    <div className={`ai-pill ${getModeClass()}`}>
      <span className="ai-pill-label">{label}</span>
      <span className="ai-pill-mode">{getModeLabel()}</span>
      {mode === 'shadow' && <InfoTooltip text="Shadow mode observes but doesn't affect trades" />}
    </div>
  )
}

export default function PearlInsightsPanel({
  insights,
  suggestion,
  aiStatus,
  shadowCounters,
  mlFilterPerformance,
  chatAvailable = false,
  operatorLockEnabled = null,
  initialChatOpen = false,
}: PearlInsightsPanelProps) {
  const [showHistory, setShowHistory] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [chatOpen, setChatOpen] = useState(initialChatOpen)
  const [chatInput, setChatInput] = useState('')
  const [chatBusy, setChatBusy] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [nowMs, setNowMs] = useState(() => Date.now())

  const operatorUnlocked = useOperatorStore((s) => s.isUnlocked)
  const operatorUnlockedUntil = useOperatorStore((s) => s.unlockedUntil)
  const operatorUnlock = useOperatorStore((s) => s.unlock)
  const operatorLock = useOperatorStore((s) => s.lock)

  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const [feedbackResult, setFeedbackResult] = useState<{ type: 'ok' | 'error'; message: string } | null>(null)

  const [unlockOpen, setUnlockOpen] = useState(false)
  const [unlockValue, setUnlockValue] = useState('')
  const [unlockBusy, setUnlockBusy] = useState(false)
  const [unlockError, setUnlockError] = useState<string | null>(null)

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

  // AI Status values
  const mlMode = aiStatus?.ml_filter.enabled
    ? (aiStatus.ml_filter.mode === 'live' ? 'live' : 'shadow')
    : 'off'

  // Check if any component is in shadow mode
  const hasShadowMode = aiStatus && (
    aiStatus.bandit_mode === 'shadow' ||
    aiStatus.contextual_mode === 'shadow' ||
    mlMode === 'shadow'
  )

  // Format currency
  const formatCurrency = (val: number) => {
    if (val >= 1000) return `$${(val / 1000).toFixed(1)}k`
    return `$${val.toFixed(0)}`
  }

  // Format percentage
  const formatPct = (val: number) => `${val.toFixed(0)}%`

  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])

  const attemptUnlock = async () => {
    const phrase = unlockValue.trim()
    if (!phrase || unlockBusy) return

    setUnlockBusy(true)
    setUnlockError(null)
    setFeedbackResult(null)
    setChatError(null)

    // Optimistically unlock locally, then validate against server.
    operatorUnlock(phrase)
    try {
      const res = await apiFetch('/api/operator/ping', { method: 'GET' })
      const raw = await res.text().catch(() => '')
      if (!res.ok) {
        let detail = raw
        try {
          const body = raw ? JSON.parse(raw) : null
          detail = (typeof body?.detail === 'string' ? body.detail : raw) || raw
        } catch {
          // ignore
        }
        throw new Error(detail || `HTTP ${res.status}`)
      }
      setUnlockOpen(false)
      setUnlockValue('')
    } catch (e) {
      operatorLock()
      setUnlockError(e instanceof Error ? e.message : 'Unlock failed')
    } finally {
      setUnlockBusy(false)
    }
  }

  const formatRemaining = () => {
    if (!operatorUnlocked || !operatorUnlockedUntil) return null
    const ms = Math.max(0, operatorUnlockedUntil - nowMs)
    const mins = Math.floor(ms / 60000)
    const secs = Math.floor((ms % 60000) / 1000)
    if (mins <= 0) return `${secs}s`
    return `${mins}m ${secs}s`
  }

  const resolveSuggestionId = (): string | null => {
    const id = (activeSuggestion as any)?.id
    return typeof id === 'string' && id.trim() ? id.trim() : null
  }

  const sendSuggestionFeedback = async (action: 'accept' | 'dismiss') => {
    const suggestionId = resolveSuggestionId()
    if (!suggestionId || feedbackBusy) return
    if (!operatorUnlocked) return

    setFeedbackBusy(true)
    setFeedbackResult(null)
    try {
      const res = await apiFetch(`/api/pearl-suggestion/${action}`, {
        method: 'POST',
        body: JSON.stringify({ suggestion_id: suggestionId }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(data?.detail || `Request failed (${res.status})`)
      }
      setFeedbackResult({ type: 'ok', message: data?.message || `Suggestion ${action}ed.` })
    } catch (e) {
      setFeedbackResult({
        type: 'error',
        message: e instanceof Error ? e.message : 'Request failed',
      })
    } finally {
      setFeedbackBusy(false)
    }
  }

  const sendChat = async () => {
    const message = chatInput.trim()
    if (!message || chatBusy) return

    if (!chatAvailable) {
      setChatError('LLM chat is disabled on this server.')
      return
    }
    if (!operatorUnlocked) {
      setChatError('Operator access required.')
      return
    }

    setChatError(null)
    setChatBusy(true)
    setChatInput('')

    setChatMessages((prev) => [...prev, { role: 'user' as const, text: message }].slice(-12))

    try {
      const res = await apiFetchJson<PearlChatResponse>('/api/pearl/chat', {
        method: 'POST',
        body: JSON.stringify({ message }),
      })
      setChatMessages((prev) => [
        ...prev,
        { role: 'pearl' as const, text: res.response, meta: { complexity: res.complexity, source: res.source } },
      ].slice(-12))
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Pearl AI request failed'
      setChatError(msg)
      setChatMessages((prev) => [...prev, { role: 'pearl' as const, text: `Error: ${msg}` }].slice(-12))
    } finally {
      setChatBusy(false)
    }
  }

  return (
    <DataPanel
      title="Pearl AI"
      iconSrc="/pearl-emoji.png"
      className="pearl-insights-panel"
      badge={hasShadowMode || metrics?.mode === 'shadow' ? 'SHADOW' : undefined}
      badgeColor="var(--color-warning)"
    >
      <div className="pearl-insights">
        {/* AI Component Status Pills */}
        {aiStatus && (
          <div className="pearl-ai-status">
            <div className="ai-pills">
              <ModePill label="Bandit" mode={aiStatus.bandit_mode as Mode} />
              <ModePill label="Contextual" mode={aiStatus.contextual_mode as Mode} />
              <ModePill label="ML" mode={mlMode as Mode} />
            </div>

            {/* ML Lift Status (compact) */}
            {aiStatus.ml_filter.enabled && aiStatus.ml_filter.lift && (
              <div className="ai-lift-compact">
                <span className={`lift-indicator ${aiStatus.ml_filter.lift.lift_ok ? 'lift-ok' : 'lift-fail'}`}>
                  {aiStatus.ml_filter.lift.lift_ok ? '✓' : '—'}
                </span>
                {aiStatus.ml_filter.lift.lift_win_rate !== undefined && (
                  <span className="lift-stat">
                    WR {(aiStatus.ml_filter.lift.lift_win_rate * 100).toFixed(0)}%
                  </span>
                )}
                {aiStatus.ml_filter.lift.lift_avg_pnl !== undefined && (
                  <span className={`lift-stat ${aiStatus.ml_filter.lift.lift_avg_pnl >= 0 ? 'positive' : 'negative'}`}>
                    {aiStatus.ml_filter.lift.lift_avg_pnl >= 0 ? '+' : ''}${aiStatus.ml_filter.lift.lift_avg_pnl.toFixed(0)}
                  </span>
                )}
              </div>
            )}

            {/* Direction Gating (compact) */}
            {aiStatus.direction_gating.enabled && aiStatus.direction_gating.blocks > 0 && (
              <div className="ai-gating-compact">
                <span className="gating-label">Gating:</span>
                <span className="gating-count">{aiStatus.direction_gating.blocks} blocks</span>
              </div>
            )}
          </div>
        )}

        {/* PEARL AI Banner (Shadow Mode) */}
        {hasShadowMode && (
          <div className="shadow-mode-banner">
            <span className="shadow-mode-icon">🦪</span>
            <span className="shadow-mode-text">
              <em>PEARL AI</em> is in <em>SHADOW</em> mode — observing trades but not affecting decisions.
            </span>
          </div>
        )}

        {/* Operator lock (public link is read-only by default) */}
        <div className="pearl-operator-strip">
          <div className="pearl-operator-left">
            <span className={`pearl-operator-dot ${operatorUnlocked ? 'on' : 'off'}`} />
            <span className="pearl-operator-label">{operatorUnlocked ? 'Operator unlocked' : 'Read-only'}</span>
            {operatorUnlocked && (
              <span className="pearl-operator-ttl">
                {formatRemaining() ? `Auto-lock: ${formatRemaining()}` : ''}
              </span>
            )}
          </div>
          <div className="pearl-operator-right">
            {!operatorUnlocked ? (
              !unlockOpen ? (
                <button
                  type="button"
                  className="pearl-btn pearl-btn-neutral"
                  onClick={() => {
                    setUnlockOpen(true)
                    setUnlockError(null)
                  }}
                >
                  Unlock
                </button>
              ) : (
                <div className="pearl-operator-unlock">
                  <input
                    className="pearl-operator-input"
                    type="password"
                    value={unlockValue}
                    placeholder="Passphrase"
                    onChange={(e) => setUnlockValue(e.target.value)}
                    disabled={unlockBusy || operatorLockEnabled === false}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault()
                        void attemptUnlock()
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="pearl-btn pearl-btn-neutral pearl-operator-go"
                    onClick={() => void attemptUnlock()}
                    disabled={unlockBusy || !unlockValue.trim() || operatorLockEnabled === false}
                  >
                    {unlockBusy ? '…' : 'Go'}
                  </button>
                  <button
                    type="button"
                    className="pearl-btn pearl-btn-neutral pearl-operator-cancel"
                    onClick={() => {
                      setUnlockOpen(false)
                      setUnlockValue('')
                      setUnlockError(null)
                    }}
                    disabled={unlockBusy}
                  >
                    ×
                  </button>
                </div>
              )
            ) : (
              <button type="button" className="pearl-btn pearl-btn-neutral" onClick={operatorLock}>
                Lock
              </button>
            )}
          </div>
        </div>

        {operatorLockEnabled === false && (
          <div className="pearl-feedback-result error">
            Operator lock is not configured on the API server. Set <code>PEARL_OPERATOR_PASSPHRASE</code>.
          </div>
        )}

        {unlockError && (
          <div className="pearl-feedback-result error">
            Unlock failed: {unlockError}
          </div>
        )}

        {feedbackResult && (
          <div className={`pearl-feedback-result ${feedbackResult.type}`}>
            {feedbackResult.message}
          </div>
        )}

        {/* LLM Chat (Pearl AI 3.0) */}
        <div className="pearl-chat">
          <button
            className="pearl-chat-toggle"
            onClick={() => setChatOpen(!chatOpen)}
            type="button"
          >
            {chatOpen ? '−' : '+'} Ask Pearl (LLM)
          </button>
          {chatOpen && (
            <div className="pearl-chat-body">
              <div className="pearl-chat-messages">
                {chatMessages.length === 0 ? (
                  <div className="pearl-chat-empty">
                    Ask about today’s setup, why signals are quiet, or what to watch next.
                  </div>
                ) : (
                  chatMessages.map((m, idx) => (
                    <div key={idx} className={`pearl-chat-msg ${m.role}`}>
                      <div className="pearl-chat-role">{m.role === 'user' ? 'You' : 'Pearl'}</div>
                      <div className="pearl-chat-text">{m.text}</div>
                      {m.role === 'pearl' && (m.meta?.complexity || m.meta?.source) && (
                        <div className="pearl-chat-meta">
                          {m.meta?.complexity && <span className="meta-pill">{m.meta.complexity}</span>}
                          {m.meta?.source && <span className="meta-pill">{m.meta.source}</span>}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>

              <form
                className="pearl-chat-form"
                onSubmit={(e) => {
                  e.preventDefault()
                  void sendChat()
                }}
              >
                <input
                  className="pearl-chat-input"
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  placeholder="Ask Pearl…"
                  disabled={chatBusy || !operatorUnlocked || !chatAvailable}
                />
                <button
                  className="pearl-chat-send"
                  type="submit"
                  disabled={chatBusy || !chatInput.trim() || !operatorUnlocked || !chatAvailable}
                >
                  {chatBusy ? '…' : 'Send'}
                </button>
                <button
                  className="pearl-chat-clear"
                  type="button"
                  onClick={() => setChatMessages([])}
                  disabled={chatBusy || chatMessages.length === 0}
                >
                  Clear
                </button>
              </form>

              {chatError && <div className="pearl-chat-error">{chatError}</div>}
              <div className="pearl-chat-hint">
                {!operatorUnlocked
                  ? 'Read-only mode. Unlock operator access to chat.'
                  : !chatAvailable
                    ? 'LLM chat is disabled on this server.'
                    : 'Operator-only. Requires Pearl AI endpoints on the API server.'}
              </div>
            </div>
          )}
        </div>

        {/* ML Filter Performance - Win Rate Comparison */}
        {mlFilterPerformance && (mlFilterPerformance.win_rate_pass !== undefined || mlFilterPerformance.win_rate_fail !== undefined) && (
          <div className="ml-performance-section">
            <div className="ml-perf-header">
              <span className="ml-perf-title">ML Filter Impact</span>
              {mlFilterPerformance.lift_ok && (
                <span className="ml-lift-badge positive">
                  +{((mlFilterPerformance.win_rate_pass || 0) - (mlFilterPerformance.win_rate_fail || 0)) * 100 > 0
                    ? (((mlFilterPerformance.win_rate_pass || 0) - (mlFilterPerformance.win_rate_fail || 0)) * 100).toFixed(0)
                    : '0'}% lift
                </span>
              )}
            </div>
            <div className="ml-comparison-bars">
              <div className="ml-bar-row">
                <span className="ml-bar-label">PASS</span>
                <div className="ml-bar-track">
                  <div
                    className="ml-bar-fill pass"
                    style={{ width: `${(mlFilterPerformance.win_rate_pass || 0) * 100}%` }}
                  />
                </div>
                <span className="ml-bar-value">
                  {mlFilterPerformance.win_rate_pass !== undefined
                    ? `${(mlFilterPerformance.win_rate_pass * 100).toFixed(0)}%`
                    : '—'}
                </span>
                <span className="ml-bar-count">{mlFilterPerformance.trades_passed}</span>
              </div>
              <div className="ml-bar-row">
                <span className="ml-bar-label">FAIL</span>
                <div className="ml-bar-track">
                  <div
                    className="ml-bar-fill fail"
                    style={{ width: `${(mlFilterPerformance.win_rate_fail || 0) * 100}%` }}
                  />
                </div>
                <span className="ml-bar-value">
                  {mlFilterPerformance.win_rate_fail !== undefined
                    ? `${(mlFilterPerformance.win_rate_fail * 100).toFixed(0)}%`
                    : '—'}
                </span>
                <span className="ml-bar-count">{mlFilterPerformance.trades_blocked}</span>
              </div>
            </div>
            {mlFilterPerformance.lift_ok ? (
              <div className="ml-value-status positive">
                <span className="status-icon">✓</span>
                <span className="status-text">ML filter adding value</span>
              </div>
            ) : (
              <div className="ml-value-status neutral">
                <span className="status-icon">—</span>
                <span className="status-text">Collecting data...</span>
              </div>
            )}
          </div>
        )}

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
              {/*
                Some suggestion sources may not provide a stable id; the server will
                best-effort resolve the active suggestion id, but we still disable
                buttons if we have nothing to reference client-side.
              */}
              {(() => {
                const sid = resolveSuggestionId()
                const disabled = !operatorUnlocked || feedbackBusy || !sid
                const title = !operatorUnlocked ? 'Read-only (operator locked)' : !sid ? 'No suggestion id available' : undefined
                return (
                  <>
                    <button
                      className="pearl-btn pearl-btn-accept"
                      onClick={() => void sendSuggestionFeedback('accept')}
                      disabled={disabled}
                      title={title}
                    >
                      Accept
                    </button>
                    <button
                      className="pearl-btn pearl-btn-dismiss"
                      onClick={() => void sendSuggestionFeedback('dismiss')}
                      disabled={disabled}
                      title={title}
                    >
                      Dismiss
                    </button>
                  </>
                )
              })()}
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

        {/* Shadow Tracking Impact Summary (compact 2x2 grid) */}
        {metrics && totalSuggestions > 0 && (
          <div className="pearl-shadow-metrics">
            <div className="shadow-header">
              <span className="shadow-title">Shadow Impact</span>
              <button
                className="details-toggle"
                onClick={() => setShowDetails(!showDetails)}
              >
                {showDetails ? '−' : '+'}
              </button>
            </div>

            {/* Compact Impact Row */}
            <div className="shadow-impact-row">
              <div className="impact-item positive">
                <span className="impact-value">{formatCurrency(totalWouldHaveSaved)}</span>
                <span className="impact-label">saved</span>
              </div>
              <div className="impact-item positive">
                <span className="impact-value">{formatCurrency(totalWouldHaveMade)}</span>
                <span className="impact-label">made</span>
              </div>
              <div className={`impact-item ${netImpact >= 0 ? 'positive' : 'negative'}`}>
                <span className="impact-value">{netImpact >= 0 ? '+' : ''}{formatCurrency(netImpact)}</span>
                <span className="impact-label">net</span>
              </div>
              <div className={`impact-item ${accuracyRate >= 60 ? 'positive' : 'neutral'}`}>
                <span className="impact-value">{formatPct(accuracyRate)}</span>
                <span className="impact-label">accuracy</span>
              </div>
            </div>

            {/* Expanded Details */}
            {showDetails && (
              <div className="shadow-details">
                {/* Shadow Counters from AI Status */}
                {shadowCounters && shadowCounters.would_block_total > 0 && (
                  <div className="shadow-blocks">
                    <span className="blocks-text">
                      Would block <strong>{shadowCounters.would_block_total}</strong> signals
                    </span>
                    {shadowCounters.ml_would_skip > 0 && (
                      <span className="blocks-sub">
                        ML skip {shadowCounters.ml_would_skip}/{shadowCounters.ml_total_decisions}
                      </span>
                    )}
                  </div>
                )}

                {/* Suggestion Stats */}
                <div className="shadow-stats-compact">
                  <span className="stat">✓ {suggestionsFollowed} followed</span>
                  <span className="stat">✗ {suggestionsDismissed} dismissed</span>
                  <span className="stat">⏱ {metrics.suggestions_expired} expired</span>
                </div>

                {/* History Toggle */}
                {metrics.recent_suggestions && metrics.recent_suggestions.length > 0 && (
                  <button
                    className="history-toggle-btn"
                    onClick={() => setShowHistory(!showHistory)}
                  >
                    {showHistory ? 'Hide History ▲' : 'Show History ▼'}
                  </button>
                )}

                {/* Recent Suggestions History */}
                {showHistory && metrics.recent_suggestions && (
                  <div className="shadow-history">
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
                                  +${s.would_have_saved.toFixed(0)}
                                </span>
                              )}
                              {s.would_have_made && s.would_have_made > 0 && (
                                <span className="would-have made">
                                  +${s.would_have_made.toFixed(0)}
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
          </div>
        )}

        {/* Empty State - No Metrics Yet */}
        {(!metrics || totalSuggestions === 0) && !activeSuggestion && !aiStatus && (
          <div className="pearl-empty-state">
            <div className="empty-icon">🔮</div>
            <div className="empty-title">Shadow Mode Active</div>
            <div className="empty-text">
              Pearl is learning your patterns.
            </div>
          </div>
        )}
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
