import { create } from 'zustand'
import { persist } from 'zustand/middleware'

export type ChartTheme = 'dark' | 'tradingview' | 'light'

export interface IndicatorVisibility {
  ema9: boolean
  ema21: boolean
  vwap: boolean
  bollingerBands: boolean
  atrBands: boolean
  volumeProfile: boolean
  volume: boolean
  vwapBands: boolean
  keyLevels: boolean
  tbtTrendlines: boolean
  srPowerZones: boolean
  rsi: boolean
  sessions: boolean
  sdZones: boolean
}

export interface ChartThemeColors {
  background: string
  text: string
  grid: string
  border: string
  candleUp: string
  candleDown: string
  wickUp: string
  wickDown: string
  volume: string
  crosshair: string
}

const THEME_PRESETS: Record<ChartTheme, ChartThemeColors> = {
  dark: {
    background: '#0a0a0f',
    text: '#8a94a6',
    grid: '#1e222d',
    border: '#2a2a3a',
    candleUp: '#00e676',
    candleDown: '#ff5252',
    wickUp: '#00e676',
    wickDown: '#ff5252',
    volume: '#26a69a',
    crosshair: '#758696',
  },
  tradingview: {
    background: '#131722',
    text: '#d1d4dc',
    grid: '#1e222d',
    border: '#2a2e39',
    candleUp: '#26a69a',
    candleDown: '#ef5350',
    wickUp: '#26a69a',
    wickDown: '#ef5350',
    volume: '#26a69a',
    crosshair: '#758696',
  },
  light: {
    background: '#ffffff',
    text: '#131722',
    grid: '#e1e3eb',
    border: '#d1d4dc',
    candleUp: '#26a69a',
    candleDown: '#ef5350',
    wickUp: '#26a69a',
    wickDown: '#ef5350',
    volume: '#26a69a',
    crosshair: '#758696',
  },
}

interface ChartSettingsStore {
  // Theme
  theme: ChartTheme
  colors: ChartThemeColors

  // Indicator visibility
  indicators: IndicatorVisibility

  // Panel visibility
  showVolumeProfilePanel: boolean

  // Chart preferences
  showVolume: boolean
  showSessionHighlights: boolean
  showTradeMarkers: boolean
  showPositionLines: boolean

  // Actions
  setTheme: (theme: ChartTheme) => void
  toggleIndicator: (indicator: keyof IndicatorVisibility) => void
  setIndicatorVisibility: (indicator: keyof IndicatorVisibility, visible: boolean) => void
  toggleVolumeProfilePanel: () => void
  setShowVolume: (show: boolean) => void
  setShowSessionHighlights: (show: boolean) => void
  setShowTradeMarkers: (show: boolean) => void
  setShowPositionLines: (show: boolean) => void
  resetToDefaults: () => void
}

const DEFAULT_INDICATORS: IndicatorVisibility = {
  ema9: true,
  ema21: true,
  vwap: true,
  bollingerBands: false,
  atrBands: false,
  volumeProfile: false,
  volume: true,
  vwapBands: false,
  keyLevels: true,
  tbtTrendlines: false,
  srPowerZones: false,
  rsi: true,
  sessions: false,
  sdZones: false,
}

export const useChartSettingsStore = create<ChartSettingsStore>()(
  persist(
    (set) => ({
      // Initial state
      theme: 'dark',
      colors: THEME_PRESETS.dark,
      indicators: DEFAULT_INDICATORS,
      showVolumeProfilePanel: false,
      showVolume: true,
      showSessionHighlights: true,
      showTradeMarkers: true,
      showPositionLines: true,

      // Actions
      setTheme: (theme) =>
        set({
          theme,
          colors: THEME_PRESETS[theme],
        }),

      toggleIndicator: (indicator) =>
        set((state) => ({
          indicators: {
            ...state.indicators,
            [indicator]: !state.indicators[indicator],
          },
        })),

      setIndicatorVisibility: (indicator, visible) =>
        set((state) => ({
          indicators: {
            ...state.indicators,
            [indicator]: visible,
          },
        })),

      toggleVolumeProfilePanel: () =>
        set((state) => ({ showVolumeProfilePanel: !state.showVolumeProfilePanel })),

      setShowVolume: (show) => set({ showVolume: show }),

      setShowSessionHighlights: (show) => set({ showSessionHighlights: show }),

      setShowTradeMarkers: (show) => set({ showTradeMarkers: show }),

      setShowPositionLines: (show) => set({ showPositionLines: show }),

      resetToDefaults: () =>
        set({
          theme: 'dark',
          colors: THEME_PRESETS.dark,
          indicators: DEFAULT_INDICATORS,
          showVolumeProfilePanel: false,
          showVolume: true,
          showSessionHighlights: true,
          showTradeMarkers: true,
          showPositionLines: true,
        }),
    }),
    {
      name: 'pearl-chart-settings',
      partialize: (state) => ({
        theme: state.theme,
        indicators: state.indicators,
        showVolumeProfilePanel: state.showVolumeProfilePanel,
        showVolume: state.showVolume,
        showSessionHighlights: state.showSessionHighlights,
        showTradeMarkers: state.showTradeMarkers,
        showPositionLines: state.showPositionLines,
      }),
    }
  )
)

// Selectors
export const selectThemeColors = (state: ChartSettingsStore) => state.colors
export const selectIndicatorVisibility = (state: ChartSettingsStore) => state.indicators
export const getThemePreset = (theme: ChartTheme) => THEME_PRESETS[theme]
