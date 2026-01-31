import { useAgentStore } from '@/stores/agentStore'
import { act } from '@testing-library/react'

describe('agentStore', () => {
  beforeEach(() => {
    // Reset store before each test
    useAgentStore.setState({
      agentState: null,
      lastUpdated: null,
      isLoading: true,
      error: null,
    })
  })

  describe('initial state', () => {
    it('should have null agentState initially', () => {
      const state = useAgentStore.getState()
      expect(state.agentState).toBeNull()
    })

    it('should be loading initially', () => {
      const state = useAgentStore.getState()
      expect(state.isLoading).toBe(true)
    })

    it('should have no error initially', () => {
      const state = useAgentStore.getState()
      expect(state.error).toBeNull()
    })
  })

  describe('setAgentState', () => {
    it('should set agent state with partial data', () => {
      act(() => {
        useAgentStore.getState().setAgentState({
          running: true,
          daily_pnl: 150.50,
        })
      })

      const state = useAgentStore.getState()
      expect(state.agentState?.running).toBe(true)
      expect(state.agentState?.daily_pnl).toBe(150.50)
      expect(state.isLoading).toBe(false)
    })

    it('should merge with existing state', () => {
      act(() => {
        useAgentStore.getState().setAgentState({
          running: true,
          daily_pnl: 100,
        })
      })

      act(() => {
        useAgentStore.getState().setAgentState({
          daily_wins: 5,
        })
      })

      const state = useAgentStore.getState()
      expect(state.agentState?.running).toBe(true)
      expect(state.agentState?.daily_pnl).toBe(100)
      expect(state.agentState?.daily_wins).toBe(5)
    })

    it('should update lastUpdated timestamp', () => {
      const before = new Date()

      act(() => {
        useAgentStore.getState().setAgentState({ running: true })
      })

      const state = useAgentStore.getState()
      expect(state.lastUpdated).not.toBeNull()
      expect(state.lastUpdated!.getTime()).toBeGreaterThanOrEqual(before.getTime())
    })
  })

  describe('updateFromWebSocket', () => {
    it('should update state from WebSocket data', () => {
      act(() => {
        useAgentStore.getState().updateFromWebSocket({
          running: true,
          paused: false,
          daily_pnl: 250.00,
          active_trades_count: 2,
        })
      })

      const state = useAgentStore.getState()
      expect(state.agentState?.running).toBe(true)
      expect(state.agentState?.daily_pnl).toBe(250.00)
      expect(state.agentState?.active_trades_count).toBe(2)
    })
  })

  describe('setError', () => {
    it('should set error and stop loading', () => {
      act(() => {
        useAgentStore.getState().setError('Connection failed')
      })

      const state = useAgentStore.getState()
      expect(state.error).toBe('Connection failed')
      expect(state.isLoading).toBe(false)
    })

    it('should clear error when set to null', () => {
      act(() => {
        useAgentStore.getState().setError('Some error')
      })

      act(() => {
        useAgentStore.getState().setError(null)
      })

      const state = useAgentStore.getState()
      expect(state.error).toBeNull()
    })
  })

  describe('reset', () => {
    it('should reset to initial state', () => {
      // Set some state
      act(() => {
        useAgentStore.getState().setAgentState({
          running: true,
          daily_pnl: 500,
        })
      })

      // Reset
      act(() => {
        useAgentStore.getState().reset()
      })

      const state = useAgentStore.getState()
      expect(state.agentState).toBeNull()
      expect(state.isLoading).toBe(true)
      expect(state.lastUpdated).toBeNull()
      expect(state.error).toBeNull()
    })
  })
})
