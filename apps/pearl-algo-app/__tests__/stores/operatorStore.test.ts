import { useOperatorStore } from '@/stores/operatorStore'

const SESSION_KEY = 'pearl_operator_unlocked_v2'

const sessionStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: (key: string) => store[key] ?? null,
    setItem: (key: string, value: string) => {
      store[key] = String(value)
    },
    removeItem: (key: string) => {
      delete store[key]
    },
    clear: () => {
      store = {}
    },
    get length() {
      return Object.keys(store).length
    },
    key: (i: number) => Object.keys(store)[i] ?? null,
  }
})()

Object.defineProperty(window, 'sessionStorage', { value: sessionStorageMock })

describe('operatorStore (session-only lock)', () => {
  beforeEach(() => {
    sessionStorageMock.clear()
    useOperatorStore.setState({
      passphrase: null,
      isUnlocked: false,
      unlockedUntil: null,
    })
  })

  describe('unlock', () => {
    it('stores the passphrase and flips isUnlocked', () => {
      useOperatorStore.getState().unlock('test-passphrase')

      const state = useOperatorStore.getState()
      expect(state.passphrase).toBe('test-passphrase')
      expect(state.isUnlocked).toBe(true)
    })

    it('persists the unlock flag to sessionStorage', () => {
      useOperatorStore.getState().unlock('test-passphrase')
      expect(sessionStorageMock.getItem(SESSION_KEY)).toBe('1')
    })

    it('accepts an empty passphrase (backend owns validation)', () => {
      useOperatorStore.getState().unlock('')

      const state = useOperatorStore.getState()
      expect(state.passphrase).toBe('')
      expect(state.isUnlocked).toBe(true)
    })

    it('replaces the previous passphrase on re-unlock', () => {
      useOperatorStore.getState().unlock('first')
      useOperatorStore.getState().unlock('second')

      expect(useOperatorStore.getState().passphrase).toBe('second')
    })

    it('leaves unlockedUntil null (no TTL in session-only mode)', () => {
      useOperatorStore.getState().unlock('test-passphrase')
      expect(useOperatorStore.getState().unlockedUntil).toBeNull()
    })
  })

  describe('lock', () => {
    it('clears passphrase and flips isUnlocked back to false', () => {
      useOperatorStore.getState().unlock('test-passphrase')
      useOperatorStore.getState().lock()

      const state = useOperatorStore.getState()
      expect(state.passphrase).toBeNull()
      expect(state.isUnlocked).toBe(false)
    })

    it('clears the sessionStorage flag', () => {
      useOperatorStore.getState().unlock('test-passphrase')
      expect(sessionStorageMock.getItem(SESSION_KEY)).toBe('1')

      useOperatorStore.getState().lock()
      expect(sessionStorageMock.getItem(SESSION_KEY)).toBeNull()
    })
  })

  describe('legacy extend/tick', () => {
    it('extend is a no-op and does not throw', () => {
      useOperatorStore.getState().unlock('test-passphrase')
      const before = useOperatorStore.getState()

      expect(() => useOperatorStore.getState().extend()).not.toThrow()

      const after = useOperatorStore.getState()
      expect(after.isUnlocked).toBe(before.isUnlocked)
      expect(after.passphrase).toBe(before.passphrase)
      expect(after.unlockedUntil).toBe(before.unlockedUntil)
    })

    it('tick is a no-op and does not auto-relock', () => {
      useOperatorStore.getState().unlock('test-passphrase')

      expect(() => useOperatorStore.getState().tick()).not.toThrow()
      expect(useOperatorStore.getState().isUnlocked).toBe(true)
    })
  })

  describe('storage edge cases', () => {
    it('ignores sessionStorage errors during unlock', () => {
      const setItemSpy = jest
        .spyOn(sessionStorageMock, 'setItem')
        .mockImplementationOnce(() => {
          throw new Error('quota exceeded')
        })

      expect(() => useOperatorStore.getState().unlock('test-passphrase')).not.toThrow()
      expect(useOperatorStore.getState().isUnlocked).toBe(true)

      setItemSpy.mockRestore()
    })

    it('ignores sessionStorage errors during lock', () => {
      useOperatorStore.getState().unlock('test-passphrase')
      const removeItemSpy = jest
        .spyOn(sessionStorageMock, 'removeItem')
        .mockImplementationOnce(() => {
          throw new Error('storage unavailable')
        })

      expect(() => useOperatorStore.getState().lock()).not.toThrow()
      expect(useOperatorStore.getState().isUnlocked).toBe(false)

      removeItemSpy.mockRestore()
    })
  })
})
