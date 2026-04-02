import { create } from 'zustand'

// FIXED 2026-03-25: Session-only operator lock — unlocked once per page load (hard reload = locked).
// No TTL, no localStorage, no auto-expiry. Password validates against backend.
// 200 viewers can watch; only passphrase holder can act.

const SESSION_KEY = 'pearl_operator_unlocked_v2'

function isUnlockedInSession(): boolean {
  if (typeof window === 'undefined') return false
  try {
    return window.sessionStorage.getItem(SESSION_KEY) === '1'
  } catch {
    return false
  }
}

function setUnlockedInSession(val: boolean): void {
  try {
    if (val) window.sessionStorage.setItem(SESSION_KEY, '1')
    else window.sessionStorage.removeItem(SESSION_KEY)
  } catch {
    // ignore
  }
}

interface OperatorStore {
  passphrase: string | null
  isUnlocked: boolean
  unlock: (passphrase: string) => void
  lock: () => void
  // Legacy compat
  unlockedUntil: number | null
  extend: () => void
  tick: () => void
}

export const useOperatorStore = create<OperatorStore>(() => ({
  passphrase: null,
  isUnlocked: isUnlockedInSession(),
  unlockedUntil: null,

  unlock: (passphrase: string) => {
    setUnlockedInSession(true)
    useOperatorStore.setState({ passphrase, isUnlocked: true })
  },

  lock: () => {
    setUnlockedInSession(false)
    useOperatorStore.setState({ passphrase: null, isUnlocked: false })
  },

  // Legacy no-ops
  extend: () => {},
  tick: () => {},
}))
