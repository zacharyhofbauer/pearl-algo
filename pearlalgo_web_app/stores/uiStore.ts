import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { WebSocketStatus } from '@/hooks/useWebSocket'

interface UIStore {
  // Connection state
  wsStatus: WebSocketStatus
  isLive: boolean
  lastUpdate: Date | null

  // UI preferences (persisted)
  theme: 'dark' | 'light'
  showHelp: boolean

  // Notifications
  notifications: Notification[]

  // Actions
  setWsStatus: (status: WebSocketStatus) => void
  setIsLive: (isLive: boolean) => void
  setLastUpdate: (date: Date) => void
  setTheme: (theme: 'dark' | 'light') => void
  toggleHelp: () => void
  addNotification: (notification: Omit<Notification, 'id' | 'timestamp'>) => void
  removeNotification: (id: string) => void
  clearNotifications: () => void
}

interface Notification {
  id: string
  type: 'info' | 'success' | 'warning' | 'error'
  title: string
  message?: string
  timestamp: Date
  duration?: number // Auto-dismiss after ms, 0 = persistent
}

export const useUIStore = create<UIStore>()(
  persist(
    (set) => ({
      // Initial state
      wsStatus: 'disconnected',
      isLive: false,
      lastUpdate: null,
      theme: 'dark',
      showHelp: false,
      notifications: [],

      // Actions
      setWsStatus: (wsStatus) => set({ wsStatus }),

      setIsLive: (isLive) => set({ isLive }),

      setLastUpdate: (lastUpdate) => set({ lastUpdate }),

      setTheme: (theme) => set({ theme }),

      toggleHelp: () => set((state) => ({ showHelp: !state.showHelp })),

      addNotification: (notification) =>
        set((state) => ({
          notifications: [
            ...state.notifications,
            {
              ...notification,
              id: `notif-${Date.now()}-${Math.random().toString(36).slice(2)}`,
              timestamp: new Date(),
            },
          ],
        })),

      removeNotification: (id) =>
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        })),

      clearNotifications: () => set({ notifications: [] }),
    }),
    {
      name: 'pearl-ui-store',
      partialize: (state) => ({
        theme: state.theme,
        showHelp: state.showHelp,
      }),
    }
  )
)

// Selectors
export const selectWsStatus = (state: UIStore) => state.wsStatus
export const selectIsConnected = (state: UIStore) => state.wsStatus === 'connected'
export const selectTheme = (state: UIStore) => state.theme
export const selectNotifications = (state: UIStore) => state.notifications
