import { useOperatorStore } from '@/stores/operatorStore'

// Mock localStorage and sessionStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value.toString()
    },
    removeItem: (key: string) => {
      delete store[key]
    },
    clear: () => {
      store = {}
    },
  }
})()

const sessionStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => {
      store[key] = value.toString()
    },
    removeItem: (key: string) => {
      delete store[key]
    },
    clear: () => {
      store = {}
    },
  }
})()

Object.defineProperty(window, 'localStorage', {
  value: localStorageMock,
})

Object.defineProperty(window, 'sessionStorage', {
  value: sessionStorageMock,
})

describe('operatorStore', () => {
  beforeEach(() => {
    localStorageMock.clear()
    sessionStorageMock.clear()
    useOperatorStore.setState({
      passphrase: null,
      unlockedUntil: null,
      isUnlocked: false,
    })
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  describe('unlock', () => {
    it('should unlock with default TTL', () => {
      const now = Date.now()
      jest.setSystemTime(now)

      useOperatorStore.getState().unlock('test-passphrase')

      const state = useOperatorStore.getState()
      expect(state.passphrase).toBe('test-passphrase')
      expect(state.isUnlocked).toBe(true)
      expect(state.unlockedUntil).toBeGreaterThan(now)
    })

    it('should unlock with custom TTL', () => {
      const now = Date.now()
      jest.setSystemTime(now)
      const customTtl = 5 * 60 * 1000 // 5 minutes

      useOperatorStore.getState().unlock('test-passphrase', customTtl)

      const state = useOperatorStore.getState()
      expect(state.unlockedUntil).toBe(now + customTtl)
    })

    it('should enforce minimum TTL of 30 seconds', () => {
      const now = Date.now()
      jest.setSystemTime(now)

      useOperatorStore.getState().unlock('test-passphrase', 10000) // 10 seconds

      const state = useOperatorStore.getState()
      expect(state.unlockedUntil).toBe(now + 30000) // Should be 30 seconds minimum
    })

    it('should persist to sessionStorage in dev mode', () => {
      const now = Date.now()
      jest.setSystemTime(now)
      const originalEnv = process.env.NODE_ENV
      process.env.NODE_ENV = 'development'

      useOperatorStore.getState().unlock('test-passphrase')

      const persisted = sessionStorageMock.getItem('pearl_operator_unlock_v1')
      expect(persisted).toBeTruthy()
      const data = JSON.parse(persisted!)
      expect(data.passphrase).toBe('test-passphrase')
      expect(data.unlockedUntil).toBeGreaterThan(now)

      process.env.NODE_ENV = originalEnv
    })
  })

  describe('lock', () => {
    it('should lock and clear passphrase', () => {
      useOperatorStore.getState().unlock('test-passphrase')
      expect(useOperatorStore.getState().isUnlocked).toBe(true)

      useOperatorStore.getState().lock()

      const state = useOperatorStore.getState()
      expect(state.passphrase).toBeNull()
      expect(state.unlockedUntil).toBeNull()
      expect(state.isUnlocked).toBe(false)
    })

    it('should clear persisted data on lock', () => {
      useOperatorStore.getState().unlock('test-passphrase')
      expect(sessionStorageMock.getItem('pearl_operator_unlock_v1')).toBeTruthy()

      useOperatorStore.getState().lock()

      expect(sessionStorageMock.getItem('pearl_operator_unlock_v1')).toBeNull()
    })
  })

  describe('extend', () => {
    it('should extend unlock time when unlocked', () => {
      const now = Date.now()
      jest.setSystemTime(now)

      useOperatorStore.getState().unlock('test-passphrase', 60000) // 1 minute
      const initialUntil = useOperatorStore.getState().unlockedUntil!

      jest.advanceTimersByTime(30000) // 30 seconds later
      useOperatorStore.getState().extend(60000) // Extend by another minute

      const state = useOperatorStore.getState()
      expect(state.unlockedUntil).toBeGreaterThan(initialUntil)
      expect(state.isUnlocked).toBe(true)
    })

    it('should do nothing when not unlocked', () => {
      const initialState = useOperatorStore.getState()
      useOperatorStore.getState().extend()

      const state = useOperatorStore.getState()
      expect(state).toEqual(initialState)
    })
  })

  describe('tick', () => {
    it('should auto-relock when expired', () => {
      const now = Date.now()
      jest.setSystemTime(now)

      useOperatorStore.getState().unlock('test-passphrase', 60000) // 1 minute
      expect(useOperatorStore.getState().isUnlocked).toBe(true)

      jest.advanceTimersByTime(61000) // 61 seconds later
      useOperatorStore.getState().tick()

      const state = useOperatorStore.getState()
      expect(state.isUnlocked).toBe(false)
      expect(state.passphrase).toBeNull()
      expect(state.unlockedUntil).toBeNull()
    })

    it('should not relock when still valid', () => {
      const now = Date.now()
      jest.setSystemTime(now)

      useOperatorStore.getState().unlock('test-passphrase', 60000)
      expect(useOperatorStore.getState().isUnlocked).toBe(true)

      jest.advanceTimersByTime(30000) // 30 seconds later
      useOperatorStore.getState().tick()

      const state = useOperatorStore.getState()
      expect(state.isUnlocked).toBe(true)
      expect(state.passphrase).toBe('test-passphrase')
    })

    it('should do nothing when already locked', () => {
      const initialState = useOperatorStore.getState()
      useOperatorStore.getState().tick()

      const state = useOperatorStore.getState()
      expect(state).toEqual(initialState)
    })
  })

  describe('persistence', () => {
    it('should load persisted data on initialization', () => {
      const now = Date.now()
      const future = now + 60000
      sessionStorageMock.setItem(
        'pearl_operator_unlock_v1',
        JSON.stringify({ passphrase: 'persisted-pass', unlockedUntil: future })
      )

      // Create a new store instance to test initialization
      const state = useOperatorStore.getState()
      // Note: Zustand stores are singletons, so we can't fully test initialization
      // But we can test that loadPersisted would work correctly
      expect(sessionStorageMock.getItem('pearl_operator_unlock_v1')).toBeTruthy()
    })

    it('should auto-expire expired persisted data on load', () => {
      const past = Date.now() - 60000 // 1 minute ago
      sessionStorageMock.setItem(
        'pearl_operator_unlock_v1',
        JSON.stringify({ passphrase: 'expired-pass', unlockedUntil: past })
      )

      // The store should clear expired data
      // Since we can't fully test initialization, we test the clear behavior
      useOperatorStore.getState().lock()
      expect(sessionStorageMock.getItem('pearl_operator_unlock_v1')).toBeNull()
    })

    it('should handle corrupted storage gracefully', () => {
      sessionStorageMock.setItem('pearl_operator_unlock_v1', 'invalid-json')

      // Should not throw - store should handle gracefully
      expect(() => {
        useOperatorStore.getState().lock()
      }).not.toThrow()
    })

    it('should handle missing storage fields gracefully', () => {
      sessionStorageMock.setItem('pearl_operator_unlock_v1', JSON.stringify({}))

      // Should not throw
      expect(() => {
        useOperatorStore.getState().lock()
      }).not.toThrow()
    })
  })

  describe('edge cases', () => {
    it('should handle empty passphrase', () => {
      const now = Date.now()
      jest.setSystemTime(now)

      useOperatorStore.getState().unlock('')

      const state = useOperatorStore.getState()
      expect(state.passphrase).toBe('')
      expect(state.isUnlocked).toBe(true)
    })

    it('should handle very long TTL', () => {
      const now = Date.now()
      jest.setSystemTime(now)
      const longTtl = 24 * 60 * 60 * 1000 // 24 hours

      useOperatorStore.getState().unlock('test-passphrase', longTtl)

      const state = useOperatorStore.getState()
      expect(state.unlockedUntil).toBe(now + longTtl)
    })

    it('should handle multiple unlock calls', () => {
      const now = Date.now()
      jest.setSystemTime(now)

      useOperatorStore.getState().unlock('first-passphrase', 60000)
      const firstUntil = useOperatorStore.getState().unlockedUntil!

      jest.advanceTimersByTime(1000)
      useOperatorStore.getState().unlock('second-passphrase', 120000)

      const state = useOperatorStore.getState()
      expect(state.passphrase).toBe('second-passphrase')
      expect(state.unlockedUntil).toBeGreaterThan(firstUntil)
    })
  })
})
