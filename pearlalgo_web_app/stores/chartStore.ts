import { create } from 'zustand'

// Types for chart data
export interface CandleData {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

export interface IndicatorData {
  time: number
  value: number
}

export interface BollingerBandsData {
  time: number
  upper: number
  middle: number
  lower: number
}

export interface ATRBandsData {
  time: number
  upper: number
  lower: number
  atr: number
}

export interface VolumeProfileData {
  price: number
  volume: number
  buyVolume: number
  sellVolume: number
}

export interface VolumeProfile {
  levels: VolumeProfileData[]
  poc: number  // Point of Control - price with highest volume
  vah: number  // Value Area High
  val: number  // Value Area Low
}

export interface Indicators {
  ema9?: IndicatorData[]
  ema21?: IndicatorData[]
  vwap?: IndicatorData[]
  bollingerBands?: BollingerBandsData[]
  atrBands?: ATRBandsData[]
  volumeProfile?: VolumeProfile
}

export interface MarkerData {
  time: number
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle'
  text: string
  // Additional metadata for tooltips
  kind?: 'entry' | 'exit'
  signal_id?: string
  direction?: string
  entry_price?: number
  exit_price?: number
  pnl?: number
  reason?: string
  exit_reason?: string
}

// Active position for chart price lines
export interface Position {
  signal_id: string
  direction: 'long' | 'short'
  entry_price: number
  entry_time?: string
  stop_loss?: number
  take_profit?: number
}

// Position line for chart visualization
export interface PositionLine {
  price: number
  color: string
  title: string
  /** Optional semantic type used for label de-cluttering */
  kind?: 'entry' | 'sl' | 'tp'
  lineStyle?: number  // 0=solid, 1=dotted, 2=dashed
  axisLabelVisible?: boolean  // Show/hide price on axis
}

export interface MarketStatus {
  is_open: boolean
  close_reason: string | null
  next_open: string | null
  current_time_et: string
}

export type Timeframe = '1m' | '5m' | '15m' | '30m' | '1h' | '4h' | '1D'

interface ChartStore {
  // State
  candles: CandleData[]
  indicators: Indicators
  markers: MarkerData[]
  marketStatus: MarketStatus | null
  timeframe: Timeframe
  barCount: number
  barSpacing: number
  isLoading: boolean
  error: string | null
  lastDataHash: string

  // Actions
  setCandles: (candles: CandleData[]) => void
  setIndicators: (indicators: Indicators) => void
  setMarkers: (markers: MarkerData[]) => void
  setMarketStatus: (status: MarketStatus | null) => void
  setTimeframe: (timeframe: Timeframe) => void
  setBarCount: (count: number) => void
  setBarSpacing: (spacing: number) => void
  setLoading: (loading: boolean) => void
  setError: (error: string | null) => void
  setLastDataHash: (hash: string) => void
  updateChartData: (data: {
    candles?: CandleData[]
    indicators?: Indicators
    markers?: MarkerData[]
    marketStatus?: MarketStatus
  }) => void
  reset: () => void
}

export const useChartStore = create<ChartStore>((set) => ({
  // Initial state
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

  // Actions
  setCandles: (candles) => set({ candles, isLoading: false }),

  setIndicators: (indicators) => set({ indicators }),

  setMarkers: (markers) => set({ markers }),

  setMarketStatus: (marketStatus) => set({ marketStatus }),

  setTimeframe: (timeframe) =>
    set({
      timeframe,
      isLoading: true,
      // Keep existing data visible while loading new timeframe
      // This prevents the flash/loading screen during timeframe changes
      lastDataHash: '', // Force data refresh
    }),

  setBarCount: (barCount) => set({ barCount }),

  setBarSpacing: (barSpacing) => set({ barSpacing }),

  setLoading: (isLoading) => set({ isLoading }),

  setError: (error) => set({ error, isLoading: false }),

  setLastDataHash: (lastDataHash) => set({ lastDataHash }),

  updateChartData: (data) =>
    set((state) => ({
      ...state,
      ...(data.candles && { candles: data.candles }),
      ...(data.indicators && { indicators: data.indicators }),
      ...(data.markers && { markers: data.markers }),
      ...(data.marketStatus && { marketStatus: data.marketStatus }),
      isLoading: false,
      error: null,
    })),

  reset: () =>
    set({
      candles: [],
      indicators: {},
      markers: [],
      marketStatus: null,
      isLoading: true,
      error: null,
      lastDataHash: '',
    }),
}))

// Selectors
export const selectCurrentPrice = (state: ChartStore) =>
  state.candles.length > 0 ? state.candles[state.candles.length - 1]?.close : null

export const selectPriceChange = (state: ChartStore) => {
  if (state.candles.length < 2) return 0
  const last = state.candles[state.candles.length - 1]
  return last.close - last.open
}

export const selectIsMarketOpen = (state: ChartStore) =>
  state.marketStatus?.is_open ?? true
