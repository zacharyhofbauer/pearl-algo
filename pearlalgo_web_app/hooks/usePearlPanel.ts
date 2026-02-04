'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { apiFetch, apiFetchJson } from '@/lib/api'
import { useOperatorStore } from '@/stores'
import type { AgentState, PearlFeedMessage } from '@/stores'
import type {
  PearlPanelData,
  PearlMetrics,
  MetricsSummary,
  CostSummary,
  ResponseSourceDist,
  ChatMessage,
  PearlChatResponse,
} from '@/types/pearl'
import { createPearlPanelData } from '@/types/pearl'

// ============================================================================
// Chat Hook
// ============================================================================

interface UsePearlChatOptions {
  chatAvailable: boolean
  onChatOpen?: () => void
}

interface UsePearlChatReturn {
  messages: ChatMessage[]
  input: string
  setInput: (value: string) => void
  busy: boolean
  error: string | null
  sendMessage: (message?: string) => Promise<void>
  clearMessages: () => void
}

export function usePearlChat({ chatAvailable, onChatOpen }: UsePearlChatOptions): UsePearlChatReturn {
  const operatorUnlocked = useOperatorStore((s) => s.isUnlocked)
  
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  const sendMessage = useCallback(async (message?: string) => {
    const m = (message || input).trim()
    if (!m || busy) return
    
    if (!chatAvailable) {
      setError('LLM chat is disabled on this server.')
      return
    }
    if (!operatorUnlocked) {
      setError('Operator access required.')
      return
    }
    
    setError(null)
    setBusy(true)
    setInput('')
    
    // Add user message
    setMessages((prev) => [...prev, { role: 'user' as const, text: m }].slice(-12))
    
    try {
      const res = await apiFetchJson<PearlChatResponse>('/api/pearl/chat', {
        method: 'POST',
        body: JSON.stringify({ message: m }),
      })
      setMessages((prev) => [
        ...prev,
        { role: 'pearl' as const, text: res.response, meta: { complexity: res.complexity, source: res.source } },
      ].slice(-12))
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'Pearl AI request failed'
      setError(msg)
      setMessages((prev) => [...prev, { role: 'pearl' as const, text: `Error: ${msg}` }].slice(-12))
    } finally {
      setBusy(false)
    }
  }, [input, busy, chatAvailable, operatorUnlocked])
  
  const clearMessages = useCallback(() => {
    setMessages([])
  }, [])
  
  return { messages, input, setInput, busy, error, sendMessage, clearMessages }
}

// ============================================================================
// Metrics Hook
// ============================================================================

interface UsePearlMetricsOptions {
  chatAvailable: boolean
  autoRefresh?: boolean
  refreshInterval?: number
}

interface UsePearlMetricsReturn {
  metrics: PearlMetrics
  refresh: (force?: boolean) => Promise<void>
}

export function usePearlMetrics({ chatAvailable, autoRefresh = false, refreshInterval = 15000 }: UsePearlMetricsOptions): UsePearlMetricsReturn {
  const operatorUnlocked = useOperatorStore((s) => s.isUnlocked)
  
  const [summary, setSummary] = useState<MetricsSummary | null>(null)
  const [cost, setCost] = useState<CostSummary | null>(null)
  const [sources, setSources] = useState<ResponseSourceDist | null>(null)
  const [asOfMs, setAsOfMs] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  
  const refresh = useCallback(async (force: boolean = false) => {
    if (loading) return
    
    if (!chatAvailable) {
      setError('Pearl AI endpoints are disabled on this server.')
      return
    }
    if (!operatorUnlocked) {
      setError('Operator access required.')
      return
    }
    
    // Skip if recently refreshed (unless forced)
    if (!force && asOfMs && Date.now() - asOfMs < refreshInterval) {
      return
    }
    
    setLoading(true)
    setError(null)
    
    try {
      const [m, c, s] = await Promise.all([
        apiFetchJson<MetricsSummary>('/api/pearl/metrics?hours=24', { method: 'GET' }),
        apiFetchJson<CostSummary>('/api/pearl/metrics/cost', { method: 'GET' }),
        apiFetchJson<ResponseSourceDist>('/api/pearl/metrics/sources?hours=24', { method: 'GET' }).catch(() => null),
      ])
      setSummary(m)
      setCost(c)
      if (s) setSources(s)
      setAsOfMs(Date.now())
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Metrics fetch failed')
    } finally {
      setLoading(false)
    }
  }, [loading, chatAvailable, operatorUnlocked, asOfMs, refreshInterval])
  
  // Auto-refresh if enabled
  useEffect(() => {
    if (!autoRefresh || !operatorUnlocked || !chatAvailable) return
    
    const id = window.setInterval(() => {
      void refresh(false)
    }, refreshInterval)
    
    return () => window.clearInterval(id)
  }, [autoRefresh, operatorUnlocked, chatAvailable, refresh, refreshInterval])
  
  const metrics: PearlMetrics = useMemo(() => ({
    summary,
    cost,
    sources,
    asOfMs,
    loading,
    error,
  }), [summary, cost, sources, asOfMs, loading, error])
  
  return { metrics, refresh }
}

// ============================================================================
// Quick Actions Hook
// ============================================================================

type QuickActionId = 'plan' | 'quiet' | 'rejections' | 'insight' | 'daily_review'

interface QuickActionResult {
  type: 'ok' | 'error'
  message: string
}

interface UseQuickActionsOptions {
  chatAvailable: boolean
  sendChatMessage: (message: string) => Promise<void>
  onChatOpen?: () => void
}

interface UseQuickActionsReturn {
  busy: QuickActionId | null
  result: QuickActionResult | null
  runAction: (id: QuickActionId) => Promise<void>
  clearResult: () => void
}

const QUICK_ACTION_PROMPTS: Record<QuickActionId, string> = {
  plan: 'Create a session plan for the next 60 minutes: bias, key levels, triggers, invalidation, and risk rules. Use bullets.',
  quiet: 'If signals are quiet, explain why and what I should watch next; include 3 concrete triggers and one rule to avoid overtrading.',
  rejections: "Summarize today's signal rejections (top reasons) and what to adjust to reduce missed good setups.",
  insight: 'Give me ONE brief, actionable insight for this session based on current state.',
  daily_review: 'Give me a concise end-of-day review: what went well, what to improve, and one rule for tomorrow.',
}

export function useQuickActions({ chatAvailable, sendChatMessage, onChatOpen }: UseQuickActionsOptions): UseQuickActionsReturn {
  const operatorUnlocked = useOperatorStore((s) => s.isUnlocked)
  
  const [busy, setBusy] = useState<QuickActionId | null>(null)
  const [result, setResult] = useState<QuickActionResult | null>(null)
  
  const runAction = useCallback(async (id: QuickActionId) => {
    if (busy || !operatorUnlocked || !chatAvailable) return
    
    setBusy(id)
    setResult(null)
    onChatOpen?.()
    
    try {
      // For insight and daily_review, try the dedicated endpoints first
      if (id === 'insight' || id === 'daily_review') {
        const endpoint = id === 'insight' ? '/api/pearl/insight' : '/api/pearl/daily-review'
        try {
          const res = await apiFetchJson<{ generated: boolean; content?: string; reason?: string }>(endpoint, { method: 'POST' })
          if (res.generated) {
            setResult({ type: 'ok', message: `${id === 'insight' ? 'Insight' : 'Daily review'} generated.` })
            setBusy(null)
            return
          }
          // Fallback to chat if not generated
        } catch {
          // Fallback to chat
        }
      }
      
      // Use chat for all other actions or as fallback
      await sendChatMessage(QUICK_ACTION_PROMPTS[id])
      setResult({ type: 'ok', message: 'Response generated.' })
    } catch (e) {
      setResult({ type: 'error', message: e instanceof Error ? e.message : 'Action failed' })
    } finally {
      setBusy(null)
    }
  }, [busy, operatorUnlocked, chatAvailable, sendChatMessage, onChatOpen])
  
  const clearResult = useCallback(() => {
    setResult(null)
  }, [])
  
  return { busy, result, runAction, clearResult }
}

// ============================================================================
// Main Pearl Panel Hook
// ============================================================================

interface UsePearlPanelOptions {
  agentState: AgentState | null
  dropdownActive?: boolean
  initialTab?: 'overview' | 'feed' | 'chat' | 'costs'
}

interface UsePearlPanelReturn {
  // Unified panel data
  data: PearlPanelData
  // Time tracking
  nowMs: number
  formatAgo: (iso?: string | null) => string
  // Tabs
  activeTab: 'overview' | 'feed' | 'chat' | 'costs'
  setActiveTab: (tab: 'overview' | 'feed' | 'chat' | 'costs') => void
  // Chat
  chat: UsePearlChatReturn
  // Metrics
  metricsData: PearlMetrics
  refreshMetrics: (force?: boolean) => Promise<void>
  // Quick actions
  quickActions: UseQuickActionsReturn
  // Feed filtering
  feedQuery: string
  setFeedQuery: (query: string) => void
  feedType: 'all' | 'narration' | 'insight' | 'coaching' | 'alert' | 'response' | 'message'
  setFeedType: (type: 'all' | 'narration' | 'insight' | 'coaching' | 'alert' | 'response' | 'message') => void
  filteredFeed: PearlFeedMessage[]
}

export function usePearlPanel({ agentState, dropdownActive = false, initialTab = 'overview' }: UsePearlPanelOptions): UsePearlPanelReturn {
  // Time tracking
  const [nowMs, setNowMs] = useState(() => Date.now())
  
  useEffect(() => {
    const id = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(id)
  }, [])
  
  // Format time ago
  const formatAgo = useCallback((iso?: string | null): string => {
    if (!iso) return '—'
    const t = Date.parse(iso)
    if (!Number.isFinite(t)) return '—'
    const s = Math.max(0, Math.floor((nowMs - t) / 1000))
    if (s < 60) return `${s}s ago`
    const m = Math.floor(s / 60)
    if (m < 60) return `${m}m ago`
    const h = Math.floor(m / 60)
    if (h < 48) return `${h}h ago`
    const d = Math.floor(h / 24)
    return `${d}d ago`
  }, [nowMs])
  
  // Unified panel data
  const data = useMemo(() => createPearlPanelData(agentState, nowMs), [agentState, nowMs])
  
  // Tabs
  const [activeTab, setActiveTab] = useState<'overview' | 'feed' | 'chat' | 'costs'>(initialTab)
  
  // Chat
  const chat = usePearlChat({
    chatAvailable: data.status.chatAvailable,
    onChatOpen: () => setActiveTab('chat'),
  })
  
  // Metrics
  const { metrics: metricsData, refresh: refreshMetrics } = usePearlMetrics({
    chatAvailable: data.status.chatAvailable,
  })
  
  // Auto-refresh metrics when dropdown is active and on overview/costs tab
  useEffect(() => {
    if (!dropdownActive) return
    if (activeTab !== 'overview' && activeTab !== 'costs') return
    
    void refreshMetrics(false)
  }, [dropdownActive, activeTab, refreshMetrics])
  
  // Quick actions
  const quickActions = useQuickActions({
    chatAvailable: data.status.chatAvailable,
    sendChatMessage: chat.sendMessage,
    onChatOpen: () => setActiveTab('chat'),
  })
  
  // Feed filtering
  const [feedQuery, setFeedQuery] = useState('')
  const [feedType, setFeedType] = useState<'all' | 'narration' | 'insight' | 'coaching' | 'alert' | 'response' | 'message'>('all')
  
  const filteredFeed = useMemo(() => {
    const rows = [...(data.feed || [])].slice(-60).reverse()
    const q = feedQuery.trim().toLowerCase()
    
    return rows.filter((m) => {
      const mt = (m?.type || 'message').toLowerCase()
      if (feedType !== 'all' && mt !== feedType) return false
      
      if (!q) return true
      
      const details = (m as any)?.metadata?.details
      const detailsText = typeof details?.text === 'string' ? details.text : ''
      const detailsTitle = typeof details?.title === 'string' ? details.title : ''
      const detailsLines = Array.isArray(details?.lines) ? details.lines.join(' ') : ''
      
      const hay = `${m?.content || ''} ${m?.type || ''} ${m?.priority || ''} ${detailsTitle} ${detailsText} ${detailsLines}`.toLowerCase()
      return hay.includes(q)
    })
  }, [data.feed, feedQuery, feedType])
  
  return {
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
  }
}
