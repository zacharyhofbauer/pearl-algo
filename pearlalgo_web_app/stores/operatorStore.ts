import { create } from 'zustand'

const DEFAULT_TTL_MS = 10 * 60 * 1000 // 10 minutes

interface OperatorStore {
  /** Operator passphrase kept in-memory only (never persisted). */
  passphrase: string | null
  /** Epoch ms when the unlock expires. */
  unlockedUntil: number | null
  /** Derived flag for UI convenience. */
  isUnlocked: boolean

  unlock: (passphrase: string, ttlMs?: number) => void
  extend: (ttlMs?: number) => void
  lock: () => void
  tick: () => void
}

export const useOperatorStore = create<OperatorStore>((set, get) => ({
  passphrase: null,
  unlockedUntil: null,
  isUnlocked: false,

  unlock: (passphrase, ttlMs = DEFAULT_TTL_MS) => {
    const ttl = Math.max(30_000, ttlMs) // minimum 30s
    const until = Date.now() + ttl
    set({ passphrase, unlockedUntil: until, isUnlocked: true })
  },

  extend: (ttlMs = DEFAULT_TTL_MS) => {
    const { passphrase } = get()
    if (!passphrase) return
    const ttl = Math.max(30_000, ttlMs)
    const until = Date.now() + ttl
    set({ unlockedUntil: until, isUnlocked: true })
  },

  lock: () => set({ passphrase: null, unlockedUntil: null, isUnlocked: false }),

  tick: () => {
    const { passphrase, unlockedUntil, isUnlocked } = get()
    if (!isUnlocked) return
    if (!passphrase || !unlockedUntil || Date.now() > unlockedUntil) {
      set({ passphrase: null, unlockedUntil: null, isUnlocked: false })
    }
  },
}))

