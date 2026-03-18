import { create } from 'zustand'

type PersistMode = 'off' | 'session' | 'local'

function parsePositiveInt(raw: string | undefined): number | null {
  if (typeof raw !== 'string' || !raw.trim()) return null
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? n : null
}

function getDefaultTtlMs(): number {
  const minutes = parsePositiveInt(process.env.NEXT_PUBLIC_OPERATOR_UNLOCK_TTL_MINUTES)
  if (minutes) return Math.max(30_000, minutes * 60_000)

  // Development convenience: keep you unlocked while editing without constant re-entry.
  if (process.env.NODE_ENV !== 'production') return 60 * 60 * 1000 // 60 minutes

  return 10 * 60 * 1000 // 10 minutes
}

function getPersistMode(): PersistMode {
  const raw = (process.env.NEXT_PUBLIC_OPERATOR_UNLOCK_PERSIST || '').toString().trim().toLowerCase()
  if (raw === 'off' || raw === 'session' || raw === 'local') return raw

  // Default: dev convenience (including tunneled dev URLs); prod stays strict-by-default.
  if (process.env.NODE_ENV !== 'production') return 'session'

  // Production fallback: only remember unlocks on localhost (if someone runs prod build locally).
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    if (host === 'localhost' || host === '127.0.0.1') return 'session'
  }
  return 'off'
}

const DEFAULT_TTL_MS = getDefaultTtlMs()
const PERSIST_KEY = 'pearl_operator_unlock_v1'

function getStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  const mode = getPersistMode()
  if (mode === 'off') return null
  return mode === 'local' ? window.localStorage : window.sessionStorage
}

function loadPersisted(): { passphrase: string; unlockedUntil: number } | null {
  const storage = getStorage()
  if (!storage) return null
  try {
    const raw = storage.getItem(PERSIST_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    const passphrase = typeof data?.passphrase === 'string' ? data.passphrase : ''
    const unlockedUntil = typeof data?.unlockedUntil === 'number' ? data.unlockedUntil : 0
    if (!passphrase || !Number.isFinite(unlockedUntil)) return null
    if (Date.now() > unlockedUntil) {
      try {
        storage.removeItem(PERSIST_KEY)
      } catch {
        // ignore
      }
      return null
    }
    return { passphrase, unlockedUntil }
  } catch {
    return null
  }
}

function savePersisted(passphrase: string, unlockedUntil: number): void {
  const storage = getStorage()
  if (!storage) return
  try {
    storage.setItem(PERSIST_KEY, JSON.stringify({ passphrase, unlockedUntil }))
  } catch {
    // ignore
  }
}

function clearPersisted(): void {
  const storage = getStorage()
  if (!storage) return
  try {
    storage.removeItem(PERSIST_KEY)
  } catch {
    // ignore
  }
}

interface OperatorStore {
  /**
   * Operator passphrase.
   *
   * Default behavior:
   * - In production: in-memory only
   * - On localhost (dev): remembered in sessionStorage so reloads/hot-reloads don't log you out
   *
   * Override with NEXT_PUBLIC_OPERATOR_UNLOCK_PERSIST=off|session|local.
   */
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
  ...(() => {
    const data = loadPersisted()
    if (!data) return { passphrase: null, unlockedUntil: null, isUnlocked: false }
    return { passphrase: data.passphrase, unlockedUntil: data.unlockedUntil, isUnlocked: true }
  })(),

  unlock: (passphrase, ttlMs = DEFAULT_TTL_MS) => {
    const ttl = Math.max(30_000, ttlMs) // minimum 30s
    const until = Date.now() + ttl
    set({ passphrase, unlockedUntil: until, isUnlocked: true })
    savePersisted(passphrase, until)
  },

  extend: (ttlMs = DEFAULT_TTL_MS) => {
    const { passphrase } = get()
    if (!passphrase) return
    const ttl = Math.max(30_000, ttlMs)
    const until = Date.now() + ttl
    set({ unlockedUntil: until, isUnlocked: true })
    savePersisted(passphrase, until)
  },

  lock: () => {
    clearPersisted()
    set({ passphrase: null, unlockedUntil: null, isUnlocked: false })
  },

  tick: () => {
    const { passphrase, unlockedUntil, isUnlocked } = get()
    if (!isUnlocked) return
    if (!passphrase || !unlockedUntil || Date.now() > unlockedUntil) {
      clearPersisted()
      set({ passphrase: null, unlockedUntil: null, isUnlocked: false })
    }
  },
}))

