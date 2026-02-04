'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { InfoTooltip } from './ui'
import { apiFetch, apiFetchJson } from '@/lib/api'
import { useOperatorStore } from '@/stores'
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

interface PearlInsightsPanelProps {
  insights: PearlInsights | null
  suggestion: PearlSuggestion | null
  agentState?: AgentState | null
  aiStatus?: AIStatus | null
  shadowCounters?: ShadowCounters | null
  mlFilterPerformance?: MLFilterPerformance | null
  /** Whether the LLM chat endpoint is mounted/available on the API server */
  chatAvailable?: boolean
  /** Whether operator passphrase locking is configured on the API server (null = unknown) */
  operatorLockEnabled?: boolean | null
  /** Recent Pearl AI messages (narrations, insights, alerts, chat responses) */
  pearlFeed?: PearlFeedMessage[]
  /** Lightweight 'heartbeat' snapshot for Pearl AI */
  pearlAIHeartbeat?: PearlAIHeartbeat | null
  /** Last Pearl AI debug snapshot (routing/model/tools/latency/cache) */
  pearlAIDebug?: PearlAIDebugInfo | null
  /** Layout mode (full panel vs header dropdown) */
  layout?: 'panel' | 'dropdown'
  /** Dropdown is currently expanded/visible (prevents background polling when collapsed) */
  dropdownActive?: boolean
  initialChatOpen?: boolean
}

type Mode = 'off' | 'shadow' | 'live'
type DropdownTab = 'overview' | 'feed' | 'chat' | 'costs'

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

type ModelMetrics = {
  count: number
  tokens: number
  cost_usd: number
  avg_latency_ms: number
  error_rate: number
}

type MetricsSummary = {
  period_hours: number
  total_requests: number
  total_tokens: number
  total_cost_usd: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
  cache_hit_rate: number
  error_rate: number
  fallback_rate: number
  by_endpoint: Record<string, ModelMetrics>
  by_model: Record<string, ModelMetrics>
}

type ResponseSourceDist = {
  counts: Record<string, number>
  percentages: Record<string, number>
  total: number
  period_hours?: number
  period?: string
}

type CostSummary = {
  today_usd: number
  month_usd: number
  limit_usd: number | null
}

type GenerateMessageResponse =
  | { generated: true; content: string; timestamp: string }
  | { generated: false; reason: string }

/** Mode indicator pill with tooltip for shadow mode */
function ModePill({ label, mode }: { label: string; mode: Mode }) {
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
  const [showHistory, setShowHistory] = useState(false)
  const [showDetails, setShowDetails] = useState(false)
  const [showTransparency, setShowTransparency] = useState(false)
  const [chatOpen, setChatOpen] = useState(initialChatOpen)
  const isDropdown = layout === 'dropdown'
  const [dropdownTab, setDropdownTab] = useState<DropdownTab>(() => (initialChatOpen ? 'chat' : 'overview'))
  const [chatInput, setChatInput] = useState('')
  const [chatBusy, setChatBusy] = useState(false)
  const [chatError, setChatError] = useState<string | null>(null)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([])
  const [nowMs, setNowMs] = useState(() => Date.now())

  const [feedQuery, setFeedQuery] = useState('')
  const [feedType, setFeedType] = useState<
    'all' | 'narration' | 'insight' | 'coaching' | 'alert' | 'response' | 'message'
  >('all')

  const [metricsSummary, setMetricsSummary] = useState<MetricsSummary | null>(null)
  const [costSummary, setCostSummary] = useState<CostSummary | null>(null)
  const [sourceDist, setSourceDist] = useState<ResponseSourceDist | null>(null)
  const [metricsBusy, setMetricsBusy] = useState(false)
  const [metricsError, setMetricsError] = useState<string | null>(null)
  const [metricsAsOfMs, setMetricsAsOfMs] = useState<number | null>(null)

  const [quickBusy, setQuickBusy] = useState<string | null>(null)
  const [quickResult, setQuickResult] = useState<{ type: 'ok' | 'error'; message: string } | null>(null)

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

  // Refs for auto-scroll
  const chatMessagesRef = useRef<HTMLDivElement>(null)
  const feedListRef = useRef<HTMLDivElement>(null)

  const metrics = insights?.shadow_metrics
  const activeSuggestion = suggestion || metrics?.active_suggestion
  const latestFeed = pearlFeed.length > 0 ? pearlFeed[pearlFeed.length - 1] : null
  const dropdownHeadline = latestFeed?.content || activeSuggestion?.message || 'Watching for opportunities…'

  const filteredFeed = useMemo(() => {
    const rows = [...(pearlFeed || [])].slice(-60).reverse()
    const q = feedQuery.trim().toLowerCase()

    return rows.filter((m) => {
      const mt = (m?.type || 'message').toLowerCase()
      if (feedType !== 'all' && mt !== feedType) return false

      if (!q) return true

      const details = (m as any)?.metadata?.details
      const detailsText =
        typeof details?.text === 'string' ? details.text : ''
      const detailsTitle =
        typeof details?.title === 'string' ? details.title : ''
      const detailsLines = Array.isArray(details?.lines) ? details.lines.join(' ') : ''

      const hay = `${m?.content || ''} ${m?.type || ''} ${m?.priority || ''} ${detailsTitle} ${detailsText} ${detailsLines}`.toLowerCase()
      return hay.includes(q)
    })
  }, [pearlFeed, feedQuery, feedType])

  const getMs = (iso?: string | null): number | null => {
    if (!iso) return null
    const t = Date.parse(iso)
    return Number.isFinite(t) ? t : null
  }

  const formatAgo = (iso?: string | null): string => {
    const t = getMs(iso)
    if (!t) return '—'
    const s = Math.max(0, Math.floor((nowMs - t) / 1000))
    if (s < 60) return `${s}s ago`
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 48) return `${h}h ago`
    const d = Math.floor(h / 24)
    return `${d}d ago`
  }

  const lastMessageTs =
    pearlAIHeartbeat?.last_message_time ||
    (pearlFeed.length > 0 ? (pearlFeed[pearlFeed.length - 1]?.timestamp ?? null) : null)

  const lastStateTs =
    pearlAIHeartbeat?.last_state_sync_time ||
    pearlAIHeartbeat?.last_state_seen_time ||
    null

  const lastActivityTs = lastMessageTs || lastStateTs

  const heartbeatRecent = (() => {
    const t = getMs(lastActivityTs)
    if (!t) return false
    return nowMs - t < 15000
  })()

  const routingLabel = useMemo((): string => {
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
  }, [pearlAIDebug?.routing])

  const toolCount = Array.isArray(pearlAIDebug?.tool_calls) ? pearlAIDebug!.tool_calls!.length : 0

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
  const hasShadowMode = Boolean(aiStatus && (
    aiStatus.bandit_mode === 'shadow' ||
    aiStatus.contextual_mode === 'shadow' ||
    mlMode === 'shadow'
  ))

  const overallMode: Mode = (() => {
    if (hasShadowMode || metrics?.mode === 'shadow') return 'shadow'
    if (
      aiStatus &&
      (aiStatus.bandit_mode === 'live' || aiStatus.contextual_mode === 'live' || mlMode === 'live')
    ) {
      return 'live'
    }
    return 'off'
  })()

  const statusPnL = typeof agentState?.daily_pnl === 'number' ? agentState!.daily_pnl : null
  const statusWins = typeof agentState?.daily_wins === 'number' ? agentState!.daily_wins : null
  const statusLosses = typeof agentState?.daily_losses === 'number' ? agentState!.daily_losses : null
  const statusPos = typeof agentState?.active_trades_count === 'number' ? agentState!.active_trades_count : null
  const statusRegime = agentState?.market_regime?.regime || null
  const statusAllowedDir = agentState?.market_regime?.allowed_direction || null
  const statusDataFresh = typeof agentState?.data_fresh === 'boolean' ? agentState!.data_fresh : null
  const statusMarketOpen = typeof agentState?.futures_market_open === 'boolean' ? agentState!.futures_market_open : null
  const lastDecision = agentState?.last_signal_decision || null
  const decisionLabel = lastDecision?.action ? lastDecision.action.toUpperCase() : null
  const decisionAgo = lastDecision?.timestamp ? formatAgo(lastDecision.timestamp) : null

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

  // Auto-scroll chat messages to bottom when new messages arrive
  useEffect(() => {
    if (chatMessagesRef.current && chatMessages.length > 0) {
      chatMessagesRef.current.scrollTo({
        top: chatMessagesRef.current.scrollHeight,
        behavior: 'smooth',
      })
    }
  }, [chatMessages.length])

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

  const resolveSuggestionId = useCallback((): string | null => {
    // Check activeSuggestion for id (may come from shadow_metrics or direct suggestion)
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

  const sendChatText = useCallback(async (message: string) => {
    const m = (message || '').trim()
    if (!m || chatBusy) return

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

    setChatMessages((prev) => [...prev, { role: 'user' as const, text: m }].slice(-12))

    try {
      const res = await apiFetchJson<PearlChatResponse>('/api/pearl/chat', {
        method: 'POST',
        body: JSON.stringify({ message: m }),
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
  }, [chatBusy, chatAvailable, operatorUnlocked])

  const sendChat = async () => {
    const message = chatInput.trim()
    if (!message || chatBusy) return
    await sendChatText(message)
  }

  const refreshMetrics = useCallback(async (force: boolean = false) => {
    if (metricsBusy) return

    if (!chatAvailable) {
      setMetricsError('Pearl AI endpoints are disabled on this server.')
      return
    }
    if (!operatorUnlocked) {
      setMetricsError('Operator access required.')
      return
    }

    if (!force && metricsAsOfMs && Date.now() - metricsAsOfMs < 15000) {
      return
    }

    setMetricsBusy(true)
    setMetricsError(null)
    try {
      const [m, c, s] = await Promise.all([
        apiFetchJson<MetricsSummary>('/api/pearl/metrics?hours=24', { method: 'GET' }),
        apiFetchJson<CostSummary>('/api/pearl/metrics/cost', { method: 'GET' }),
        apiFetchJson<ResponseSourceDist>('/api/pearl/metrics/sources?hours=24', { method: 'GET' }).catch(() => null),
      ])
      setMetricsSummary(m)
      setCostSummary(c)
      if (s) setSourceDist(s)
      setMetricsAsOfMs(Date.now())
    } catch (e) {
      setMetricsError(e instanceof Error ? e.message : 'Metrics fetch failed')
    } finally {
      setMetricsBusy(false)
    }
  }, [metricsBusy, chatAvailable, operatorUnlocked, metricsAsOfMs])

  useEffect(() => {
    if (!isDropdown || !dropdownActive) return
    if (dropdownTab !== 'overview' && dropdownTab !== 'costs') return
    if (!operatorUnlocked || !chatAvailable) return

    void refreshMetrics(false)
  }, [isDropdown, dropdownActive, dropdownTab, operatorUnlocked, chatAvailable, refreshMetrics])

  const runQuickChat = useCallback(async (id: string, message: string) => {
    if (quickBusy) return

    setQuickBusy(id)
    setQuickResult(null)
    setChatError(null)

    if (isDropdown) {
      setDropdownTab('chat')
    } else {
      setChatOpen(true)
    }

    try {
      await sendChatText(message)
    } finally {
      setQuickBusy(null)
    }
  }, [quickBusy, isDropdown, sendChatText, setChatOpen])

  const triggerInsight = useCallback(async () => {
    if (quickBusy) return
    setQuickBusy('insight')
    setQuickResult(null)
    try {
      const res = await apiFetchJson<GenerateMessageResponse>('/api/pearl/insight', { method: 'POST' })
      if ((res as any)?.generated) {
        setQuickResult({ type: 'ok', message: 'Insight generated.' })
      } else {
        const reason = (res as any)?.reason || 'No insight generated.'
        // Fallback: ask via chat so local LLM can still help.
        if (isDropdown) {
          setDropdownTab('chat')
        } else {
          setChatOpen(true)
        }
        await sendChatText('Give me ONE brief, actionable insight for this session based on current state.')
        setQuickResult({ type: 'ok', message: reason })
      }
    } catch (e) {
      setQuickResult({ type: 'error', message: e instanceof Error ? e.message : 'Insight failed' })
    } finally {
      setQuickBusy(null)
    }
  }, [quickBusy, isDropdown, sendChatText, setChatOpen])

  const triggerDailyReview = useCallback(async () => {
    if (quickBusy) return
    setQuickBusy('daily_review')
    setQuickResult(null)
    try {
      const res = await apiFetchJson<GenerateMessageResponse>('/api/pearl/daily-review', { method: 'POST' })
      if ((res as any)?.generated) {
        setQuickResult({ type: 'ok', message: 'Daily review generated.' })
      } else {
        const reason = (res as any)?.reason || 'No review generated.'
        if (isDropdown) {
          setDropdownTab('chat')
        } else {
          setChatOpen(true)
        }
        await sendChatText('Give me a concise end-of-day review: what went well, what to improve, and one rule for tomorrow.')
        setQuickResult({ type: 'ok', message: reason })
      }
    } catch (e) {
      setQuickResult({ type: 'error', message: e instanceof Error ? e.message : 'Daily review failed' })
    } finally {
      setQuickBusy(null)
    }
  }, [quickBusy, isDropdown, sendChatText, setChatOpen])

  const transparencyExpanded = isDropdown ? true : showTransparency
  const chatExpanded = isDropdown ? true : chatOpen

  return (
    <DataPanel
      title="Pearl AI"
      iconSrc="/pearl-emoji.png"
      className={`pearl-insights-panel${isDropdown ? ' pearl-insights-dropdown' : ''}`}
      padding={isDropdown ? 'compact' : 'default'}
      badge={!isDropdown && (hasShadowMode || metrics?.mode === 'shadow') ? 'SHADOW' : undefined}
      badgeColor="var(--color-warning)"
    >
      <div className={`pearl-insights${isDropdown ? ' pearl-insights-dropdown-body' : ''}`}>
        {isDropdown && (
          <div className="pearl-dropdown-top">
            <div className="pearl-dropdown-tabs" role="tablist" aria-label="Pearl AI">
              <button
                type="button"
                role="tab"
                aria-selected={dropdownTab === 'overview'}
                className={`pearl-dropdown-tab ${dropdownTab === 'overview' ? 'active' : ''}`}
                onClick={() => setDropdownTab('overview')}
              >
                Overview
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={dropdownTab === 'feed'}
                className={`pearl-dropdown-tab ${dropdownTab === 'feed' ? 'active' : ''}`}
                onClick={() => setDropdownTab('feed')}
              >
                Feed
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={dropdownTab === 'chat'}
                className={`pearl-dropdown-tab ${dropdownTab === 'chat' ? 'active' : ''}`}
                onClick={() => setDropdownTab('chat')}
              >
                Chat
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={dropdownTab === 'costs'}
                className={`pearl-dropdown-tab ${dropdownTab === 'costs' ? 'active' : ''}`}
                onClick={() => setDropdownTab('costs')}
              >
                Costs
              </button>
            </div>

            <div className="pearl-dropdown-headline">
              <div className="pearl-dropdown-headline-text">{dropdownHeadline}</div>
              <div className="pearl-dropdown-headline-meta">
                <span className={`pearl-heartbeat-dot ${heartbeatRecent ? 'on' : 'off'}`} />
                <span className={`pearl-dropdown-mode ${overallMode}`}>{overallMode.toUpperCase()}</span>
                <span className="pearl-dropdown-ago">{formatAgo(lastActivityTs)}</span>
              </div>

              {dropdownTab === 'overview' && (
                <div className="pearl-dropdown-cta">
                  <div className="pearl-dropdown-status-grid" aria-label="Status">
                    {statusPnL !== null && (
                      <div className={`pearl-status-pill pnl ${statusPnL >= 0 ? 'positive' : 'negative'}`}>
                        <span className="k">P&amp;L</span>
                        <span className="v">{statusPnL >= 0 ? '+' : ''}${statusPnL.toFixed(0)}</span>
                      </div>
                    )}
                    {(statusWins !== null || statusLosses !== null) && (
                      <div className="pearl-status-pill wl">
                        <span className="k">W/L</span>
                        <span className="v">
                          <span className="win">{statusWins ?? 0}</span>/<span className="loss">{statusLosses ?? 0}</span>
                        </span>
                      </div>
                    )}
                    {statusPos !== null && (
                      <div className="pearl-status-pill pos">
                        <span className="k">Pos</span>
                        <span className="v">{statusPos}</span>
                      </div>
                    )}
                    {statusRegime && (
                      <div className="pearl-status-pill regime">
                        <span className="k">Regime</span>
                        <span className="v">
                          {statusRegime.replace(/_/g, ' ')}
                          {statusAllowedDir ? ` • ${statusAllowedDir}` : ''}
                        </span>
                      </div>
                    )}
                    {decisionLabel && (
                      <div className="pearl-status-pill decision">
                        <span className="k">Last</span>
                        <span className="v">
                          {decisionLabel}
                          {decisionAgo ? ` • ${decisionAgo}` : ''}
                        </span>
                      </div>
                    )}
                    {statusDataFresh !== null && (
                      <div className={`pearl-status-pill data ${statusDataFresh ? 'ok' : 'stale'}`}>
                        <span className="k">Data</span>
                        <span className="v">{statusDataFresh ? 'Fresh' : 'Stale'}</span>
                      </div>
                    )}
                    {statusMarketOpen !== null && (
                      <div className={`pearl-status-pill market ${statusMarketOpen ? 'open' : 'closed'}`}>
                        <span className="k">Mkt</span>
                        <span className="v">{statusMarketOpen ? 'Open' : 'Closed'}</span>
                      </div>
                    )}
                  </div>

                  {activeSuggestion?.action && (
                    <div className="pearl-dropdown-action-line">
                      <span className="pearl-dropdown-action-k">Suggestion</span>
                      <span className="pearl-dropdown-action-v">{activeSuggestion.action}</span>
                    </div>
                  )}

                  {activeSuggestion ? (
                    <div className="pearl-dropdown-cta-buttons">
                      {(() => {
                        const sid = resolveSuggestionId()
                        const disabled = !operatorUnlocked || feedbackBusy || !sid
                        const title =
                          !operatorUnlocked ? 'Read-only (operator locked)' : !sid ? 'No suggestion id available' : undefined
                        return (
                          <>
                            <button
                              className="pearl-btn pearl-btn-accept"
                              onClick={() => void sendSuggestionFeedback('accept')}
                              disabled={disabled}
                              title={title}
                              type="button"
                            >
                              Accept
                            </button>
                            <button
                              className="pearl-btn pearl-btn-dismiss"
                              onClick={() => void sendSuggestionFeedback('dismiss')}
                              disabled={disabled}
                              title={title}
                              type="button"
                            >
                              Dismiss
                            </button>
                            <button
                              className="pearl-btn pearl-btn-neutral"
                              onClick={() => setDropdownTab('chat')}
                              type="button"
                            >
                              Ask
                            </button>
                          </>
                        )
                      })()}
                    </div>
                  ) : (
                    <div className="pearl-dropdown-tip">
                      Tap <strong>Chat</strong> to ask for a plan, or <strong>Feed</strong> for transparency.
                    </div>
                  )}

                  <div className="pearl-dropdown-latest">
                    <div className="pearl-dropdown-latest-header">
                      <span className="pearl-dropdown-latest-title">Latest</span>
                      <button
                        type="button"
                        className="pearl-dropdown-latest-link"
                        onClick={() => setDropdownTab('feed')}
                      >
                        Feed →
                      </button>
                    </div>

                    {pearlFeed.length > 0 ? (
                      <div className="pearl-dropdown-latest-list">
                        {pearlFeed
                          .slice(-2)
                          .reverse()
                          .map((m) => (
                            <div key={m.id} className={`pearl-dropdown-latest-item ${m.type || 'message'}`}>
                              <div className="pearl-dropdown-latest-meta">
                                <span className="pearl-dropdown-latest-type">{(m.type || 'message').toUpperCase()}</span>
                                <span className="pearl-dropdown-latest-ago">{formatAgo(m.timestamp)}</span>
                              </div>
                              <div className="pearl-dropdown-latest-text">{m.content}</div>
                            </div>
                          ))}
                      </div>
                    ) : (
                      <div className="pearl-dropdown-latest-empty">
                        No Pearl messages yet — you’ll see narration on trades, rejections, circuit breakers, or quiet
                        periods. Use <strong>Session plan</strong> or <strong>Quiet check</strong> to start.
                      </div>
                    )}
                  </div>

                  <div className="pearl-dropdown-metrics">
                    {!operatorUnlocked ? (
                      <div className="pearl-dropdown-metrics-muted">Unlock to run actions and view metrics.</div>
                    ) : metricsBusy ? (
                      <div className="pearl-dropdown-metrics-muted">Loading metrics…</div>
                    ) : metricsSummary ? (
                      <div className="pearl-dropdown-metrics-row">
                        <span className="pearl-metric-pill">p95 {Math.round(metricsSummary.p95_latency_ms)}ms</span>
                        <span className="pearl-metric-pill">cache {Math.round(metricsSummary.cache_hit_rate * 100)}%</span>
                        <span className="pearl-metric-pill">
                          cost ${typeof costSummary?.today_usd === 'number' ? costSummary.today_usd.toFixed(3) : '—'}
                        </span>
                        <button
                          type="button"
                          className="pearl-metric-refresh"
                          onClick={() => void refreshMetrics(true)}
                          disabled={metricsBusy || !chatAvailable}
                          title="Refresh metrics"
                        >
                          ↻
                        </button>
                      </div>
                    ) : metricsError ? (
                      <div className="pearl-dropdown-metrics-muted">Metrics: {metricsError}</div>
                    ) : (
                      <button
                        type="button"
                        className="pearl-btn pearl-btn-neutral"
                        onClick={() => void refreshMetrics(true)}
                        disabled={!chatAvailable}
                      >
                        Load metrics
                      </button>
                    )}
                  </div>

                  <div className="pearl-dropdown-quick-actions" role="group" aria-label="Quick actions">
                    <button
                      type="button"
                      className={`pearl-btn pearl-btn-neutral ${quickBusy === 'plan' ? 'busy' : ''}`}
                      onClick={() => void runQuickChat('plan', 'Create a session plan for the next 60 minutes: bias, key levels, triggers, invalidation, and risk rules. Use bullets.')}
                      disabled={!operatorUnlocked || !chatAvailable || chatBusy || Boolean(quickBusy)}
                      title={!operatorUnlocked ? 'Operator access required' : 'Create a trading session plan'}
                      aria-busy={quickBusy === 'plan'}
                    >
                      {quickBusy === 'plan' ? '…' : 'Session plan'}
                    </button>
                    <button
                      type="button"
                      className={`pearl-btn pearl-btn-neutral ${quickBusy === 'quiet' ? 'busy' : ''}`}
                      onClick={() => void runQuickChat('quiet', 'If signals are quiet, explain why and what I should watch next; include 3 concrete triggers and one rule to avoid overtrading.')}
                      disabled={!operatorUnlocked || !chatAvailable || chatBusy || Boolean(quickBusy)}
                      title={!operatorUnlocked ? 'Operator access required' : 'Check why signals are quiet'}
                      aria-busy={quickBusy === 'quiet'}
                    >
                      {quickBusy === 'quiet' ? '…' : 'Quiet check'}
                    </button>
                    <button
                      type="button"
                      className={`pearl-btn pearl-btn-neutral ${quickBusy === 'rejections' ? 'busy' : ''}`}
                      onClick={() => void runQuickChat('rejections', "Summarize today's signal rejections (top reasons) and what to adjust to reduce missed good setups.")}
                      disabled={!operatorUnlocked || !chatAvailable || chatBusy || Boolean(quickBusy)}
                      title={!operatorUnlocked ? 'Operator access required' : 'Review signal rejections'}
                      aria-busy={quickBusy === 'rejections'}
                    >
                      {quickBusy === 'rejections' ? '…' : 'Rejections'}
                    </button>
                    <button
                      type="button"
                      className={`pearl-btn pearl-btn-neutral ${quickBusy === 'insight' ? 'busy' : ''}`}
                      onClick={() => void triggerInsight()}
                      disabled={!operatorUnlocked || !chatAvailable || chatBusy || Boolean(quickBusy)}
                      title={!operatorUnlocked ? 'Operator access required' : 'Get a quick trading insight'}
                      aria-busy={quickBusy === 'insight'}
                    >
                      {quickBusy === 'insight' ? '…' : 'Insight'}
                    </button>
                    <button
                      type="button"
                      className={`pearl-btn pearl-btn-neutral ${quickBusy === 'daily_review' ? 'busy' : ''}`}
                      onClick={() => void triggerDailyReview()}
                      disabled={!operatorUnlocked || !chatAvailable || chatBusy || Boolean(quickBusy)}
                      title={!operatorUnlocked ? 'Operator access required' : 'Get end-of-day review'}
                      aria-busy={quickBusy === 'daily_review'}
                    >
                      {quickBusy === 'daily_review' ? '…' : 'Daily review'}
                    </button>
                  </div>

                  {quickResult && (
                    <div className={`pearl-dropdown-result ${quickResult.type}`}>
                      {quickResult.message}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        )}

        {/* AI Component Status Pills */}
        {(!isDropdown || dropdownTab === 'overview') && aiStatus && (
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
        {(!isDropdown || dropdownTab === 'overview') && hasShadowMode && (
          <div className="shadow-mode-banner">
            <span className="shadow-mode-icon">🦪</span>
            <span className="shadow-mode-text">
              <em>PEARL AI</em> is in <em>SHADOW</em> mode — observing trades but not affecting decisions.
            </span>
          </div>
        )}

        {/* Operator lock (public link is read-only by default) */}
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

        {/* Transparency / Heartbeat */}
        {(!isDropdown || dropdownTab === 'feed') && (pearlFeed.length > 0 || pearlAIHeartbeat || pearlAIDebug) && (
          <div className="pearl-transparency">
            <div className="transparency-header">
              <div className="transparency-left">
                <span className={`pearl-heartbeat-dot ${heartbeatRecent ? 'on' : 'off'}`} />
                <span className="transparency-title">Transparency</span>
                <span className="transparency-sub">{formatAgo(lastActivityTs)}</span>
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

        {/* LLM Chat (Pearl AI 3.0) */}
        {(!isDropdown || dropdownTab === 'chat') && (
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
                  {chatMessages.length === 0 ? (
                    <div className="pearl-chat-empty">
                      Ask about today&apos;s setup, why signals are quiet, or what to watch next.
                    </div>
                  ) : (
                    chatMessages.map((m, idx) => (
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
                    void sendChat()
                  }}
                  aria-label="Chat with Pearl AI"
                >
                  <input
                    className="pearl-chat-input"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    placeholder="Ask Pearl…"
                    disabled={chatBusy || !operatorUnlocked || !chatAvailable}
                    aria-label="Message input"
                    autoComplete="off"
                  />
                  <button
                    className="pearl-chat-send"
                    type="submit"
                    disabled={chatBusy || !chatInput.trim() || !operatorUnlocked || !chatAvailable}
                    aria-label={chatBusy ? 'Sending message' : 'Send message'}
                  >
                    {chatBusy ? '…' : 'Send'}
                  </button>
                  <button
                    className="pearl-chat-clear"
                    type="button"
                    onClick={() => setChatMessages([])}
                    disabled={chatBusy || chatMessages.length === 0}
                    aria-label="Clear chat history"
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
        )}

        {/* AI Cost Transparency Dashboard */}
        {dropdownTab === 'costs' && isDropdown && (
          <div className="pearl-costs-dashboard" role="region" aria-label="AI Cost Transparency">
            <div className="pearl-costs-header">
              <span className="pearl-costs-title">AI Cost Transparency</span>
              <button
                type="button"
                className={`pearl-metric-refresh ${metricsBusy ? 'spinning' : ''}`}
                onClick={() => void refreshMetrics(true)}
                disabled={metricsBusy || !chatAvailable || !operatorUnlocked}
                title="Refresh metrics"
                aria-label={metricsBusy ? 'Loading metrics' : 'Refresh metrics'}
              >
                ↻
              </button>
            </div>

            {!operatorUnlocked ? (
              <div className="pearl-costs-locked">
                <span className="lock-icon">🔒</span>
                <span>Unlock operator access to view cost data</span>
              </div>
            ) : metricsError ? (
              <div className="pearl-costs-error">{metricsError}</div>
            ) : metricsBusy && !metricsSummary ? (
              <div className="pearl-costs-loading">Loading cost data...</div>
            ) : metricsSummary && costSummary ? (
              <>
                {/* Cost Summary Cards */}
                <div className="pearl-costs-cards">
                  <div className="pearl-cost-card today">
                    <div className="cost-card-value">${costSummary.today_usd.toFixed(3)}</div>
                    <div className="cost-card-label">Today</div>
                    {costSummary.limit_usd && (
                      <div className="cost-card-limit">
                        {Math.round((costSummary.today_usd / costSummary.limit_usd) * 100)}% of ${costSummary.limit_usd} limit
                      </div>
                    )}
                  </div>
                  <div className="pearl-cost-card month">
                    <div className="cost-card-value">${costSummary.month_usd.toFixed(2)}</div>
                    <div className="cost-card-label">This Month</div>
                  </div>
                  <div className="pearl-cost-card tokens">
                    <div className="cost-card-value">{(metricsSummary.total_tokens / 1000).toFixed(1)}k</div>
                    <div className="cost-card-label">Tokens (24h)</div>
                  </div>
                  <div className="pearl-cost-card requests">
                    <div className="cost-card-value">{metricsSummary.total_requests}</div>
                    <div className="cost-card-label">Requests (24h)</div>
                  </div>
                </div>

                {/* Response Source Distribution */}
                <div className="pearl-costs-section">
                  <div className="pearl-costs-section-title">Response Sources (24h)</div>
                  <div className="pearl-source-bars">
                    {(() => {
                      const sources = sourceDist?.counts || {
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
                {metricsSummary.by_model && Object.keys(metricsSummary.by_model).length > 0 && (
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
                      {Object.entries(metricsSummary.by_model).map(([model, stats]) => {
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
                {metricsSummary.by_endpoint && Object.keys(metricsSummary.by_endpoint).length > 0 && (
                  <div className="pearl-costs-section">
                    <div className="pearl-costs-section-title">Endpoint Usage (24h)</div>
                    <div className="pearl-endpoint-grid">
                      {Object.entries(metricsSummary.by_endpoint).map(([endpoint, stats]) => (
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
                      <span className={`perf-value ${metricsSummary.cache_hit_rate > 0.3 ? 'good' : ''}`}>
                        {(metricsSummary.cache_hit_rate * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">Error Rate</span>
                      <span className={`perf-value ${metricsSummary.error_rate > 0.05 ? 'bad' : 'good'}`}>
                        {(metricsSummary.error_rate * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">Fallback Rate</span>
                      <span className="perf-value">
                        {(metricsSummary.fallback_rate * 100).toFixed(1)}%
                      </span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">p50 Latency</span>
                      <span className="perf-value">{Math.round(metricsSummary.p50_latency_ms || 0)}ms</span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">p95 Latency</span>
                      <span className="perf-value">{Math.round(metricsSummary.p95_latency_ms)}ms</span>
                    </div>
                    <div className="pearl-perf-item">
                      <span className="perf-label">p99 Latency</span>
                      <span className="perf-value">{Math.round(metricsSummary.p99_latency_ms || 0)}ms</span>
                    </div>
                  </div>
                </div>

                {/* Cost Optimization Tips */}
                <div className="pearl-costs-tips">
                  <div className="pearl-costs-tips-title">Cost Optimization</div>
                  <ul className="pearl-tips-list">
                    {metricsSummary.cache_hit_rate < 0.2 && (
                      <li className="tip">Low cache hit rate ({(metricsSummary.cache_hit_rate * 100).toFixed(0)}%). Similar queries could benefit from caching.</li>
                    )}
                    {sourceDist && sourceDist.counts.claude > (sourceDist.counts.local || 0) * 2 && (
                      <li className="tip">Heavy Claude usage. Consider routing simpler queries to local Ollama.</li>
                    )}
                    {metricsSummary.by_model?.['claude-sonnet-4-20250514']?.count > 50 && (
                      <li className="tip">High Sonnet usage. Route simple queries to Haiku for 3x savings.</li>
                    )}
                    {costSummary.limit_usd && costSummary.today_usd > costSummary.limit_usd * 0.5 && (
                      <li className="tip warning">Over 50% of daily budget used.</li>
                    )}
                    {metricsSummary.cache_hit_rate >= 0.3 && sourceDist && sourceDist.counts.local >= sourceDist.counts.claude && (
                      <li className="tip success">Good cost efficiency. Cache and local LLM handling most queries.</li>
                    )}
                  </ul>
                </div>

                {/* Last Updated */}
                {metricsAsOfMs && (
                  <div className="pearl-costs-footer">
                    Updated {formatAgo(new Date(metricsAsOfMs).toISOString())}
                  </div>
                )}
              </>
            ) : (
              <div className="pearl-costs-empty">
                <button
                  type="button"
                  className="pearl-btn pearl-btn-neutral"
                  onClick={() => void refreshMetrics(true)}
                  disabled={!chatAvailable || !operatorUnlocked}
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

        {/* Current Insight / Suggestion */}
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
        {!isDropdown && !activeSuggestion && (
          <div className="pearl-no-insight">
            <span className="no-insight-icon">✨</span>
            <span className="no-insight-text">Watching for opportunities...</span>
          </div>
        )}

        {/* Shadow Tracking Impact Summary (compact 2x2 grid) */}
        {(!isDropdown || dropdownTab === 'overview') && metrics && totalSuggestions > 0 && (
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
        {(!isDropdown || dropdownTab === 'overview') && (!metrics || totalSuggestions === 0) && !activeSuggestion && !aiStatus && (
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
