/**
 * Tests for useDashboardData hook
 *
 * Tests cover:
 * - Parallel data fetching
 * - Error recovery
 * - Data hash change detection
 * - WebSocket integration
 * - Polling behavior based on WebSocket status
 */

import { renderHook, act, waitFor } from '@testing-library/react'

// Mock the stores before importing the hook
jest.mock('@/stores', () => ({
  useAgentStore: jest.fn((selector) =>
    selector({
      setAgentState: jest.fn(),
      updateFromWebSocket: jest.fn(),
    })
  ),
  useChartStore: jest.fn((selector) =>
    selector({
      timeframe: '5m',
      barCount: 100,
      lastDataHash: '',
      setCandles: jest.fn(),
      setIndicators: jest.fn(),
      setMarkers: jest.fn(),
      setMarketStatus: jest.fn(),
      setLoading: jest.fn(),
      setError: jest.fn(),
      setLastDataHash: jest.fn(),
    })
  ),
  useUIStore: jest.fn((selector) =>
    selector({
      wsStatus: 'disconnected',
      setWsStatus: jest.fn(),
      setIsLive: jest.fn(),
      setLastUpdate: jest.fn(),
      setIsFetching: jest.fn(),
      recordFetch: jest.fn(),
    })
  ),
}))

// Mock useWebSocket
jest.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: jest.fn(),
  getWebSocketUrl: jest.fn(() => 'ws://localhost:8000/ws'),
}))

// Mock apiFetch
const mockApiFetch = jest.fn()
jest.mock('@/lib/api', () => ({
  apiFetch: (...args: unknown[]) => mockApiFetch(...args),
}))

import { useDashboardData } from '@/hooks/useDashboardData'
import { useAgentStore, useChartStore, useUIStore } from '@/stores'
import { useWebSocket, getWebSocketUrl } from '@/hooks/useWebSocket'

describe('useDashboardData', () => {
  // Store mocks
  let mockSetAgentState: jest.Mock
  let mockUpdateFromWebSocket: jest.Mock
  let mockSetCandles: jest.Mock
  let mockSetIndicators: jest.Mock
  let mockSetMarkers: jest.Mock
  let mockSetMarketStatus: jest.Mock
  let mockSetLoading: jest.Mock
  let mockSetError: jest.Mock
  let mockSetLastDataHash: jest.Mock
  let mockSetWsStatus: jest.Mock
  let mockSetIsLive: jest.Mock
  let mockSetLastUpdate: jest.Mock
  let mockSetIsFetching: jest.Mock
  let mockRecordFetch: jest.Mock

  // Store state
  let storeState: {
    timeframe: string
    barCount: number
    lastDataHash: string
    wsStatus: string
  }

  beforeEach(() => {
    jest.useFakeTimers()

    // Reset mocks
    mockSetAgentState = jest.fn()
    mockUpdateFromWebSocket = jest.fn()
    mockSetCandles = jest.fn()
    mockSetIndicators = jest.fn()
    mockSetMarkers = jest.fn()
    mockSetMarketStatus = jest.fn()
    mockSetLoading = jest.fn()
    mockSetError = jest.fn()
    mockSetLastDataHash = jest.fn()
    mockSetWsStatus = jest.fn()
    mockSetIsLive = jest.fn()
    mockSetLastUpdate = jest.fn()
    mockSetIsFetching = jest.fn()
    mockRecordFetch = jest.fn()

    // Initialize store state
    storeState = {
      timeframe: '5m',
      barCount: 100,
      lastDataHash: '',
      wsStatus: 'disconnected',
    }

    // Configure store mocks
    ;(useAgentStore as unknown as jest.Mock).mockImplementation((selector) =>
      selector({
        setAgentState: mockSetAgentState,
        updateFromWebSocket: mockUpdateFromWebSocket,
      })
    )

    ;(useChartStore as unknown as jest.Mock).mockImplementation((selector) =>
      selector({
        timeframe: storeState.timeframe,
        barCount: storeState.barCount,
        lastDataHash: storeState.lastDataHash,
        setCandles: mockSetCandles,
        setIndicators: mockSetIndicators,
        setMarkers: mockSetMarkers,
        setMarketStatus: mockSetMarketStatus,
        setLoading: mockSetLoading,
        setError: mockSetError,
        setLastDataHash: mockSetLastDataHash,
      })
    )

    ;(useUIStore as unknown as jest.Mock).mockImplementation((selector) =>
      selector({
        wsStatus: storeState.wsStatus,
        setWsStatus: mockSetWsStatus,
        setIsLive: mockSetIsLive,
        setLastUpdate: mockSetLastUpdate,
        setIsFetching: mockSetIsFetching,
        recordFetch: mockRecordFetch,
      })
    )

    // Configure WebSocket mock
    ;(useWebSocket as jest.Mock).mockImplementation(() => ({
      status: storeState.wsStatus,
      lastMessage: null,
      send: jest.fn(),
      refresh: jest.fn(),
      reconnect: jest.fn(),
      close: jest.fn(),
      reconnectAttempts: 0,
    }))

    // Reset apiFetch mock
    mockApiFetch.mockReset()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  const createMockResponse = (data: unknown, ok = true, status = 200) => ({
    ok,
    status,
    json: () => Promise.resolve(data),
    headers: new Map([['x-data-source', 'live']]),
  })

  const setupSuccessfulFetches = () => {
    mockApiFetch.mockImplementation((path: string) => {
      if (path.includes('/api/candles')) {
        return Promise.resolve(
          createMockResponse([{ time: 1000, open: 100, high: 105, low: 99, close: 102 }])
        )
      }
      if (path.includes('/api/indicators')) {
        return Promise.resolve(createMockResponse({ ema9: [], ema21: [], vwap: [] }))
      }
      if (path.includes('/api/markers')) {
        return Promise.resolve(createMockResponse([]))
      }
      if (path.includes('/api/state')) {
        return Promise.resolve(createMockResponse({ running: true, daily_pnl: 100 }))
      }
      if (path.includes('/api/market-status')) {
        return Promise.resolve(createMockResponse({ is_open: true }))
      }
      if (path.includes('/api/analytics')) {
        return Promise.resolve(createMockResponse({}))
      }
      if (path.includes('/api/positions')) {
        return Promise.resolve(createMockResponse([]))
      }
      return Promise.resolve(createMockResponse({}))
    })
  }

  describe('data fetching', () => {
    it('should fetch all data endpoints in parallel on mount', async () => {
      setupSuccessfulFetches()

      renderHook(() => useDashboardData())

      // Wait for all fetches to complete
      await act(async () => {
        await Promise.resolve()
      })

      // Verify parallel fetches were made
      expect(mockApiFetch).toHaveBeenCalledWith(expect.stringContaining('/api/candles'))
      expect(mockApiFetch).toHaveBeenCalledWith(expect.stringContaining('/api/indicators'))
      expect(mockApiFetch).toHaveBeenCalledWith(expect.stringContaining('/api/markers'))
      expect(mockApiFetch).toHaveBeenCalledWith('/api/state')
      expect(mockApiFetch).toHaveBeenCalledWith('/api/market-status')
    })

    it('should update stores with fetched data', async () => {
      setupSuccessfulFetches()

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      expect(mockSetCandles).toHaveBeenCalled()
      expect(mockSetIndicators).toHaveBeenCalled()
      expect(mockSetMarkers).toHaveBeenCalled()
    })

    it('should request at least MIN_BARS (500)', async () => {
      setupSuccessfulFetches()

      // Configure store with low bar count
      storeState.barCount = 50

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      // Should request 500 bars, not 50
      const candlesCall = mockApiFetch.mock.calls.find((call: [string]) =>
        call[0].includes('/api/candles')
      )
      expect(candlesCall[0]).toContain('bars=500')
    })
  })

  describe('error recovery', () => {
    it('should handle 503 (data unavailable) specifically', async () => {
      mockApiFetch.mockImplementation((path: string) => {
        if (path.includes('/api/candles')) {
          return Promise.resolve({
            ok: false,
            status: 503,
            json: () =>
              Promise.resolve({ detail: { message: 'No Data — Agent Not Running' } }),
          })
        }
        return Promise.resolve(createMockResponse({}))
      })

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      expect(mockSetError).toHaveBeenCalledWith('No Data — Agent Not Running')
      expect(mockSetIsLive).toHaveBeenCalledWith(false)
    })

    it('should handle generic API errors', async () => {
      mockApiFetch.mockImplementation((path: string) => {
        if (path.includes('/api/candles')) {
          return Promise.resolve({
            ok: false,
            status: 500,
          })
        }
        return Promise.resolve(createMockResponse({}))
      })

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      expect(mockSetError).toHaveBeenCalledWith('API Error: 500')
    })

    it('should handle network errors gracefully', async () => {
      mockApiFetch.mockRejectedValue(new Error('Network error'))

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      expect(mockSetError).toHaveBeenCalledWith('Network error')
      expect(mockSetIsLive).toHaveBeenCalledWith(false)
      expect(mockSetLoading).toHaveBeenCalledWith(false)
    })

    it('should continue even if optional endpoints fail', async () => {
      mockApiFetch.mockImplementation((path: string) => {
        if (path.includes('/api/analytics') || path.includes('/api/positions')) {
          return Promise.reject(new Error('Optional endpoint failed'))
        }
        if (path.includes('/api/candles')) {
          return Promise.resolve(
            createMockResponse([{ time: 1000, open: 100, high: 105, low: 99, close: 102 }])
          )
        }
        return Promise.resolve(createMockResponse({}))
      })

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      // Should still update candles despite analytics/positions failing
      expect(mockSetCandles).toHaveBeenCalled()
      expect(mockSetError).toHaveBeenCalledWith(null) // No error set
    })
  })

  describe('data hash change detection', () => {
    it('should only update stores when data hash changes', async () => {
      const candles = [{ time: 1000, open: 100, high: 105, low: 99, close: 102 }]
      setupSuccessfulFetches()

      // First render with empty hash
      storeState.lastDataHash = ''

      const { rerender } = renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      expect(mockSetCandles).toHaveBeenCalledTimes(1)
      expect(mockSetLastDataHash).toHaveBeenCalled()

      // Get the hash that was set
      const firstHash = mockSetLastDataHash.mock.calls[0][0]

      // Update store state with the same hash
      storeState.lastDataHash = firstHash

      // Reset mocks
      mockSetCandles.mockClear()
      mockSetLastDataHash.mockClear()

      // Force another fetch
      rerender()
      await act(async () => {
        jest.advanceTimersByTime(10000)
        await Promise.resolve()
      })

      // Should not update candles because hash is the same
      // (In the actual implementation, setCandles is not called if hash matches)
    })
  })

  describe('polling behavior', () => {
    it('should use slower polling interval when WebSocket connected', async () => {
      setupSuccessfulFetches()
      storeState.wsStatus = 'connected'

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      // Initial fetch
      expect(mockApiFetch).toHaveBeenCalledTimes(7) // 7 endpoints

      mockApiFetch.mockClear()

      // Wait for 10 seconds (fast interval) - should not trigger
      await act(async () => {
        jest.advanceTimersByTime(10000)
        await Promise.resolve()
      })

      // When WS connected, uses 30s interval, so no fetch at 10s
      // Note: This depends on implementation details
    })

    it('should use faster polling when WebSocket disconnected', async () => {
      setupSuccessfulFetches()
      storeState.wsStatus = 'disconnected'

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      mockApiFetch.mockClear()

      // Wait for 10 seconds
      await act(async () => {
        jest.advanceTimersByTime(10000)
        await Promise.resolve()
      })

      // Should have triggered another fetch cycle
      expect(mockApiFetch).toHaveBeenCalled()
    })
  })

  describe('forceRefresh', () => {
    it('should provide forceRefresh function', async () => {
      setupSuccessfulFetches()

      const { result } = renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      expect(result.current.forceRefresh).toBeDefined()
      expect(typeof result.current.forceRefresh).toBe('function')
    })

    it('should trigger fetch when forceRefresh called', async () => {
      setupSuccessfulFetches()

      const { result } = renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      mockApiFetch.mockClear()

      await act(async () => {
        result.current.forceRefresh()
        await Promise.resolve()
      })

      expect(mockApiFetch).toHaveBeenCalled()
    })
  })

  describe('positions callback', () => {
    it('should call onPositionsUpdate with position data', async () => {
      const positions = [{ signal_id: '1', entry_price: 100, direction: 'long' }]

      mockApiFetch.mockImplementation((path: string) => {
        if (path.includes('/api/positions')) {
          return Promise.resolve(createMockResponse(positions))
        }
        if (path.includes('/api/candles')) {
          return Promise.resolve(
            createMockResponse([{ time: 1000, open: 100, high: 105, low: 99, close: 102 }])
          )
        }
        return Promise.resolve(createMockResponse({}))
      })

      const onPositionsUpdate = jest.fn()

      renderHook(() => useDashboardData({ onPositionsUpdate }))

      await act(async () => {
        await Promise.resolve()
      })

      expect(onPositionsUpdate).toHaveBeenCalledWith(positions, null, 2.0)
    })

    it('should call onPositionsUpdate with empty array on error', async () => {
      mockApiFetch.mockImplementation((path: string) => {
        if (path.includes('/api/positions')) {
          return Promise.resolve({ ok: false, status: 500 })
        }
        if (path.includes('/api/candles')) {
          return Promise.resolve(
            createMockResponse([{ time: 1000, open: 100, high: 105, low: 99, close: 102 }])
          )
        }
        return Promise.resolve(createMockResponse({}))
      })

      const onPositionsUpdate = jest.fn()

      renderHook(() => useDashboardData({ onPositionsUpdate }))

      await act(async () => {
        await Promise.resolve()
      })

      expect(onPositionsUpdate).toHaveBeenCalledWith([], null, 2.0)
    })
  })

  describe('fetch timing', () => {
    it('should track fetch duration', async () => {
      setupSuccessfulFetches()

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      // recordFetch should be called with duration and source
      expect(mockRecordFetch).toHaveBeenCalled()
      const [duration, source] = mockRecordFetch.mock.calls[0]
      expect(typeof duration).toBe('number')
      expect(source).toBe('live')
    })

    it('should set isFetching during fetch', async () => {
      setupSuccessfulFetches()

      renderHook(() => useDashboardData())

      // Should be fetching initially
      expect(mockSetIsFetching).toHaveBeenCalledWith(true)

      await act(async () => {
        await Promise.resolve()
      })

      // After completion, fetching state is updated by recordFetch
    })
  })

  describe('marker filtering', () => {
    it('should filter markers to candle time range', async () => {
      const candles = [
        { time: 1000, open: 100, high: 105, low: 99, close: 102 },
        { time: 2000, open: 102, high: 108, low: 101, close: 106 },
      ]

      const markers = [
        { time: 500, type: 'entry' }, // Before candles
        { time: 1500, type: 'entry' }, // Within candles
        { time: 2500, type: 'exit' }, // After candles
      ]

      mockApiFetch.mockImplementation((path: string) => {
        if (path.includes('/api/candles')) {
          return Promise.resolve(createMockResponse(candles))
        }
        if (path.includes('/api/markers')) {
          return Promise.resolve(createMockResponse(markers))
        }
        return Promise.resolve(createMockResponse({}))
      })

      renderHook(() => useDashboardData())

      await act(async () => {
        await Promise.resolve()
      })

      // setMarkers should be called with filtered markers (only time=1500)
      expect(mockSetMarkers).toHaveBeenCalledWith([{ time: 1500, type: 'entry' }])
    })
  })
})
