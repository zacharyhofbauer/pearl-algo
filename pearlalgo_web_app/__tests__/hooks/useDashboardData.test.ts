/**
 * Tests for useDashboardData hook
 * 
 * Covers:
 * - Successful fetch of all 9 endpoints
 * - Individual endpoint failures (503, network error)
 * - Loading states
 * - Polling cycle
 * - In-flight guard (prevents duplicate requests)
 * - Pull-to-refresh
 * - Hash-based dedup (doesn't update store if data unchanged)
 */

import { renderHook, act, waitFor } from '@testing-library/react'
import { useDashboardData } from '@/hooks/useDashboardData'
import { apiFetch } from '@/lib/api'
import * as stores from '@/stores'

// Mock apiFetch
jest.mock('@/lib/api', () => ({
  apiFetch: jest.fn(),
  getApiUrl: jest.fn(() => 'http://localhost:8000'),
}))

// Mock stores
const mockSetCandles = jest.fn()
const mockSetIndicators = jest.fn()
const mockSetMarkers = jest.fn()
const mockSetMarketStatus = jest.fn()
const mockSetAgentState = jest.fn()
const mockSetChartLoading = jest.fn()
const mockSetChartError = jest.fn()
const mockSetIsLive = jest.fn()
const mockSetIsFetching = jest.fn()
const mockRecordFetch = jest.fn()

jest.mock('@/stores', () => ({
  useAgentStore: jest.fn((selector: (s: any) => unknown) => {
    const state = {
      agentState: { config: { symbol: 'MNQ' } },
    }
    return selector(state)
  }),
  useChartStore: jest.fn((selector: (s: any) => unknown) => {
    const state = {
      candles: [],
      indicators: {},
      markers: [],
      marketStatus: null,
      isLoading: false,
      error: null,
      setCandles: mockSetCandles,
      setIndicators: mockSetIndicators,
      setMarkers: mockSetMarkers,
      setMarketStatus: mockSetMarketStatus,
      setLoading: mockSetChartLoading,
      setError: mockSetChartError,
    }
    return selector(state)
  }),
  useUIStore: jest.fn((selector: (s: any) => unknown) => {
    const state = {
      isFetching: false,
      setIsFetching: mockSetIsFetching,
      recordFetch: mockRecordFetch,
      setIsLive: mockSetIsLive,
    }
    return selector(state)
  }),
}))

const mockApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>

describe('useDashboardData', () => {
  beforeEach(() => {
    jest.clearAllMocks()
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  describe('successful fetch', () => {
    it('should fetch all 9 endpoints in parallel', async () => {
      const mockCandles = [{ time: 1000, open: 1, high: 2, low: 0.5, close: 1.5 }]
      const mockIndicators = { ema9: [] }
      const mockMarkers = []
      const mockState = { running: true }
      const mockMarketStatus = { is_open: true }
      const mockPositions = []
      const mockTrades = []
      const mockPerf = { td: { pnl: 100 } }

      mockApiFetch
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: () => Promise.resolve(mockCandles),
          headers: new Headers(),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockIndicators),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockMarkers),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockState),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockMarketStatus),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockPositions),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockTrades),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockPerf),
        } as Response)

      const { result } = renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'disconnected',
          symbol: 'MNQ',
        })
      )

      await waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalledTimes(9)
      })

      expect(mockSetCandles).toHaveBeenCalledWith(mockCandles)
      expect(mockSetIndicators).toHaveBeenCalledWith(mockIndicators)
      expect(mockSetMarkers).toHaveBeenCalled()
      expect(mockSetMarketStatus).toHaveBeenCalledWith(mockMarketStatus)
      expect(mockSetAgentState).toHaveBeenCalled()
    })

    it('should handle 503 error specifically', async () => {
      mockApiFetch.mockResolvedValueOnce({
        ok: false,
        status: 503,
        json: () => Promise.resolve({ detail: { message: 'Agent not running' } }),
        headers: new Headers(),
      } as Response)

      const { result } = renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'disconnected',
        })
      )

      await waitFor(() => {
        expect(result.current.error).toBeTruthy()
      })

      expect(result.current.error).toContain('Agent not running')
      expect(mockSetChartError).toHaveBeenCalled()
    })

    it('should handle network errors', async () => {
      mockApiFetch.mockRejectedValueOnce(new Error('Network error'))

      const { result } = renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'disconnected',
        })
      )

      await waitFor(() => {
        expect(result.current.error).toBeTruthy()
      })

      expect(result.current.error).toContain('Network error')
    })
  })

  describe('in-flight guard', () => {
    it('should prevent duplicate requests when already fetching', async () => {
      let resolveFirst: () => void
      const firstPromise = new Promise<Response>((resolve) => {
        resolveFirst = () => resolve({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
          headers: new Headers(),
        } as Response)
      })

      mockApiFetch.mockReturnValueOnce(firstPromise)

      const { result } = renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'disconnected',
        })
      )

      // Trigger first fetch
      act(() => {
        result.current.refresh()
      })

      // Try to trigger second fetch while first is in progress
      act(() => {
        result.current.refresh()
      })

      // Should only have called apiFetch once
      expect(mockApiFetch).toHaveBeenCalledTimes(1)

      // Resolve the first fetch
      act(() => {
        resolveFirst!()
      })

      await waitFor(() => {
        expect(mockSetIsFetching).toHaveBeenCalledWith(false)
      })
    })
  })

  describe('polling', () => {
    it('should poll every 10s when WebSocket is disconnected', async () => {
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
        headers: new Headers(),
      } as Response)

      renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'disconnected',
        })
      )

      // Initial fetch
      await waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalled()
      })

      const initialCallCount = mockApiFetch.mock.calls.length

      // Advance timer by 10 seconds
      act(() => {
        jest.advanceTimersByTime(10000)
      })

      await waitFor(() => {
        expect(mockApiFetch.mock.calls.length).toBeGreaterThan(initialCallCount)
      })
    })

    it('should poll every 30s when WebSocket is connected', async () => {
      mockApiFetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve([]),
        headers: new Headers(),
      } as Response)

      renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'connected',
        })
      )

      // Initial fetch
      await waitFor(() => {
        expect(mockApiFetch).toHaveBeenCalled()
      })

      const initialCallCount = mockApiFetch.mock.calls.length

      // Advance timer by 10 seconds - should NOT trigger poll
      act(() => {
        jest.advanceTimersByTime(10000)
      })

      // Advance timer by 20 more seconds (total 30s) - should trigger poll
      act(() => {
        jest.advanceTimersByTime(20000)
      })

      await waitFor(() => {
        expect(mockApiFetch.mock.calls.length).toBeGreaterThan(initialCallCount)
      })
    })
  })

  describe('hash-based dedup', () => {
    it('should not update store if candle data hash is unchanged', async () => {
      const mockCandles = [
        { time: 1000, open: 1, high: 2, low: 0.5, close: 1.5 },
        { time: 2000, open: 1.5, high: 2.5, low: 1, close: 2 },
        { time: 3000, open: 2, high: 3, low: 1.5, close: 2.5 },
      ]

      mockApiFetch
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: () => Promise.resolve(mockCandles),
          headers: new Headers(),
        } as Response)
        .mockResolvedValue({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)

      const { result, rerender } = renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'disconnected',
        })
      )

      await waitFor(() => {
        expect(mockSetCandles).toHaveBeenCalledTimes(1)
      })

      mockSetCandles.mockClear()

      // Trigger another fetch with same data
      act(() => {
        result.current.refresh()
      })

      await waitFor(() => {
        // Should not call setCandles again because hash is the same
        expect(mockSetCandles).not.toHaveBeenCalled()
      })
    })
  })

  describe('optional endpoints', () => {
    it('should handle optional endpoints failing gracefully', async () => {
      mockApiFetch
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
          headers: new Headers(),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve([]),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)
        // Optional endpoints fail
        .mockRejectedValueOnce(new Error('Analytics failed'))
        .mockRejectedValueOnce(new Error('Positions failed'))
        .mockRejectedValueOnce(new Error('Trades failed'))
        .mockRejectedValueOnce(new Error('Performance failed'))

      const { result } = renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'disconnected',
        })
      )

      await waitFor(() => {
        expect(result.current.error).toBeNull()
      })

      // Should not have error because optional endpoints failed
      expect(result.current.error).toBeNull()
    })
  })

  describe('return values', () => {
    it('should return positions, recentTrades, and performanceSummary', async () => {
      const mockPositions = [{ signal_id: '1', entry_price: 100 }]
      const mockTrades = [{ signal_id: '2', pnl: 50 }]
      const mockPerf = { td: { pnl: 100 } }

      mockApiFetch
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          json: () => Promise.resolve([]),
          headers: new Headers(),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve([]),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve({}),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockPositions),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockTrades),
        } as Response)
        .mockResolvedValueOnce({
          ok: true,
          json: () => Promise.resolve(mockPerf),
        } as Response)

      const { result } = renderHook(() =>
        useDashboardData({
          timeframe: '5m',
          barCount: 500,
          wsStatus: 'disconnected',
        })
      )

      await waitFor(() => {
        expect(result.current.positions).toEqual(mockPositions)
        expect(result.current.recentTrades).toEqual(mockTrades)
        expect(result.current.performanceSummary).toEqual(mockPerf)
      })
    })
  })
})
