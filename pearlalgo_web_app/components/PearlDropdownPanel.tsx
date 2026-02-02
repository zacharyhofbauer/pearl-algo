'use client'

import React, { useRef, useEffect, useCallback, useState } from 'react'
import { InfoTooltip } from './ui'
import { usePearlStore, type PearlMessage, type PearlTab, type TradingContext } from '@/stores'
import type { PearlInsights, PearlSuggestion, AIStatus, ShadowCounters, MLFilterPerformance } from '@/stores'

interface PearlDropdownPanelProps {
  insights: PearlInsights | null
  suggestion: PearlSuggestion | null
  aiStatus?: AIStatus | null
  shadowCounters?: ShadowCounters | null
  mlFilterPerformance?: MLFilterPerformance | null
  onAccept?: () => void
  onDismiss?: () => void
  // Optional overrides for embedded use
  showTabs?: boolean
  className?: string
  // Disable auto-scroll for in-page panels to prevent page scroll on load
  disableAutoScroll?: boolean
}

type Mode = 'off' | 'shadow' | 'live'

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

// Helper function to get icon for suggestion type
function getTypeIcon(type: string): string {
  const icons: Record<string, string> = {
    risk_alert: '\u26A0\uFE0F',
    pattern_insight: '\uD83D\uDCCA',
    direction_bias: '\u2197\uFE0F',
    size_reduction: '\uD83D\uDCC9',
    pause_trading: '\u23F8\uFE0F',
    opportunity: '\uD83C\uDFAF',
    session_advice: '\uD83D\uDD50',
  }
  return icons[type] || '\uD83D\uDCA1'
}

function getChatTypeIcon(type?: string) {
  switch (type) {
    case 'narration': return '\uD83D\uDCCA'
    case 'insight': return '\uD83D\uDCA1'
    case 'alert': return '\u26A0\uFE0F'
    case 'coaching': return '\uD83C\uDFAF'
    case 'response': return '\uD83D\uDCAC'
    default: return '\u2728'
  }
}

export default function PearlDropdownPanel({
  insights,
  suggestion,
  aiStatus,
  shadowCounters,
  mlFilterPerformance,
  onAccept,
  onDismiss,
  showTabs = true,
  className = '',
  disableAutoScroll = false,
}: PearlDropdownPanelProps) {
  // Use shared store
  const {
    messages,
    isConnected,
    activeTab,
    tradingContext,
    inputValue,
    isLoading,
    showContext,
    setActiveTab,
    setInputValue,
    setIsLoading,
    setShowContext,
    addMessage,
    updateMessage,
  } = usePearlStore()

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const prevMessageCountRef = useRef<number>(0)
  const hasMountedRef = useRef<boolean>(false)

  // Local UI state for history/details
  const [showHistory, setShowHistory] = useState(false)
  const [showDetails, setShowDetails] = useState(false)

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

  // Auto-scroll chat to bottom - use block: 'nearest' to prevent page scroll
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [])

  // Only scroll on new messages after initial mount, not on page load
  // Skip entirely if disableAutoScroll is true (for in-page panels)
  useEffect(() => {
    if (disableAutoScroll) return

    if (!hasMountedRef.current) {
      hasMountedRef.current = true
      prevMessageCountRef.current = messages.length
      return
    }

    // Only scroll if there are new messages and chat tab is active
    if (activeTab === 'chat' && messages.length > prevMessageCountRef.current) {
      scrollToBottom()
    }
    prevMessageCountRef.current = messages.length
  }, [messages, activeTab, scrollToBottom, disableAutoScroll])

  // Count unread messages
  const unreadCount = messages.filter(m => m.role === 'assistant').length

  // Send chat message with streaming support
  const sendMessage = async () => {
    if (!inputValue.trim() || isLoading) return

    const userMessage: PearlMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: inputValue.trim(),
      timestamp: new Date(),
    }

    addMessage(userMessage)
    const messageText = inputValue.trim()
    setInputValue('')
    setIsLoading(true)

    const streamingMessageId = `pearl-${Date.now()}`

    try {
      // Try streaming first
      const streamResponse = await fetch('/api/pearl/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: messageText }),
      })

      if (streamResponse.ok && streamResponse.body) {
        // Create streaming message placeholder
        const streamingMessage: PearlMessage = {
          id: streamingMessageId,
          role: 'assistant',
          content: '',
          timestamp: new Date(),
          type: 'response',
          isStreaming: true,
        }
        addMessage(streamingMessage)

        // Read the stream
        const reader = streamResponse.body.getReader()
        const decoder = new TextDecoder()
        let fullContent = ''

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunk = decoder.decode(value)
          const lines = chunk.split('\n')

          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.type === 'chunk' && data.content) {
                  fullContent += data.content
                  updateMessage(streamingMessageId, { content: fullContent })
                } else if (data.type === 'done') {
                  updateMessage(streamingMessageId, { isStreaming: false })
                } else if (data.type === 'error') {
                  console.error('Stream error:', data.message)
                }
              } catch {
                // Ignore parsing errors for incomplete chunks
              }
            }
          }
        }
      } else if (wsRef.current?.readyState === WebSocket.OPEN) {
        // Fallback to WebSocket
        wsRef.current.send(`chat:${messageText}`)
      } else {
        // Fallback to regular HTTP
        const response = await fetch('/api/pearl/chat', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: messageText }),
        })

        if (response.ok) {
          const data = await response.json()
          const assistantMessage: PearlMessage = {
            id: streamingMessageId,
            role: 'assistant',
            content: data.response,
            timestamp: new Date(data.timestamp),
            type: 'response',
          }
          addMessage(assistantMessage)
        }
      }
    } catch (error) {
      console.error('Failed to send message:', error)
      const errorMessage: PearlMessage = {
        id: `error-${Date.now()}`,
        role: 'system',
        content: 'Failed to connect to Pearl AI. Please try again.',
        timestamp: new Date(),
      }
      addMessage(errorMessage)
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

  const getMessageClass = (msg: PearlMessage) => {
    const classes = ['pearl-msg', `pearl-msg-${msg.role}`]
    if (msg.type) classes.push(`pearl-msg-type-${msg.type}`)
    if (msg.priority === 'high' || msg.priority === 'critical') classes.push('pearl-msg-priority')
    if (msg.isStreaming) classes.push('pearl-msg-streaming')
    return classes.join(' ')
  }

  return (
    <div className={`pearl-dropdown-panel ${className}`}>
      {/* Tab Navigation */}
      {showTabs && (
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
      )}

      {/* Status Tab Content */}
      {activeTab === 'status' && (
        <div className="pearl-status-content">
          {/* AI Component Status Pills */}
          {aiStatus ? (
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
                    {aiStatus.ml_filter.lift.lift_ok ? '\u2713' : '\u2014'}
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
          ) : (
            <div className="pearl-ai-status">
              <div className="ai-pills">
                <ModePill label="Bandit" mode="off" />
                <ModePill label="Contextual" mode="off" />
                <ModePill label="ML" mode="off" />
              </div>
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
                      : '\u2014'}
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
                      : '\u2014'}
                  </span>
                  <span className="ml-bar-count">{mlFilterPerformance.trades_blocked}</span>
                </div>
              </div>
              {mlFilterPerformance.lift_ok ? (
                <div className="ml-value-status positive">
                  <span className="status-icon">\u2713</span>
                  <span className="status-text">ML filter adding value</span>
                </div>
              ) : (
                <div className="ml-value-status neutral">
                  <span className="status-icon">\u2014</span>
                  <span className="status-text">Collecting data...</span>
                </div>
              )}
            </div>
          )}

          {/* Current Insight / Suggestion */}
          {activeSuggestion && (
            <div className="pearl-current-insight">
              <div className="insight-header">
                <span className="insight-icon">\uD83D\uDCA1</span>
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

          {/* No Active Suggestion State - only show if we have some data */}
          {!activeSuggestion && (aiStatus || (metrics && totalSuggestions > 0)) && (
            <div className="pearl-no-insight">
              <span className="no-insight-icon">{'\u2728'}</span>
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
                  {showDetails ? '\u2212' : '+'}
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
                    <span className="stat">\u2713 {suggestionsFollowed} followed</span>
                    <span className="stat">\u2717 {suggestionsDismissed} dismissed</span>
                    <span className="stat">\u23F1 {metrics.suggestions_expired} expired</span>
                  </div>

                  {metrics.recent_suggestions && metrics.recent_suggestions.length > 0 && (
                    <button
                      className="history-toggle-btn"
                      onClick={() => setShowHistory(!showHistory)}
                    >
                      {showHistory ? 'Hide History \u25B2' : 'Show History \u25BC'}
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
          {(!metrics || totalSuggestions === 0) && !activeSuggestion && (
            <div className="pearl-empty-state">
              <div className="empty-icon">{'\uD83D\uDD2E'}</div>
              <div className="empty-title">Pearl AI Active</div>
              <div className="empty-text">Watching your trading session...</div>
            </div>
          )}
        </div>
      )}

      {/* Chat Tab Content */}
      {activeTab === 'chat' && (
        <div className="pearl-chat-content">
          {/* State Context Panel - Collapsible */}
          {tradingContext && (
            <div className="pearl-chat-context">
              <button
                className="context-toggle"
                onClick={() => setShowContext(!showContext)}
              >
                <span className="context-summary">
                  <span className={`context-pnl ${(tradingContext.daily_pnl || 0) >= 0 ? 'positive' : 'negative'}`}>
                    ${(tradingContext.daily_pnl || 0).toFixed(0)}
                  </span>
                  <span className="context-divider">|</span>
                  <span className="context-wl">
                    {tradingContext.win_count}W/{tradingContext.loss_count}L
                  </span>
                  {tradingContext.active_positions > 0 && (
                    <>
                      <span className="context-divider">|</span>
                      <span className="context-active">{tradingContext.position_info || 'Active'}</span>
                    </>
                  )}
                </span>
                <span className="toggle-icon">{showContext ? '\u25B2' : '\u25BC'}</span>
              </button>

              {showContext && (
                <div className="context-details">
                  <div className="context-row">
                    <span className="context-label">Regime</span>
                    <span className="context-value">{tradingContext.market_regime || 'Unknown'}</span>
                  </div>
                  <div className="context-row">
                    <span className="context-label">Last Signal</span>
                    <span className="context-value">{tradingContext.last_signal_time || 'None'}</span>
                  </div>
                  <div className="context-row">
                    <span className="context-label">Win Rate</span>
                    <span className="context-value">{tradingContext.win_rate.toFixed(0)}%</span>
                  </div>
                  {tradingContext.consecutive_losses >= 2 && (
                    <div className="context-row context-warning">
                      <span className="context-label">Streak</span>
                      <span className="context-value">{tradingContext.consecutive_losses} losses</span>
                    </div>
                  )}
                  {tradingContext.consecutive_wins >= 3 && (
                    <div className="context-row context-positive">
                      <span className="context-label">Streak</span>
                      <span className="context-value">{tradingContext.consecutive_wins} wins</span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="pearl-chat-messages">
            {messages.length === 0 ? (
              <div className="pearl-chat-empty">
                <span className="empty-icon">\u2728</span>
                <span className="empty-text">
                  Ask me anything about your trades, performance, or strategy.
                </span>
                <div className="empty-suggestions">
                  <button onClick={() => setInputValue("How am I doing today?")}>
                    How am I doing?
                  </button>
                  <button onClick={() => setInputValue("Why did you skip that signal?")}>
                    Why skip signal?
                  </button>
                  <button onClick={() => setInputValue("What's my win rate?")}>
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
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask Pearl..."
              disabled={isLoading}
            />
            <button
              onClick={sendMessage}
              disabled={!inputValue.trim() || isLoading}
              className={isLoading ? 'loading' : ''}
            >
              {isLoading ? '...' : '\u2192'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
