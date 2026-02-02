'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { DataPanel } from './DataPanelsContainer'
import { InfoTooltip } from './ui'
import type { PearlInsights, PearlSuggestion, AIStatus, ShadowCounters, MLFilterPerformance } from '@/stores'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  type?: 'narration' | 'insight' | 'alert' | 'coaching' | 'response'
  priority?: 'low' | 'normal' | 'high' | 'critical'
}

interface PearlInsightsPanelProps {
  insights: PearlInsights | null
  suggestion: PearlSuggestion | null
  aiStatus?: AIStatus | null
  shadowCounters?: ShadowCounters | null
  mlFilterPerformance?: MLFilterPerformance | null
  onAccept?: () => void
  onDismiss?: () => void
}

type Mode = 'off' | 'shadow' | 'live'
type TabType = 'status' | 'chat'

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
  onAccept,
  onDismiss,
}: PearlInsightsPanelProps) {
  const [activeTab, setActiveTab] = useState<TabType>('status')
  const [showHistory, setShowHistory] = useState(false)
  const [showDetails, setShowDetails] = useState(false)

  // Chat state
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

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

  // Auto-scroll chat to bottom
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    if (activeTab === 'chat') {
      scrollToBottom()
    }
  }, [messages, activeTab, scrollToBottom])

  // WebSocket connection for real-time feed
  useEffect(() => {
    if (typeof window === 'undefined') return

    const wsUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/api/pearl/feed/ws`

    const connect = () => {
      try {
        const ws = new WebSocket(wsUrl)

        ws.onopen = () => {
          setIsConnected(true)
          console.log('Pearl AI WebSocket connected')
        }

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data)

            if (data.type === 'chat_response') {
              const msg: Message = {
                id: `pearl-${Date.now()}`,
                role: 'assistant',
                content: data.content,
                timestamp: new Date(data.timestamp),
                type: 'response',
              }
              setMessages((prev) => [...prev, msg])
            } else if (data.content) {
              const msg: Message = {
                id: data.id || `feed-${Date.now()}`,
                role: 'assistant',
                content: data.content,
                timestamp: new Date(data.timestamp),
                type: data.type || 'narration',
                priority: data.priority || 'normal',
              }
              setMessages((prev) => [...prev, msg])
            }
          } catch {
            if (event.data === 'ping') {
              ws.send('pong')
            }
          }
        }

        ws.onclose = () => {
          setIsConnected(false)
          console.log('Pearl AI WebSocket disconnected')
          setTimeout(connect, 3000)
        }

        ws.onerror = (error) => {
          console.error('Pearl AI WebSocket error:', error)
        }

        wsRef.current = ws
      } catch (e) {
        console.error('Failed to create WebSocket:', e)
      }
    }

    connect()

    return () => {
      wsRef.current?.close()
    }
  }, [])

  // Send chat message
  const sendMessage = async () => {
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    const messageText = input.trim()
    setInput('')
    setIsLoading(true)

    try {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(`chat:${messageText}`)
      } else {
        const response = await fetch('/api/pearl/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: messageText }),
        })

        if (response.ok) {
          const data = await response.json()
          const assistantMessage: Message = {
            id: `pearl-${Date.now()}`,
            role: 'assistant',
            content: data.response,
            timestamp: new Date(data.timestamp),
            type: 'response',
          }
          setMessages((prev) => [...prev, assistantMessage])
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error)
      const errorMessage: Message = {
        id: `error-${Date.now()}`,
        role: 'system',
        content: 'Failed to connect to Pearl AI. Please try again.',
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  const getMessageClass = (msg: Message) => {
    const classes = ['pearl-msg', `pearl-msg-${msg.role}`]
    if (msg.type) classes.push(`pearl-msg-type-${msg.type}`)
    if (msg.priority === 'high' || msg.priority === 'critical') classes.push('pearl-msg-priority')
    return classes.join(' ')
  }

  const getChatTypeIcon = (type?: string) => {
    switch (type) {
      case 'narration': return '📊'
      case 'insight': return '💡'
      case 'alert': return '⚠️'
      case 'coaching': return '🎯'
      case 'response': return '💬'
      default: return '✨'
    }
  }

  // Count unread messages
  const unreadCount = messages.filter(m => m.role === 'assistant').length

  return (
    <DataPanel
      title="Pearl AI"
      iconSrc="/pearl-emoji.png"
      className="pearl-insights-panel"
      badge={hasShadowMode || metrics?.mode === 'shadow' ? 'SHADOW' : undefined}
      badgeColor="var(--color-warning)"
    >
      <div className="pearl-insights">
        {/* Tab Navigation */}
        <div className="pearl-tabs">
          <button
            className={`pearl-tab ${activeTab === 'status' ? 'active' : ''}`}
            onClick={() => setActiveTab('status')}
          >
            Status
          </button>
          <button
            className={`pearl-tab ${activeTab === 'chat' ? 'active' : ''}`}
            onClick={() => setActiveTab('chat')}
          >
            Chat
            {unreadCount > 0 && activeTab !== 'chat' && (
              <span className="pearl-tab-badge">{unreadCount}</span>
            )}
            <span className={`pearl-ws-dot ${isConnected ? 'connected' : ''}`} />
          </button>
        </div>

        {/* Status Tab Content */}
        {activeTab === 'status' && (
          <div className="pearl-status-content">
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

            {/* ML Filter Performance - Win Rate Comparison */}
            {mlFilterPerformance && (mlFilterPerformance.win_rate_pass !== undefined || mlFilterPerformance.win_rate_fail !== undefined) && (
              <div className="ml-performance-section">
                <div className="ml-perf-header">
                  <span className="ml-perf-title">ML Filter Impact</span>
                  {mlFilterPerformance.lift_ok && (
                    <span className="ml-lift-badge positive">
                      +{((mlFilterPerformance.win_rate_pass || 0) - (mlFilterPerformance.win_rate_fail || 0)) * 100 > 0
                        ? ((mlFilterPerformance.win_rate_pass || 0) - (mlFilterPerformance.win_rate_fail || 0) * 100).toFixed(0)
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
                  <button className="pearl-btn pearl-btn-accept" onClick={onAccept}>
                    Accept
                  </button>
                  <button className="pearl-btn pearl-btn-dismiss" onClick={onDismiss}>
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

            {/* Shadow Tracking Impact Summary */}
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
            {(!metrics || totalSuggestions === 0) && !activeSuggestion && !aiStatus && (
              <div className="pearl-empty-state">
                <div className="empty-icon">🔮</div>
                <div className="empty-title">Shadow Mode Active</div>
                <div className="empty-text">Pearl is learning your patterns.</div>
              </div>
            )}
          </div>
        )}

        {/* Chat Tab Content */}
        {activeTab === 'chat' && (
          <div className="pearl-chat-content">
            <div className="pearl-chat-messages">
              {messages.length === 0 ? (
                <div className="pearl-chat-empty">
                  <span className="empty-icon">✨</span>
                  <span className="empty-text">
                    Ask me anything about your trades, performance, or strategy.
                  </span>
                  <div className="empty-suggestions">
                    <button onClick={() => setInput("How am I doing today?")}>
                      How am I doing?
                    </button>
                    <button onClick={() => setInput("Why did you skip that signal?")}>
                      Why skip signal?
                    </button>
                    <button onClick={() => setInput("What's my win rate?")}>
                      Win rate?
                    </button>
                  </div>
                </div>
              ) : (
                messages.map((msg) => (
                  <div key={msg.id} className={getMessageClass(msg)}>
                    {msg.role === 'assistant' && (
                      <span className="msg-type-icon">{getChatTypeIcon(msg.type)}</span>
                    )}
                    <div className="msg-content">
                      <span className="msg-text">{msg.content}</span>
                      <span className="msg-time">
                        {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                  </div>
                ))
              )}
              <div ref={messagesEndRef} />
            </div>

            <div className="pearl-chat-input">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask Pearl..."
                disabled={isLoading}
              />
              <button
                onClick={sendMessage}
                disabled={!input.trim() || isLoading}
                className={isLoading ? 'loading' : ''}
              >
                {isLoading ? '...' : '→'}
              </button>
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
