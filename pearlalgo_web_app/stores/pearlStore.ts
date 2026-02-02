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

export type PearlTab = 'status' | 'chat'

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

  // Get latest message for header preview
  getLatestMessage: () => PearlMessage | null
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
        // Persist only user preferences, not chat history or connection state
        activeTab: state.activeTab,
        showContext: state.showContext,
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
