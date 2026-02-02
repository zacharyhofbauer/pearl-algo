'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { DataPanel } from './DataPanelsContainer'

interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  type?: 'narration' | 'insight' | 'alert' | 'coaching' | 'response'
  priority?: 'low' | 'normal' | 'high' | 'critical'
}

interface PearlChatPanelProps {
  apiUrl?: string
  wsUrl?: string
  onMessage?: (message: Message) => void
}

export default function PearlChatPanel({
  apiUrl = '/api/pearl',
  wsUrl,
  onMessage,
}: PearlChatPanelProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isConnected, setIsConnected] = useState(false)
  const [showChat, setShowChat] = useState(false)

  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const wsRef = useRef<WebSocket | null>(null)

  // Auto-scroll to bottom
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    scrollToBottom()
  }, [messages, scrollToBottom])

  // WebSocket connection for real-time feed
  useEffect(() => {
    if (!wsUrl) return

    const connect = () => {
      const ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        setIsConnected(true)
        console.log('Pearl AI WebSocket connected')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)

          if (data.type === 'chat_response') {
            // Response to chat message
            const msg: Message = {
              id: `pearl-${Date.now()}`,
              role: 'assistant',
              content: data.content,
              timestamp: new Date(data.timestamp),
              type: 'response',
            }
            setMessages((prev) => [...prev, msg])
            onMessage?.(msg)
          } else if (data.content) {
            // Feed message (narration, insight, etc.)
            const msg: Message = {
              id: data.id || `feed-${Date.now()}`,
              role: 'assistant',
              content: data.content,
              timestamp: new Date(data.timestamp),
              type: data.type || 'narration',
              priority: data.priority || 'normal',
            }
            setMessages((prev) => [...prev, msg])
            onMessage?.(msg)
          }
        } catch (e) {
          // Ping/pong
          if (event.data === 'ping') {
            ws.send('pong')
          }
        }
      }

      ws.onclose = () => {
        setIsConnected(false)
        console.log('Pearl AI WebSocket disconnected')
        // Reconnect after delay
        setTimeout(connect, 3000)
      }

      ws.onerror = (error) => {
        console.error('Pearl AI WebSocket error:', error)
      }

      wsRef.current = ws
    }

    connect()

    return () => {
      wsRef.current?.close()
    }
  }, [wsUrl, onMessage])

  // Send message
  const sendMessage = async () => {
    if (!input.trim() || isLoading) return

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput('')
    setIsLoading(true)

    try {
      // Try WebSocket first
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(`chat:${input.trim()}`)
      } else {
        // Fall back to HTTP
        const response = await fetch(`${apiUrl}/chat`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message: input.trim() }),
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
          onMessage?.(assistantMessage)
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

  // Handle keyboard
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  // Get message style based on type
  const getMessageClass = (msg: Message) => {
    const classes = ['pearl-message', `pearl-message-${msg.role}`]

    if (msg.type) {
      classes.push(`pearl-message-type-${msg.type}`)
    }

    if (msg.priority === 'high' || msg.priority === 'critical') {
      classes.push('pearl-message-priority')
    }

    return classes.join(' ')
  }

  // Get type icon
  const getTypeIcon = (type?: string) => {
    switch (type) {
      case 'narration':
        return '📊'
      case 'insight':
        return '💡'
      case 'alert':
        return '⚠️'
      case 'coaching':
        return '🎯'
      case 'response':
        return '💬'
      default:
        return '✨'
    }
  }

  // Collapsed view - just show recent message
  if (!showChat) {
    const lastPearlMessage = messages.filter((m) => m.role === 'assistant').slice(-1)[0]

    return (
      <div className="pearl-chat-collapsed" onClick={() => setShowChat(true)}>
        <div className="pearl-chat-collapsed-header">
          <span className="pearl-chat-icon">💬</span>
          <span className="pearl-chat-title">Pearl AI</span>
          <span className={`pearl-status-dot ${isConnected ? 'connected' : ''}`}></span>
          <span className="pearl-expand-icon">▼</span>
        </div>
        {lastPearlMessage && (
          <div className="pearl-chat-preview">
            <span className="preview-icon">{getTypeIcon(lastPearlMessage.type)}</span>
            <span className="preview-text">{lastPearlMessage.content.slice(0, 80)}...</span>
          </div>
        )}
      </div>
    )
  }

  return (
    <DataPanel title="Pearl AI" iconSrc="/pearl-emoji.png" className="pearl-chat-panel">
      <div className="pearl-chat">
        {/* Header with status */}
        <div className="pearl-chat-header">
          <span className={`connection-status ${isConnected ? 'connected' : ''}`}>
            {isConnected ? '● Connected' : '○ Connecting...'}
          </span>
          <button className="pearl-minimize-btn" onClick={() => setShowChat(false)}>
            ▲
          </button>
        </div>

        {/* Messages */}
        <div className="pearl-chat-messages">
          {messages.length === 0 ? (
            <div className="pearl-chat-empty">
              <span className="empty-icon">✨</span>
              <span className="empty-text">
                Ask me anything about your trades, performance, or strategy.
              </span>
              <div className="empty-suggestions">
                <button onClick={() => setInput("How am I doing today?")}>
                  How am I doing today?
                </button>
                <button onClick={() => setInput("Why did you skip that last signal?")}>
                  Why skip that signal?
                </button>
                <button onClick={() => setInput("What's my win rate this week?")}>
                  Win rate this week?
                </button>
              </div>
            </div>
          ) : (
            messages.map((msg) => (
              <div key={msg.id} className={getMessageClass(msg)}>
                {msg.role === 'assistant' && (
                  <span className="message-type-icon">{getTypeIcon(msg.type)}</span>
                )}
                <div className="message-content">
                  <span className="message-text">{msg.content}</span>
                  <span className="message-time">
                    {msg.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
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
    </DataPanel>
  )
}
