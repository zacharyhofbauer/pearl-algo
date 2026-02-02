import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

// Admin password - in production this should be an env variable
// For now using a simple password that can be changed
const ADMIN_PASSWORD = 'wake up, daddys home'

interface AdminState {
  isAuthenticated: boolean
  showAuthModal: boolean
  authCallback: (() => void) | null

  // Actions
  authenticate: (password: string) => boolean
  logout: () => void
  requireAuth: (callback: () => void) => void
  closeAuthModal: () => void
}

export const useAdminStore = create<AdminState>()(
  persist(
    (set, get) => ({
      isAuthenticated: false,
      showAuthModal: false,
      authCallback: null,

      authenticate: (password: string) => {
        const isValid = password === ADMIN_PASSWORD
        if (isValid) {
          set({ isAuthenticated: true, showAuthModal: false })
          // Execute pending callback if any
          const callback = get().authCallback
          if (callback) {
            callback()
            set({ authCallback: null })
          }
        }
        return isValid
      },

      logout: () => {
        set({ isAuthenticated: false })
      },

      requireAuth: (callback: () => void) => {
        if (get().isAuthenticated) {
          callback()
        } else {
          set({ showAuthModal: true, authCallback: callback })
        }
      },

      closeAuthModal: () => {
        set({ showAuthModal: false, authCallback: null })
      },
    }),
    {
      name: 'pearl-admin-auth',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({ isAuthenticated: state.isAuthenticated }),
    }
  )
)

// Selectors
export const selectIsAuthenticated = (state: AdminState) => state.isAuthenticated
export const selectShowAuthModal = (state: AdminState) => state.showAuthModal
