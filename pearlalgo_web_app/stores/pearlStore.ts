import { create } from 'zustand'
import { persist } from 'zustand/middleware'

// Message type for Pearl AI chat
export interface PearlMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: Date
  type?: 'narration' | 'insight' | 'alert' | 'coaching' | 'response'
  priority?: 'low' | 'normal' | 'high' | 'critical'
  isStreaming?: boolean
}

// Feedback reasons for dismissed suggestions (I3.1)
export type DismissFeedbackReason = 'not_relevant' | 'wrong_timing' | 'too_risky' | 'other'

export interface SuggestionFeedback {
  suggestion_id: string
  action: 'accept' | 'dismiss'
  dismiss_reason?: DismissFeedbackReason
  dismiss_comment?: string
  timestamp: Date
}

// Pearl AI settings/preferences (I3.2)
export interface PearlSettings {
  enableCoachingMessages: boolean
  showShadowImpact: boolean
  suggestionFrequency: 'low' | 'normal' | 'high'
}

// Trading context for context panel
export interface TradingContext {
  daily_pnl: number
  win_count: number
  loss_count: number
  trade_count: number
  win_rate: number
  active_positions: number
  position_info: string | null
  market_regime: string
  last_signal_time: string | null
  consecutive_wins: number
  consecutive_losses: number
}

export type PearlTab = 'status' | 'chat' | 'settings'

// Session ID for chat persistence (I3.3)
const generateSessionId = () => `pearl-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`

interface PearlStore {
  // Chat state
  messages: PearlMessage[]

  // Connection state
  isConnected: boolean

  // Header bar state
  isHeaderExpanded: boolean

  // Active tab
  activeTab: PearlTab

  // Trading context for context panel
  tradingContext: TradingContext | null

  // Input state (for syncing between header and panel)
  inputValue: string

  // Loading state
  isLoading: boolean

  // Context panel visibility
  showContext: boolean

  // Session ID for chat persistence (I3.3)
  sessionId: string

  // Feedback history (I3.1)
  feedbackHistory: SuggestionFeedback[]

  // Pearl settings/preferences (I3.2)
  settings: PearlSettings

  // Feedback modal state
  showFeedbackModal: boolean
  pendingDismissSuggestionId: string | null

  // Actions
  addMessage: (message: PearlMessage) => void
  updateMessage: (id: string, updates: Partial<PearlMessage>) => void
  clearMessages: () => void
  setIsConnected: (connected: boolean) => void
  toggleHeaderExpanded: () => void
  setHeaderExpanded: (expanded: boolean) => void
  setActiveTab: (tab: PearlTab) => void
  setTradingContext: (context: TradingContext | null) => void
  setInputValue: (value: string) => void
  setIsLoading: (loading: boolean) => void
  setShowContext: (show: boolean) => void

  // Feedback actions (I3.1)
  recordFeedback: (feedback: SuggestionFeedback) => void
  showDismissFeedback: (suggestionId: string) => void
  hideDismissFeedback: () => void

  // Settings actions (I3.2)
  updateSettings: (settings: Partial<PearlSettings>) => void

  // Get latest message for header preview
  getLatestMessage: () => PearlMessage | null
}

const defaultSettings: PearlSettings = {
  enableCoachingMessages: true,
  showShadowImpact: true,
  suggestionFrequency: 'normal',
}

export const usePearlStore = create<PearlStore>()(
  persist(
    (set, get) => ({
      // Initial state
      messages: [],
      isConnected: false,
      isHeaderExpanded: false,
      activeTab: 'status',
      tradingContext: null,
      inputValue: '',
      isLoading: false,
      showContext: false,
      sessionId: generateSessionId(),
      feedbackHistory: [],
      settings: defaultSettings,
      showFeedbackModal: false,
      pendingDismissSuggestionId: null,

      // Actions
      addMessage: (message) =>
        set((state) => ({
          messages: [...state.messages, message],
        })),

      updateMessage: (id, updates) =>
        set((state) => ({
          messages: state.messages.map((msg) =>
            msg.id === id ? { ...msg, ...updates } : msg
          ),
        })),

      clearMessages: () => set({ messages: [] }),

      setIsConnected: (isConnected) => set({ isConnected }),

      toggleHeaderExpanded: () =>
        set((state) => ({ isHeaderExpanded: !state.isHeaderExpanded })),

      setHeaderExpanded: (isHeaderExpanded) => set({ isHeaderExpanded }),

      setActiveTab: (activeTab) => set({ activeTab }),

      setTradingContext: (tradingContext) => set({ tradingContext }),

      setInputValue: (inputValue) => set({ inputValue }),

      setIsLoading: (isLoading) => set({ isLoading }),

      setShowContext: (showContext) => set({ showContext }),

      // Feedback actions (I3.1)
      recordFeedback: (feedback) => {
        // Store locally
        set((state) => ({
          feedbackHistory: [...state.feedbackHistory.slice(-99), feedback],
          showFeedbackModal: false,
          pendingDismissSuggestionId: null,
        }))

        // Send to backend API (fire and forget)
        fetch('/api/pearl/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            suggestion_id: feedback.suggestion_id,
            action: feedback.action,
            dismiss_reason: feedback.dismiss_reason,
            dismiss_comment: feedback.dismiss_comment,
          }),
        }).catch(() => {
          // Feedback send failed silently
        })
      },

      showDismissFeedback: (suggestionId) =>
        set({
          showFeedbackModal: true,
          pendingDismissSuggestionId: suggestionId,
        }),

      hideDismissFeedback: () =>
        set({
          showFeedbackModal: false,
          pendingDismissSuggestionId: null,
        }),

      // Settings actions (I3.2)
      updateSettings: (newSettings) =>
        set((state) => ({
          settings: { ...state.settings, ...newSettings },
        })),

      getLatestMessage: () => {
        const { messages } = get()
        if (messages.length === 0) return null
        // Return the most recent assistant message, or the most recent message
        const assistantMessages = messages.filter((m) => m.role === 'assistant')
        return assistantMessages.length > 0
          ? assistantMessages[assistantMessages.length - 1]
          : messages[messages.length - 1]
      },
    }),
    {
      name: 'pearl-store',
      partialize: (state) => ({
        // Persist user preferences and settings
        activeTab: state.activeTab,
        showContext: state.showContext,
        sessionId: state.sessionId,
        settings: state.settings,
        // Keep last 20 feedback entries for history
        feedbackHistory: state.feedbackHistory.slice(-20),
      }),
    }
  )
)

// Selectors
export const selectMessages = (state: PearlStore) => state.messages
export const selectIsConnected = (state: PearlStore) => state.isConnected
export const selectIsHeaderExpanded = (state: PearlStore) => state.isHeaderExpanded
export const selectActiveTab = (state: PearlStore) => state.activeTab
export const selectTradingContext = (state: PearlStore) => state.tradingContext
export const selectInputValue = (state: PearlStore) => state.inputValue
export const selectIsLoading = (state: PearlStore) => state.isLoading
export const selectShowContext = (state: PearlStore) => state.showContext
export const selectUnreadCount = (state: PearlStore) =>
  state.messages.filter((m) => m.role === 'assistant').length
export const selectSessionId = (state: PearlStore) => state.sessionId
export const selectFeedbackHistory = (state: PearlStore) => state.feedbackHistory
export const selectSettings = (state: PearlStore) => state.settings
export const selectShowFeedbackModal = (state: PearlStore) => state.showFeedbackModal
export const selectPendingDismissSuggestionId = (state: PearlStore) => state.pendingDismissSuggestionId
