import React from 'react'
import { render } from '@testing-library/react'
import CandlestickChart from '@/components/CandlestickChart'
import type { CandleData } from '@/stores'

// ---------------------------------------------------------------------------
// Mock lightweight-charts – canvas-based library that cannot render in jsdom
// ---------------------------------------------------------------------------

const mockPriceScale = jest.fn(() => ({
  applyOptions: jest.fn(),
}))

const mockRemovePriceLine = jest.fn()
const mockCreatePriceLine = jest.fn(() => ({}))

const mockSetData = jest.fn()
const mockSetMarkers = jest.fn()
const mockSeriesInstance = {
  setData: mockSetData,
  setMarkers: mockSetMarkers,
  priceToCoordinate: jest.fn(() => 100),
  priceScale: mockPriceScale,
  removePriceLine: mockRemovePriceLine,
  createPriceLine: mockCreatePriceLine,
  applyOptions: jest.fn(),
}

const mockTimeScale = jest.fn(() => ({
  fitContent: jest.fn(),
  scrollToRealTime: jest.fn(),
  setVisibleRange: jest.fn(),
}))

const mockSubscribeCrosshairMove = jest.fn()
const mockUnsubscribeCrosshairMove = jest.fn()
const mockChartRemove = jest.fn()

const mockChartInstance = {
  addSeries: jest.fn(() => mockSeriesInstance),
  applyOptions: jest.fn(),
  timeScale: mockTimeScale,
  subscribeCrosshairMove: mockSubscribeCrosshairMove,
  unsubscribeCrosshairMove: mockUnsubscribeCrosshairMove,
  remove: mockChartRemove,
}

jest.mock('lightweight-charts', () => ({
  createChart: jest.fn(() => mockChartInstance),
  createSeriesMarkers: jest.fn(() => ({ setMarkers: jest.fn(), markers: jest.fn(() => []) })),
  ColorType: { Solid: 'Solid' },
  CrosshairMode: { Normal: 0 },
  LineSeries: {},
  CandlestickSeries: {},
  HistogramSeries: {},
}))

// Mock next/image – render a simple img
jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: Record<string, unknown>) => {
    // eslint-disable-next-line @next/next/no-img-element, jsx-a11y/alt-text
    return <img {...props} />
  },
}))

// Mock chart settings store
jest.mock('@/stores', () => ({
  useChartSettingsStore: jest.fn((selector: (s: any) => unknown) =>
    selector({
      indicators: {
        ema9: true,
        ema21: true,
        vwap: true,
        bollingerBands: false,
        atrBands: false,
      },
    }),
  ),
}))

// Suppress console.warn for expected "Failed to set markers" warnings
const originalWarn = console.warn
beforeAll(() => {
  console.warn = jest.fn()
})
afterAll(() => {
  console.warn = originalWarn
})

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const makeCandle = (overrides: Partial<CandleData> = {}): CandleData => ({
  time: 1717250400,
  open: 18000,
  high: 18050,
  low: 17980,
  close: 18025,
  volume: 1000,
  ...overrides,
})

const makeSampleData = (count = 5): CandleData[] => {
  const base = 1717250400
  return Array.from({ length: count }, (_, i) => ({
    time: base + i * 300,
    open: 18000 + i * 10,
    high: 18060 + i * 10,
    low: 17990 + i * 10,
    close: 18030 + i * 10,
    volume: 1000 + i * 100,
  }))
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CandlestickChart', () => {
  beforeEach(() => {
    jest.clearAllMocks()
  })

  describe('renders without crashing', () => {
    it('renders with valid candle data', () => {
      const { container } = render(
        <CandlestickChart data={makeSampleData()} />
      )

      expect(container).toBeTruthy()
      expect(container.querySelector('.chart-container-inner')).toBeInTheDocument()
    })

    it('calls createChart on mount', () => {
      const { createChart } = require('lightweight-charts')

      render(<CandlestickChart data={makeSampleData()} />)

      expect(createChart).toHaveBeenCalled()
    })

    it('creates candlestick, volume, and indicator series', () => {
      render(<CandlestickChart data={makeSampleData()} />)

      // v5: all series created via chart.addSeries(SeriesType, options)
      expect(mockChartInstance.addSeries).toHaveBeenCalled()
    })

    it('renders the chart info bar with timeframe', () => {
      render(<CandlestickChart data={makeSampleData()} timeframe="5m" />)

      expect(document.querySelector('.chart-info-bar')).toBeInTheDocument()
    })

    it('calls onChartReady callback', () => {
      const onReady = jest.fn()

      render(<CandlestickChart data={makeSampleData()} onChartReady={onReady} />)

      expect(onReady).toHaveBeenCalledWith(mockChartInstance)
    })
  })

  describe('handles empty data array', () => {
    it('renders without crashing when data is empty', () => {
      const { container } = render(
        <CandlestickChart data={[]} />
      )

      expect(container).toBeTruthy()
      expect(container.querySelector('.chart-container-inner')).toBeInTheDocument()
    })

    it('does not call setData on series when data is empty', () => {
      render(<CandlestickChart data={[]} />)

      // setData should not be called (early return in the effect for empty data)
      // The effect checks `!data?.length`
      expect(mockSetData).not.toHaveBeenCalled()
    })

    it('still initializes the chart instance with empty data', () => {
      const { createChart } = require('lightweight-charts')

      render(<CandlestickChart data={[]} />)

      expect(createChart).toHaveBeenCalled()
    })
  })

  describe('handles malformed data gracefully', () => {
    it('renders with candle data missing optional volume field', () => {
      const data: CandleData[] = [
        { time: 1717250400, open: 18000, high: 18050, low: 17980, close: 18025 },
        { time: 1717250700, open: 18025, high: 18060, low: 18000, close: 18040 },
      ]

      const { container } = render(
        <CandlestickChart data={data} />
      )

      expect(container).toBeTruthy()
      expect(container.querySelector('.chart-container-inner')).toBeInTheDocument()
    })

    it('renders a single candle without price change display issues', () => {
      const { container } = render(
        <CandlestickChart data={[makeCandle()]} />
      )

      expect(container).toBeTruthy()
    })

    it('handles undefined markers gracefully', () => {
      const { container } = render(
        <CandlestickChart data={makeSampleData()} markers={undefined} />
      )

      expect(container).toBeTruthy()
    })

    it('handles empty markers array', () => {
      const { container } = render(
        <CandlestickChart data={makeSampleData()} markers={[]} />
      )

      expect(container).toBeTruthy()
    })

    it('handles undefined indicators gracefully', () => {
      const { container } = render(
        <CandlestickChart data={makeSampleData()} indicators={undefined} />
      )

      expect(container).toBeTruthy()
    })
  })

  describe('cleans up on unmount', () => {
    it('calls chart.remove() when component unmounts', () => {
      const { unmount } = render(
        <CandlestickChart data={makeSampleData()} />
      )

      unmount()

      expect(mockChartRemove).toHaveBeenCalled()
    })

    it('calls onChartReady(null) on unmount', () => {
      const onReady = jest.fn()

      const { unmount } = render(
        <CandlestickChart data={makeSampleData()} onChartReady={onReady} />
      )

      unmount()

      // First call with chart instance, second call with null
      expect(onReady).toHaveBeenCalledWith(null)
    })
  })
})
