import { useChartStore, selectCurrentPrice, selectPriceChange, selectIsMarketOpen } from '@/stores/chartStore'
import { act } from '@testing-library/react'

describe('chartStore', () => {
  beforeEach(() => {
    // Reset store before each test
    useChartStore.setState({
      candles: [],
      indicators: {},
      markers: [],
      marketStatus: null,
      timeframe: '5m',
      barCount: 150,
      barSpacing: 10,
      isLoading: true,
      error: null,
      lastDataHash: '',
    })
  })

  describe('initial state', () => {
    it('should have empty candles', () => {
      const state = useChartStore.getState()
      expect(state.candles).toEqual([])
    })

    it('should default to 5m timeframe', () => {
      const state = useChartStore.getState()
      expect(state.timeframe).toBe('5m')
    })

    it('should be loading initially', () => {
      const state = useChartStore.getState()
      expect(state.isLoading).toBe(true)
    })
  })

  describe('setCandles', () => {
    it('should set candles and stop loading', () => {
      const candles = [
        { time: 1000, open: 100, high: 105, low: 98, close: 103 },
        { time: 1300, open: 103, high: 110, low: 101, close: 108 },
      ]

      act(() => {
        useChartStore.getState().setCandles(candles)
      })

      const state = useChartStore.getState()
      expect(state.candles).toEqual(candles)
      expect(state.isLoading).toBe(false)
    })
  })

  describe('setTimeframe', () => {
    it('should update timeframe and reset chart state', () => {
      // First set some candles
      act(() => {
        useChartStore.getState().setCandles([
          { time: 1000, open: 100, high: 105, low: 98, close: 103 },
        ])
      })

      // Change timeframe
      act(() => {
        useChartStore.getState().setTimeframe('15m')
      })

      const state = useChartStore.getState()
      expect(state.timeframe).toBe('15m')
      expect(state.candles).toEqual([])
      expect(state.indicators).toEqual({})
      expect(state.isLoading).toBe(true)
      expect(state.lastDataHash).toBe('')
    })
  })

  describe('setMarketStatus', () => {
    it('should set market status', () => {
      const status = {
        is_open: true,
        close_reason: null,
        next_open: null,
        current_time_et: '2024-01-15T10:30:00',
      }

      act(() => {
        useChartStore.getState().setMarketStatus(status)
      })

      const state = useChartStore.getState()
      expect(state.marketStatus).toEqual(status)
    })
  })

  describe('updateChartData', () => {
    it('should update multiple fields at once', () => {
      const candles = [
        { time: 1000, open: 100, high: 105, low: 98, close: 103 },
      ]
      const indicators = {
        ema9: [{ time: 1000, value: 102 }],
      }
      const marketStatus = {
        is_open: true,
        close_reason: null,
        next_open: null,
        current_time_et: '2024-01-15T10:30:00',
      }

      act(() => {
        useChartStore.getState().updateChartData({
          candles,
          indicators,
          marketStatus,
        })
      })

      const state = useChartStore.getState()
      expect(state.candles).toEqual(candles)
      expect(state.indicators).toEqual(indicators)
      expect(state.marketStatus).toEqual(marketStatus)
      expect(state.isLoading).toBe(false)
      expect(state.error).toBeNull()
    })
  })

  describe('setError', () => {
    it('should set error and stop loading', () => {
      act(() => {
        useChartStore.getState().setError('Failed to fetch data')
      })

      const state = useChartStore.getState()
      expect(state.error).toBe('Failed to fetch data')
      expect(state.isLoading).toBe(false)
    })
  })

  describe('reset', () => {
    it('should reset to initial state', () => {
      // Set some data
      act(() => {
        useChartStore.getState().setCandles([
          { time: 1000, open: 100, high: 105, low: 98, close: 103 },
        ])
        useChartStore.getState().setTimeframe('1h')
      })

      // Reset
      act(() => {
        useChartStore.getState().reset()
      })

      const state = useChartStore.getState()
      expect(state.candles).toEqual([])
      expect(state.timeframe).toBe('1h') // Note: timeframe is not reset
      expect(state.isLoading).toBe(true)
    })
  })

  describe('selectors', () => {
    describe('selectCurrentPrice', () => {
      it('should return null when no candles', () => {
        const state = useChartStore.getState()
        expect(selectCurrentPrice(state)).toBeNull()
      })

      it('should return last candle close price', () => {
        act(() => {
          useChartStore.getState().setCandles([
            { time: 1000, open: 100, high: 105, low: 98, close: 103 },
            { time: 1300, open: 103, high: 110, low: 101, close: 108 },
          ])
        })

        const state = useChartStore.getState()
        expect(selectCurrentPrice(state)).toBe(108)
      })
    })

    describe('selectPriceChange', () => {
      it('should return 0 when less than 2 candles', () => {
        act(() => {
          useChartStore.getState().setCandles([
            { time: 1000, open: 100, high: 105, low: 98, close: 103 },
          ])
        })

        const state = useChartStore.getState()
        expect(selectPriceChange(state)).toBe(0)
      })

      it('should return price change for last candle', () => {
        act(() => {
          useChartStore.getState().setCandles([
            { time: 1000, open: 100, high: 105, low: 98, close: 103 },
            { time: 1300, open: 105, high: 110, low: 101, close: 108 },
          ])
        })

        const state = useChartStore.getState()
        expect(selectPriceChange(state)).toBe(3) // 108 - 105
      })
    })

    describe('selectIsMarketOpen', () => {
      it('should return true when market status is null', () => {
        const state = useChartStore.getState()
        expect(selectIsMarketOpen(state)).toBe(true)
      })

      it('should return market open status', () => {
        act(() => {
          useChartStore.getState().setMarketStatus({
            is_open: false,
            close_reason: 'Weekend',
            next_open: null,
            current_time_et: '2024-01-15T10:30:00',
          })
        })

        const state = useChartStore.getState()
        expect(selectIsMarketOpen(state)).toBe(false)
      })
    })
  })
})
