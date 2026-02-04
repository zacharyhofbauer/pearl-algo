'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { InfoTooltip } from './ui'
import { apiFetch } from '@/lib/api'
import { useOperatorStore } from '@/stores'
import { usePearlPanel } from '@/hooks/usePearlPanel'
import type {
  PearlInsights,
  PearlSuggestion,
  AgentState,
  AIStatus,
  ShadowCounters,
  MLFilterPerformance,
  PearlFeedMessage,
  PearlAIHeartbeat,
  PearlAIDebugInfo,
} from '@/stores'
import type { PearlMode, TradingContext, ChatMessage } from '@/types/pearl'

interface PearlInsightsPanelProps {
  insights: PearlInsights | null
  suggestion: PearlSuggestion | null
  agentState?: AgentState | null
  aiStatus?: AIStatus | null
  shadowCounters?: ShadowCounters | null
  mlFilterPerformance?: MLFilterPerformance | null
  chatAvailable?: boolean
  operatorLockEnabled?: boolean | null
  pearlFeed?: PearlFeedMessage[]
  pearlAIHeartbeat?: PearlAIHeartbeat | null
  pearlAIDebug?: PearlAIDebugInfo | null
  layout?: 'panel' | 'dropdown'
  dropdownActive?: boolean
  initialChatOpen?: boolean
}

type DropdownTab = 'overview' | 'feed' | 'chat' | 'costs'

// ============================================================================
// Helpers
// ============================================================================

/** Simple markdown-to-HTML converter for Pearl AI messages */
function renderSimpleMarkdown(text: string): string {
  return text
    // Bold: **text** or __text__
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/__(.+?)__/g, '<strong>$1</strong>')
    // Italic: *text* or _text_
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .replace(/_([^_]+)_/g, '<em>$1</em>')
    // Bullet points at start of line
    .replace(/^[•\-\*]\s+/gm, '<span class="md-bullet">•</span> ')
    // Line breaks
    .replace(/\n/g, '<br />')
}

// ============================================================================
// Sub-components
// ============================================================================

function ModePill({ label, mode }: { label: string; mode: PearlMode }) {
  const modeClass = mode === 'live' ? 'ai-pill-live' : mode === 'shadow' ? 'ai-pill-shadow' : 'ai-pill-off'
  const modeLabel = mode.toUpperCase()

  return (
    <div
      className={`ai-pill ${modeClass}`}
      role="status"
      aria-label={`${label} mode: ${modeLabel}`}
    >
      <span className="ai-pill-label">{label}</span>
      <span className="ai-pill-mode">{modeLabel}</span>
      {mode === 'shadow' && <InfoTooltip text="Shadow mode observes but doesn't affect trades" />}
    </div>
  )
}

/** Compact context bar showing key trading metrics */
function ContextBar({ context, formatAgo }: { context: TradingContext; formatAgo: (ts: string | null) => string }) {
  const hasPnl = context.pnl !== null
  const hasWL = context.wins !== null || context.losses !== null
  const hasRegime = context.regime !== null

  if (!hasPnl && !hasWL && !hasRegime) return null

  return (
    <div className="pearl-context-bar" role="group" aria-label="Trading context">
      {hasPnl && (
        <div className={`context-item pnl ${(context.pnl ?? 0) >= 0 ? 'positive' : 'negative'}`}>
          <span className="context-value">
            {(context.pnl ?? 0) >= 0 ? '+' : ''}${(context.pnl ?? 0).toFixed(0)}
          </span>
        </div>
      )}
      {hasWL && (
        <div className="context-item wl">
          <span className="context-value">
            <span className="win">{context.wins ?? 0}W</span>
            <span className="sep">/</span>
            <span className="loss">{context.losses ?? 0}L</span>
          </span>
        </div>
      )}
      {hasRegime && (
        <div className="context-item regime">
          <span className="context-value">
            {context.regime?.replace(/_/g, ' ')}
            {context.allowedDirection ? ` • ${context.allowedDirection.replace(/_/g, ' ')}` : ''}
          </span>
        </div>
      )}
      {context.positions !== null && context.positions > 0 && (
        <div className="context-item pos">
          <span className="context-value">{context.positions} pos</span>
        </div>
      )}
    </div>
  )
}

/** Suggestion card with action buttons */
function SuggestionCard({
  suggestion,
  onAccept,
  onDismiss,
  onAsk,
  disabled,
  busy,
}: {
  suggestion: PearlSuggestion | null
  onAccept: () => void
  onDismiss: () => void
  onAsk: () => void
  disabled: boolean
  busy: boolean
}) {
  if (!suggestion) return null

  return (
    <div className="pearl-suggestion-card">
      <div className="suggestion-content">
        <span className="suggestion-icon">💡</span>
        <span className="suggestion-text">{suggestion.message}</span>
      </div>
      {suggestion.action && (
        <div className="suggestion-action">
          <span className="action-label">Suggestion:</span>
          <span className="action-value">{suggestion.action}</span>
        </div>
      )}
      <div className="suggestion-buttons">
        <button
          className="pearl-btn pearl-btn-accept"
          onClick={onAccept}
          disabled={disabled || busy}
          type="button"
        >
          Accept
        </button>
        <button
          className="pearl-btn pearl-btn-dismiss"
          onClick={onDismiss}
          disabled={disabled || busy}
          type="button"
        >
          Dismiss
        </button>
        <button
          className="pearl-btn pearl-btn-neutral"
          onClick={onAsk}
          type="button"
        >
          Ask
        </button>
      </div>
    </div>
  )
}

/** Quick actions row - now with collapsible "More" section */
function QuickActionsRow({
  onAction,
  busy,
  disabled,
  expanded,
  onToggleExpand,
}: {
  onAction: (id: string) => void
  busy: string | null
  disabled: boolean
  expanded: boolean
  onToggleExpand: () => void
}) {
  return (
    <div className="pearl-quick-actions" role="group" aria-label="Quick actions">
      <div className="quick-actions-primary">
        <button
          type="button"
          className={`pearl-btn pearl-btn-neutral ${busy === 'plan' ? 'busy' : ''}`}
          onClick={() => onAction('plan')}
          disabled={disabled || Boolean(busy)}
          aria-busy={busy === 'plan'}
        >
          {busy === 'plan' ? '…' : 'Session plan'}
        </button>
        <button
          type="button"
          className={`pearl-btn pearl-btn-neutral ${busy === 'quiet' ? 'busy' : ''}`}
          onClick={() => onAction('quiet')}
          disabled={disabled || Boolean(busy)}
          aria-busy={busy === 'quiet'}
        >
          {busy === 'quiet' ? '…' : 'Quiet check'}
        </button>
        <button
          type="button"
          className="pearl-btn pearl-btn-neutral pearl-btn-more"
          onClick={onToggleExpand}
          aria-expanded={expanded}
        >
          {expanded ? 'Less ▴' : 'More ▾'}
        </button>
      </div>
      {expanded && (
        <div className="quick-actions-secondary">
          <button
            type="button"
            className={`pearl-btn pearl-btn-neutral ${busy === 'rejections' ? 'busy' : ''}`}
            onClick={() => onAction('rejections')}
            disabled={disabled || Boolean(busy)}
            aria-busy={busy === 'rejections'}
          >
            {busy === 'rejections' ? '…' : 'Rejections'}
          </button>
          <button
            type="button"
            className={`pearl-btn pearl-btn-neutral ${busy === 'insight' ? 'busy' : ''}`}
            onClick={() => onAction('insight')}
            disabled={disabled || Boolean(busy)}
            aria-busy={busy === 'insight'}
          >
            {busy === 'insight' ? '…' : 'Insight'}
          </button>
          <button
            type="button"
            className={`pearl-btn pearl-btn-neutral ${busy === 'daily_review' ? 'busy' : ''}`}
            onClick={() => onAction('daily_review')}
            disabled={disabled || Boolean(busy)}
            aria-busy={busy === 'daily_review'}
          >
            {busy === 'daily_review' ? '…' : 'Daily review'}
          </button>
        </div>
      )}
    </div>
  )
}

// ============================================================================
// Main Component
// ============================================================================

export default function PearlInsightsPanel({
  insights,
  suggestion,
  agentState = null,
  aiStatus,
  shadowCounters,
  mlFilterPerformance,
  chatAvailable = false,
  operatorLockEnabled = null,
  pearlFeed = [],
  pearlAIHeartbeat = null,
  pearlAIDebug = null,
  layout = 'panel',
  dropdownActive = false,
  initialChatOpen = false,
}: PearlInsightsPanelProps) {
  const isDropdown = layout === 'dropdown'
  
  // Use the unified hook for panel data and operations
  const {
    data,
    nowMs,
    formatAgo,
    activeTab,
    setActiveTab,
    chat,
    metricsData,
    refreshMetrics,
    quickActions,
    feedQuery,
    setFeedQuery,
    feedType,
    setFeedType,
    filteredFeed,
  } = usePearlPanel({
    agentState,
    dropdownActive,
    initialTab: initialChatOpen ? 'chat' : 'overview',
  })

  // Local UI state
  const [showHistory, setShowHistory] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [showTransparency, setShowTransparency] = useState(false)
  const [chatOpen, setChatOpen] = useState(initialChatOpen)
  const [quickActionsExpanded, setQuickActionsExpanded] = useState(false)

  // Operator state
  const operatorUnlocked = useOperatorStore((s) => s.isUnlocked)
  const operatorUnlockedUntil = useOperatorStore((s) => s.unlockedUntil)
  const operatorUnlock = useOperatorStore((s) => s.unlock)
  const operatorLock = useOperatorStore((s) => s.lock)

  // Unlock UI state
  const [unlockOpen, setUnlockOpen] = useState(false)
  const [unlockValue, setUnlockValue] = useState('')
  const [unlockBusy, setUnlockBusy] = useState(false)
  const [unlockError, setUnlockError] = useState<string | null>(null)

  // Feedback state
  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const [feedbackResult, setFeedbackResult] = useState<{ type: 'ok' | 'error'; message: string } | null>(null)

  // Refs for auto-scroll
  const chatMessagesRef = useRef<HTMLDivElement>(null)
  const feedListRef = useRef<HTMLDivElement>(null)

  // Derived values from data
  const metrics = insights?.shadow_metrics
  const activeSuggestion = data.suggestion
  const mlMode = aiStatus?.ml_filter.enabled
    ? (aiStatus.ml_filter.mode === 'live' ? 'live' : 'shadow')
    : 'off'
  const hasShadowMode = data.status.mode === 'shadow'

  // Format currency
  const formatCurrency = (val: number) => {
    if (val >= 1000) return `$${(val / 1000).toFixed(1)}k`
    return `$${val.toFixed(0)}`
  }

  const formatPct = (val: number) => `${val.toFixed(0)}%`

  // Auto-scroll chat messages
  useEffect(() => {
    if (chatMessagesRef.current && chat.messages.length > 0) {
      chatMessagesRef.current.scrollTo({
        top: chatMessagesRef.current.scrollHeight,
        behavior: 'smooth',
      })
    }
  }, [chat.messages.length])

  // Operator unlock handler
  const attemptUnlock = async () => {
    const phrase = unlockValue.trim()
    if (!phrase || unlockBusy) return

    setUnlockBusy(true)
    setUnlockError(null)
    setFeedbackResult(null)

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

  // Suggestion feedback
  const resolveSuggestionId = useCallback((): string | null => {
    const id = activeSuggestion && 'id' in activeSuggestion
      ? (activeSuggestion as { id?: string }).id
      : undefined
    return typeof id === 'string' && id.trim() ? id.trim() : null
  }, [activeSuggestion])

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
      const resData = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(resData?.detail || `Request failed (${res.status})`)
      }
      setFeedbackResult({ type: 'ok', message: resData?.message || `Suggestion ${action}ed.` })
    } catch (e) {
      setFeedbackResult({
        type: 'error',
        message: e instanceof Error ? e.message : 'Request failed',
      })
    } finally {
      setFeedbackBusy(false)
    }
  }

  const transparencyExpanded = isDropdown ? true : showTransparency
  const chatExpanded = isDropdown ? true : chatOpen

  // Routing label for debug info
  const routingLabel = (() => {
    const routing = pearlAIDebug?.routing
    if (!routing) return '—'
    if (typeof routing === 'string') return routing
    if (typeof routing === 'object' && routing !== null) {
      const r = routing as Record<string, unknown>
      const v = r.route || r.decision || r.complexity || r.kind
      if (typeof v === 'string') return v
      return 'routing'
    }
    return String(routing)
  })()

  const toolCount = Array.isArray(pearlAIDebug?.tool_calls) ? pearlAIDebug!.tool_calls!.length : 0

  // Shadow metrics values
  const totalWouldHaveSaved = metrics?.total_would_have_saved || 0
  const totalWouldHaveMade = metrics?.total_would_have_made || 0
  const netImpact = metrics?.net_shadow_impact || 0
  const accuracyRate = metrics?.accuracy_rate || 0
  const totalSuggestions = metrics?.total_suggestions || 0
  const suggestionsFollowed = metrics?.suggestions_followed || 0
  const suggestionsDismissed = metrics?.suggestions_dismissed || 0

  return (
    <DataPanel
      title="Pearl AI"
      iconSrc="/pearl-emoji.png"
      className={`pearl-insights-panel${isDropdown ? ' pearl-insights-dropdown' : ''}`}
      padding={isDropdown ? 'compact' : 'default'}
      badge={!isDropdown && hasShadowMode ? 'SHADOW' : undefined}
      badgeColor="var(--color-warning)"
    >
      <div className={`pearl-insights${isDropdown ? ' pearl-insights-dropdown-body' : ''}`}>
        {/* ============================================================ */}
        {/* DROPDOWN MODE - Simplified Layout */}
        {/* ============================================================ */}
        {isDropdown && (
          <div className="pearl-dropdown-top">
            {/* Tab Bar */}
            <div className="pearl-dropdown-tabs" role="tablist" aria-label="Pearl AI">
              {(['overview', 'feed', 'chat', 'costs'] as const).map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={activeTab === tab}
                  className={`pearl-dropdown-tab ${activeTab === tab ? 'active' : ''}`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab.charAt(0).toUpperCase() + tab.slice(1)}
                </button>
              ))}
            </div>

            {/* Unified Headline - Only shown once */}
            <div className="pearl-dropdown-headline">
              <div className="pearl-dropdown-headline-row">
                <span className={`pearl-heartbeat-dot ${data.status.heartbeatRecent ? 'on' : 'off'}`} />
                <span className={`pearl-dropdown-mode ${data.status.mode}`}>{data.status.mode.toUpperCase()}</span>
                <span
                  className="pearl-dropdown-headline-text"
                  dangerouslySetInnerHTML={{ __html: renderSimpleMarkdown(data.headline.text) }}
                />
              </div>
              <span className="pearl-dropdown-ago">{formatAgo(data.status.lastActivityTs)}</span>
            </div>

            {/* Overview Tab Content */}
            {activeTab === 'overview' && (
              <div className="pearl-dropdown-overview">
                {/* Compact Context Bar */}
                <ContextBar context={data.tradingContext} formatAgo={formatAgo} />

                {/* Suggestion Card (only if active) */}
                <SuggestionCard
                  suggestion={activeSuggestion}
                  onAccept={() => void sendSuggestionFeedback('accept')}
                  onDismiss={() => void sendSuggestionFeedback('dismiss')}
                  onAsk={() => setActiveTab('chat')}
                  disabled={!operatorUnlocked || !resolveSuggestionId()}
                  busy={feedbackBusy}
                />

                {/* Metrics Row */}
                <div className="pearl-dropdown-metrics">
                  {!operatorUnlocked ? (
                    <div className="pearl-dropdown-metrics-muted">Unlock to view metrics.</div>
                  ) : metricsData.loading && !metricsData.summary ? (
                    <div className="pearl-dropdown-metrics-muted">Loading metrics…</div>
                  ) : metricsData.summary ? (
                    <div className="pearl-dropdown-metrics-row">
                      <span className="pearl-metric-pill">p95 {Math.round(metricsData.summary.p95_latency_ms)}ms</span>
                      <span className="pearl-metric-pill">cache {Math.round(metricsData.summary.cache_hit_rate * 100)}%</span>
                      <span className="pearl-metric-pill">
                        cost ${typeof metricsData.cost?.today_usd === 'number' ? metricsData.cost.today_usd.toFixed(3) : '—'}
                      </span>
                      <button
                        type="button"
                        className="pearl-metric-refresh"
                        onClick={() => void refreshMetrics(true)}
                        disabled={metricsData.loading || !data.status.chatAvailable}
                        title="Refresh metrics"
                      >
                        ↻
                      </button>
                    </div>
                  ) : metricsData.error ? (
                    <div className="pearl-dropdown-metrics-muted">Metrics: {metricsData.error}</div>
                  ) : (
                    <button
                      type="button"
                      className="pearl-btn pearl-btn-neutral"
                      onClick={() => void refreshMetrics(true)}
                      disabled={!data.status.chatAvailable}
                    >
                      Load metrics
                    </button>
                  )}
                </div>

                {/* Quick Actions (with collapsible More) */}
                <QuickActionsRow
                  onAction={(id) => void quickActions.runAction(id as any)}
                  busy={quickActions.busy}
                  disabled={!operatorUnlocked || !data.status.chatAvailable || chat.busy}
                  expanded={quickActionsExpanded}
                  onToggleExpand={() => setQuickActionsExpanded(!quickActionsExpanded)}
                />

                {quickActions.result && (
                  <div className={`pearl-dropdown-result ${quickActions.result.type}`}>
                    {quickActions.result.message}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* AI Component Status Pills */}
        {(!isDropdown || activeTab === 'overview') && aiStatus && (
          <div className="pearl-ai-status">
            <div className="ai-pills">
              <ModePill label="Bandit" mode={aiStatus.bandit_mode as PearlMode} />
              <ModePill label="Contextual" mode={aiStatus.contextual_mode as PearlMode} />
              <ModePill label="ML" mode={mlMode as PearlMode} />
            </div>

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

            {aiStatus.direction_gating.enabled && aiStatus.direction_gating.blocks > 0 && (
              <div className="ai-gating-compact">
                <span className="gating-label">Gating:</span>
                <span className="gating-count">{aiStatus.direction_gating.blocks} blocks</span>
              </div>
            )}
          </div>
        )}

        {/* Shadow Mode Banner */}
        {(!isDropdown || activeTab === 'overview') && hasShadowMode && (
          <div className="shadow-mode-banner">
            <span className="shadow-mode-icon">🦪</span>
            <span className="shadow-mode-text">
              <em>PEARL AI</em> is in <em>SHADOW</em> mode — observing trades but not affecting decisions.
            </span>
          </div>
        )}

        {/* Operator Lock Strip */}
        <div className="pearl-operator-strip" role="group" aria-label="Operator access control">
          <div className="pearl-operator-left">
            <span
              className={`pearl-operator-dot ${operatorUnlocked ? 'on' : 'off'}`}
              role="status"
              aria-label={operatorUnlocked ? 'Operator access granted' : 'Read-only mode'}
            />
            <span className="pearl-operator-label">{operatorUnlocked ? 'Operator unlocked' : 'Read-only'}</span>
            {operatorUnlocked && (
              <span className="pearl-operator-ttl" aria-live="polite">
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
                  aria-label="Enter passphrase to unlock operator access"
                >
                  Unlock
                </button>
              ) : (
                <div className="pearl-operator-unlock" role="form" aria-label="Unlock form">
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
                      } else if (e.key === 'Escape') {
                        setUnlockOpen(false)
                        setUnlockValue('')
                        setUnlockError(null)
                      }
                    }}
                    aria-label="Operator passphrase"
                    autoComplete="current-password"
                    autoFocus
                  />
                  <button
                    type="button"
                    className="pearl-btn pearl-btn-neutral pearl-operator-go"
                    onClick={() => void attemptUnlock()}
                    disabled={unlockBusy || !unlockValue.trim() || operatorLockEnabled === false}
                    aria-label={unlockBusy ? 'Verifying passphrase' : 'Submit passphrase'}
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
                    aria-label="Cancel unlock"
                  >
                    ×
                  </button>
                </div>
              )
            ) : (
              <button
                type="button"
                className="pearl-btn pearl-btn-neutral"
                onClick={operatorLock}
                aria-label="Lock operator access"
              >
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

        {/* Feed Tab - Transparency & Feed */}
        {(!isDropdown || activeTab === 'feed') && (pearlFeed.length > 0 || pearlAIHeartbeat || pearlAIDebug) && (
          <div className="pearl-transparency">
            <div className="transparency-header">
              <div className="transparency-left">
                <span className={`pearl-heartbeat-dot ${data.status.heartbeatRecent ? 'on' : 'off'}`} />
                <span className="transparency-title">Transparency</span>
                <span className="transparency-sub">{formatAgo(data.status.lastActivityTs)}</span>
              </div>
              {!isDropdown && (
                <button
                  className="details-toggle"
                  onClick={() => setShowTransparency(!showTransparency)}
                  type="button"
                >
                  {showTransparency ? '−' : '+'}
                </button>
              )}
            </div>

            {transparencyExpanded && (
              <div className="transparency-body">
                <div className="pearl-heartbeat-grid">
                  <div className="hb-item">
                    <span className="hb-k">Mounted</span>
                    <span className="hb-v">{pearlAIHeartbeat?.mounted ? 'yes' : 'no'}</span>
                  </div>
                  <div className="hb-item">
                    <span className="hb-k">Feed</span>
                    <span className="hb-v">
                      {typeof pearlAIHeartbeat?.feed_total === 'number' ? pearlAIHeartbeat.feed_total : pearlFeed.length}
                    </span>
                  </div>
                  <div className="hb-item">
                    <span className="hb-k">Route</span>
                    <span className="hb-v">{routingLabel}</span>
                  </div>
                  <div className="hb-item">
                    <span className="hb-k">Source</span>
                    <span className="hb-v">{pearlAIDebug?.response_source || '—'}</span>
                  </div>
                  <div className="hb-item">
                    <span className="hb-k">Model</span>
                    <span className="hb-v">{pearlAIDebug?.model_used || '—'}</span>
                  </div>
                  <div className="hb-item">
                    <span className="hb-k">Latency</span>
                    <span className="hb-v">
                      {typeof pearlAIDebug?.latency_ms === 'number' ? `${Math.round(pearlAIDebug.latency_ms)}ms` : '—'}
                    </span>
                  </div>
                  <div className="hb-item">
                    <span className="hb-k">Cache</span>
                    <span className="hb-v">
                      {pearlAIDebug?.cache_hit === true ? 'hit' : pearlAIDebug?.cache_hit === false ? 'miss' : '—'}
                    </span>
                  </div>
                  <div className="hb-item">
                    <span className="hb-k">Fallback</span>
                    <span className="hb-v">
                      {pearlAIDebug?.fallback_used === true ? 'yes' : pearlAIDebug?.fallback_used === false ? 'no' : '—'}
                    </span>
                  </div>
                  <div className="hb-item">
                    <span className="hb-k">Tools</span>
                    <span className="hb-v">{toolCount > 0 ? toolCount : '—'}</span>
                  </div>
                </div>

                <div className="pearl-feed">
                  <div className="pearl-feed-title">Recent Pearl messages</div>
                  {isDropdown && (
                    <div className="pearl-feed-controls" aria-label="Feed filters">
                      <input
                        className="pearl-feed-search"
                        value={feedQuery}
                        onChange={(e) => setFeedQuery(e.target.value)}
                        placeholder="Search feed…"
                      />
                      <div className="pearl-feed-filters" role="tablist" aria-label="Feed type">
                        {([
                          ['all', 'All'],
                          ['narration', 'Narration'],
                          ['insight', 'Insight'],
                          ['coaching', 'Coaching'],
                          ['alert', 'Alert'],
                          ['response', 'Response'],
                        ] as Array<[typeof feedType, string]>).map(([k, label]) => (
                          <button
                            key={k}
                            type="button"
                            role="tab"
                            aria-selected={feedType === k}
                            className={`pearl-filter-pill ${feedType === k ? 'active' : ''}`}
                            onClick={() => setFeedType(k)}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  {filteredFeed.length === 0 ? (
                    <div className="pearl-feed-empty" role="status">
                      {pearlFeed.length === 0 ? 'No Pearl feed messages yet.' : 'No matches.'}
                    </div>
                  ) : (
                    <div
                      ref={feedListRef}
                      className="pearl-feed-list"
                      role="feed"
                      aria-label="Pearl AI feed messages"
                    >
                      {filteredFeed.slice(0, 40).map((m, idx) => (
                        <details
                          key={`feed-${m.id}-${idx}`}
                          className={`pearl-feed-item type-${m.type || 'message'}`}
                        >
                          <summary
                            className="pearl-feed-summary"
                            aria-label={`${m.type || 'message'}: ${m.content.slice(0, 60)}${m.content.length > 60 ? '...' : ''}`}
                          >
                            <span className="pearl-feed-icon" aria-hidden="true">{getFeedIcon(m.type)}</span>
                            <span className="pearl-feed-type">{(m.type || 'message').toUpperCase()}</span>
                            <span className="pearl-feed-time">{formatAgo(m.timestamp)}</span>
                            <span className="pearl-feed-text">{m.content}</span>
                          </summary>

                          <div className="pearl-feed-body">
                            {m.metadata?.details && (
                              <div className="pearl-feed-details">
                                {renderNarrationDetails(m.metadata.details)}
                              </div>
                            )}
                            {!m.metadata?.details && operatorUnlocked && (
                              <div className="pearl-feed-raw">
                                <div className="pearl-feed-raw-title">Metadata</div>
                                <pre className="pearl-feed-raw-pre">
                                  {JSON.stringify(m.metadata || {}, null, 2)}
                                </pre>
                              </div>
                            )}
                            {!m.metadata?.details && !operatorUnlocked && (
                              <div className="pearl-feed-raw">
                                <div className="pearl-feed-raw-title">Metadata</div>
                                <div className="pearl-feed-empty">Unlock to view raw metadata.</div>
                              </div>
                            )}
                          </div>
                        </details>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Chat Tab */}
        {(!isDropdown || activeTab === 'chat') && (
          <div className={`pearl-chat ${isDropdown ? 'pearl-chat-dropdown' : ''}`}>
            {!isDropdown && (
              <button
                className="pearl-chat-toggle"
                onClick={() => setChatOpen(!chatOpen)}
                type="button"
              >
                {chatOpen ? '−' : '+'} Ask Pearl (LLM)
              </button>
            )}
            {isDropdown && <div className="pearl-chat-title">Ask Pearl (LLM)</div>}

            {chatExpanded && (
              <div className="pearl-chat-body">
                <div
                  ref={chatMessagesRef}
                  className="pearl-chat-messages"
                  role="log"
                  aria-live="polite"
                  aria-label="Chat messages"
                >
                  {chat.messages.length === 0 ? (
                    <div className="pearl-chat-empty">
                      Ask about today&apos;s setup, why signals are quiet, or what to watch next.
                    </div>
                  ) : (
                    chat.messages.map((m, idx) => (
                      <div
                        key={`chat-${idx}-${m.role}`}
                        className={`pearl-chat-msg ${m.role}`}
                        role="article"
                        aria-label={`${m.role === 'user' ? 'You' : 'Pearl'}: ${m.text.slice(0, 50)}${m.text.length > 50 ? '...' : ''}`}
                      >
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
                    void chat.sendMessage()
                  }}
                  aria-label="Chat with Pearl AI"
                >
                  <input
                    className="pearl-chat-input"
                    value={chat.input}
                    onChange={(e) => chat.setInput(e.target.value)}
                    placeholder="Ask Pearl…"
                    disabled={chat.busy || !operatorUnlocked || !data.status.chatAvailable}
                    aria-label="Message input"
                    autoComplete="off"
                  />
                  <button
                    className="pearl-chat-send"
                    type="submit"
                    disabled={chat.busy || !chat.input.trim() || !operatorUnlocked || !data.status.chatAvailable}
                    aria-label={chat.busy ? 'Sending message' : 'Send message'}
                  >
                    {chat.busy ? '…' : 'Send'}
                  </button>
                  <button
                    className="pearl-chat-clear"
                    type="button"
                    onClick={chat.clearMessages}
                    disabled={chat.busy || chat.messages.length === 0}
                    aria-label="Clear chat history"
                  >
                    Clear
                  </button>
                </form>

                {chat.error && <div className="pearl-chat-error">{chat.error}</div>}
                <div className="pearl-chat-hint">
                  {!operatorUnlocked
                    ? 'Read-only mode. Unlock operator access to chat.'
                    : !data.status.chatAvailable
                      ? 'LLM chat is disabled on this server.'
                      : 'Operator-only. Requires Pearl AI endpoints on the API server.'}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Costs Tab */}
        {activeTab === 'costs' && isDropdown && (
          <div className="pearl-costs-dashboard" role="region" aria-label="AI Cost Transparency">
            <div className="pearl-costs-header">
              <span className="pearl-costs-title">AI Cost Transparency</span>
              <button
                type="button"
                className={`pearl-metric-refresh ${metricsData.loading ? 'spinning' : ''}`}
                onClick={() => void refreshMetrics(true)}
                disabled={metricsData.loading || !data.status.chatAvailable || !operatorUnlocked}
                title="Refresh metrics"
                aria-label={metricsData.loading ? 'Loading metrics' : 'Refresh metrics'}
              >
                ↻
              </button>
            </div>

            {!operatorUnlocked ? (
              <div className="pearl-costs-locked">
                <span className="lock-icon">🔒</span>
                <span>Unlock operator access to view cost data</span>
              </div>
            ) : metricsData.error ? (
              <div className="pearl-costs-error">{metricsData.error}</div>
            ) : metricsData.loading && !metricsData.summary ? (
              <div className="pearl-costs-loading">Loading cost data...</div>
            ) : metricsData.summary && metricsData.cost ? (
              <>
                {/* Cost Summary Cards */}
                <div className="pearl-costs-cards">
                  <div className="pearl-cost-card today">
                    <div className="cost-card-value">${metricsData.cost.today_usd.toFixed(3)}</div>
                    <div className="cost-card-label">Today</div>
                    {metricsData.cost.limit_usd && (
                      <div className="cost-card-limit">
                        {Math.round((metricsData.cost.today_usd / metricsData.cost.limit_usd) * 100)}% of ${metricsData.cost.limit_usd} limit
                      </div>
                    )}
                  </div>
                  <div className="pearl-cost-card month">
                    <div className="cost-card-value">${metricsData.cost.month_usd.toFixed(2)}</div>
                    <div className="cost-card-label">This Month</div>
                  </div>
                  <div className="pearl-cost-card tokens">
                    <div className="cost-card-value">{(metricsData.summary.total_tokens / 1000).toFixed(1)}k</div>
                    <div className="cost-card-label">Tokens (24h)</div>
                  </div>
                  <div className="pearl-cost-card requests">
                    <div className="cost-card-value">{metricsData.summary.total_requests}</div>
                    <div className="cost-card-label">Requests (24h)</div>
                  </div>
                </div>

                {/* Response Source Distribution */}
                <div className="pearl-costs-section">
                  <div className="pearl-costs-section-title">Response Sources (24h)</div>
                  <div className="pearl-source-bars">
                    {(() => {
                      const sources = metricsData.sources?.counts || {
                        cache: 0,
                        local: 0,
                        claude: 0,
                        template: 0,
                      }
                      const total = Object.values(sources).reduce((a, b) => a + b, 0) || 1
                      const sourceLabels: Record<string, { label: string; color: string; cost: string }> = {
                        cache: { label: 'Cache', color: 'var(--color-success)', cost: 'Free' },
                        local: { label: 'Ollama', color: 'var(--color-info)', cost: 'Free' },
                        claude: { label: 'Claude', color: 'var(--color-warning)', cost: 'Paid' },
                        template: { label: 'Template', color: 'var(--color-muted)', cost: 'Free' },
                      }
                      return Object.entries(sources).map(([key, count]) => {
                        const pct = (count / total) * 100
                        const meta = sourceLabels[key] || { label: key, color: 'var(--color-muted)', cost: '?' }
                        return (
                          <div key={key} className="pearl-source-row">
                            <div className="pearl-source-label">
                              <span className="source-name">{meta.label}</span>
                              <span className={`source-cost ${meta.cost === 'Free' ? 'free' : 'paid'}`}>{meta.cost}</span>
                            </div>
                            <div className="pearl-source-bar-track">
                              <div
                                className="pearl-source-bar-fill"
                                style={{ width: `${pct}%`, backgroundColor: meta.color }}
                              />
                            </div>
                            <div className="pearl-source-value">
                              <span className="source-count">{count}</span>
                              <span className="source-pct">{pct.toFixed(0)}%</span>
                            </div>
                          </div>
                        )
                      })
                    })()}
                  </div>
                </div>

                {/* Model Usage Breakdown */}
                {metricsData.summary.by_model && Object.keys(metricsData.summary.by_model).length > 0 && (
                  <div className="pearl-costs-section">
                    <div className="pearl-costs-section-title">Model Usage (24h)</div>
                    <div className="pearl-model-table">
                      <div className="pearl-model-header">
                        <span className="model-col model">Model</span>
                        <span className="model-col reqs">Reqs</span>
                        <span className="model-col tokens">Tokens</span>
                        <span className="model-col cost">Cost</span>
                        <span className="model-col latency">Avg Latency</span>
                      </div>
                      {Object.entries(metricsData.summary.by_model).map(([model, stats]) => {
                        const shortModel = model
                          .replace('claude-', '')
                          .replace('-20250514', '')
                          .replace('-20241022', '')
                        const isFree = model.includes('llama') || model === 'cache' || model === 'template'
                        return (
                          <div key={model} className={`pearl-model-row ${isFree ? 'free' : 'paid'}`}>
                            <span className="model-col model" title={model}>{shortModel}</span>
                            <span className="model-col reqs">{stats.count}</span>
                            <span className="model-col tokens">{(stats.tokens / 1000).toFixed(1)}k</span>
                            <span className="model-col cost">${stats.cost_usd.toFixed(3)}</span>
                            <span className="model-col latency">{Math.round(stats.avg_latency_ms)}ms</span>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}

                {/* Endpoint Breakdown */}
                {metricsData.summary.by_endpoint && Object.keys(metricsData.summary.by_endpoint).length > 0 && (
                  <div className="pearl-costs-section">
                    <div className="pearl-costs-section-title">Endpoint Usage (24h)</div>
                    <div className="pearl-endpoint-grid">
                      {Object.entries(metricsData.summary.by_endpoint).map(([endpoint, stats]) => (
                        <div key={endpoint} className="pearl-endpoint-card">
                          <div className="endpoint-name">{endpoint}</div>
                          <div className="endpoint-stats">
                            <span className="endpoint-stat">{stats.count} reqs</span>
                            <span className="endpoint-stat">${stats.cost_usd.toFixed(3)}</span>
                            <span className="endpoint-stat">{Math.round(stats.avg_latency_ms)}ms</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Performance Stats */}
                <div className="pearl-costs-section">
                  <div className="pearl-costs-section-title">Performance (24h)</div>
                  <div className="pearl-perf-grid">
                    <div className="pearl-perf-item">
                      <span className="perf-label">Cache Hit Rate</span>
                      <span className={`perf-value ${metricsData.summary.cache_hit_rate > 0.3 ? 'good' : ''}`}>
                        {(metricsData.summary.cache_hit_rate * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">Error Rate</span>
                      <span className={`perf-value ${metricsData.summary.error_rate > 0.05 ? 'bad' : 'good'}`}>
                        {(metricsData.summary.error_rate * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">Fallback Rate</span>
                      <span className="perf-value">
                        {(metricsData.summary.fallback_rate * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">p50 Latency</span>
                      <span className="perf-value">{Math.round(metricsData.summary.p50_latency_ms || 0)}ms</span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">p95 Latency</span>
                      <span className="perf-value">{Math.round(metricsData.summary.p95_latency_ms)}ms</span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">p99 Latency</span>
                      <span className="perf-value">{Math.round(metricsData.summary.p99_latency_ms || 0)}ms</span>
                    </div>
                  </div>
                </div>

                {/* Cost Optimization Tips */}
                <div className="pearl-costs-tips">
                  <div className="pearl-costs-tips-title">Cost Optimization</div>
                  <ul className="pearl-tips-list">
                    {metricsData.summary.cache_hit_rate < 0.2 && (
                      <li className="tip">Low cache hit rate ({(metricsData.summary.cache_hit_rate * 100).toFixed(0)}%). Similar queries could benefit from caching.</li>
                    )}
                    {metricsData.sources && metricsData.sources.counts.claude > (metricsData.sources.counts.local || 0) * 2 && (
                      <li className="tip">Heavy Claude usage. Consider routing simpler queries to local Ollama.</li>
                    )}
                    {metricsData.summary.by_model?.['claude-sonnet-4-20250514']?.count > 50 && (
                      <li className="tip">High Sonnet usage. Route simple queries to Haiku for 3x savings.</li>
                    )}
                    {metricsData.cost.limit_usd && metricsData.cost.today_usd > metricsData.cost.limit_usd * 0.5 && (
                      <li className="tip warning">Over 50% of daily budget used.</li>
                    )}
                    {metricsData.summary.cache_hit_rate >= 0.3 && metricsData.sources && metricsData.sources.counts.local >= metricsData.sources.counts.claude && (
                      <li className="tip success">Good cost efficiency. Cache and local LLM handling most queries.</li>
                    )}
                  </ul>
                </div>

                {/* Last Updated */}
                {metricsData.asOfMs && (
                  <div className="pearl-costs-footer">
                    Updated {formatAgo(new Date(metricsData.asOfMs).toISOString())}
                  </div>
                )}
              </>
            ) : (
              <div className="pearl-costs-empty">
                <button
                  type="button"
                  className="pearl-btn pearl-btn-neutral"
                  onClick={() => void refreshMetrics(true)}
                  disabled={!data.status.chatAvailable || !operatorUnlocked}
                >
                  Load Cost Data
                </button>
              </div>
            )}
          </div>
        )}

        {/* ML Filter Performance - Win Rate Comparison */}
        {!isDropdown &&
          mlFilterPerformance &&
          (mlFilterPerformance.win_rate_pass !== undefined || mlFilterPerformance.win_rate_fail !== undefined) && (
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

        {/* Current Insight / Suggestion (Panel Mode) */}
        {!isDropdown && activeSuggestion && (
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

        {/* No Active Suggestion State (Panel Mode) */}
        {!isDropdown && !activeSuggestion && (
          <div className="pearl-no-insight">
            <span className="no-insight-icon">✨</span>
            <span className="no-insight-text">Watching for opportunities...</span>
          </div>
        )}

        {/* Shadow Tracking Impact Summary */}
        {(!isDropdown || activeTab === 'overview') && metrics && totalSuggestions > 0 && (
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

            {showDetails && (
              <div className="shadow-details">
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

                <div className="shadow-stats-compact">
                  <span className="stat">✓ {suggestionsFollowed} followed</span>
                  <span className="stat">✗ {suggestionsDismissed} dismissed</span>
                  <span className="stat">⏱ {metrics.suggestions_expired} expired</span>
                </div>

                {metrics.recent_suggestions && metrics.recent_suggestions.length > 0 && (
                  <button
                    className="history-toggle-btn"
                    onClick={() => setShowHistory(!showHistory)}
                  >
                    {showHistory ? 'Hide History ▲' : 'Show History ▼'}
                  </button>
                )}

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
        {(!isDropdown || activeTab === 'overview') && (!metrics || totalSuggestions === 0) && !activeSuggestion && !aiStatus && (
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

// ============================================================================
// Helper Functions
// ============================================================================

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

function getFeedIcon(type?: string): string {
  switch ((type || '').toLowerCase()) {
    case 'narration':
      return '🗣️'
    case 'insight':
      return '💡'
    case 'alert':
      return '⚠️'
    case 'response':
      return '🧠'
    default:
      return '🦪'
  }
}

function renderNarrationDetails(details: any) {
  if (!details || typeof details !== 'object') return null

  const title = typeof details.title === 'string' ? details.title : null
  const text = typeof details.text === 'string' ? details.text : null
  const lines = Array.isArray(details.lines) ? details.lines.filter((l: any) => typeof l === 'string') : []
  const kv =
    details.kv && typeof details.kv === 'object' && !Array.isArray(details.kv)
      ? (details.kv as Record<string, any>)
      : null
  const sections = Array.isArray(details.sections) ? details.sections : []
  const truncated = Boolean(details.truncated)

  const renderKv = (obj: Record<string, any>) => {
    const entries = Object.entries(obj).slice(0, 30)
    if (entries.length === 0) return null
    return (
      <div className="pearl-kv-grid">
        {entries.map(([k, v]) => (
          <div key={k} className="pearl-kv-row">
            <span className="pearl-kv-k">{k}</span>
            <span className="pearl-kv-v">{typeof v === 'string' ? v : JSON.stringify(v)}</span>
          </div>
        ))}
      </div>
    )
  }

  return (
    <div className="pearl-narration-details">
      {title && <div className="pearl-details-title">{title}</div>}
      {text && <div className="pearl-details-text">{text}</div>}
      {lines.length > 0 && (
        <ul className="pearl-details-lines">
          {lines.slice(0, 20).map((l: string, i: number) => (
            <li key={i}>{l}</li>
          ))}
        </ul>
      )}
      {kv && renderKv(kv)}

      {sections.length > 0 && (
        <div className="pearl-details-sections">
          {sections.slice(0, 8).map((s: any, idx: number) => {
            const st = typeof s?.title === 'string' ? s.title : null
            const slines = Array.isArray(s?.lines) ? s.lines.filter((l: any) => typeof l === 'string') : []
            const skv =
              s?.kv && typeof s.kv === 'object' && !Array.isArray(s.kv)
                ? (s.kv as Record<string, any>)
                : null
            const stext = typeof s?.text === 'string' ? s.text : null
            return (
              <div key={idx} className="pearl-details-section">
                {st && <div className="pearl-details-section-title">{st}</div>}
                {stext && <div className="pearl-details-text">{stext}</div>}
                {slines.length > 0 && (
                  <ul className="pearl-details-lines">
                    {slines.slice(0, 12).map((l: string, i: number) => (
                      <li key={i}>{l}</li>
                    ))}
                  </ul>
                )}
                {skv && renderKv(skv)}
              </div>
            )
          })}
        </div>
      )}

      {truncated && <div className="pearl-details-truncated">…truncated</div>}
    </div>
  )
}
