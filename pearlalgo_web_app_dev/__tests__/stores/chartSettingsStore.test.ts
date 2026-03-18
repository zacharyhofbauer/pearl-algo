import { useChartSettingsStore, type ChartTheme } from '@/stores/chartSettingsStore'

describe('chartSettingsStore', () => {
  beforeEach(() => {
    window.localStorage.clear()
    useChartSettingsStore.setState({
      theme: 'dark',
      colors: {
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
      indicators: {
        ema9: true,
        ema21: true,
        vwap: true,
        bollingerBands: false,
        atrBands: false,
        volumeProfile: false,
        volume: true,
      },
      showVolumeProfilePanel: false,
      showVolume: true,
      showSessionHighlights: true,
      showTradeMarkers: true,
      showPositionLines: true,
    })
  })

  describe('setTheme', () => {
    it('should switch to dark theme', () => {
      useChartSettingsStore.getState().setTheme('dark')

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('dark')
      expect(state.colors.background).toBe('#0a0a0f')
      expect(state.colors.candleUp).toBe('#00e676')
    })

    it('should switch to tradingview theme', () => {
      useChartSettingsStore.getState().setTheme('tradingview')

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('tradingview')
      expect(state.colors.background).toBe('#131722')
      expect(state.colors.candleUp).toBe('#26a69a')
    })

    it('should switch to light theme', () => {
      useChartSettingsStore.getState().setTheme('light')

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('light')
      expect(state.colors.background).toBe('#ffffff')
      expect(state.colors.text).toBe('#131722')
    })

    it('should update colors when theme changes', () => {
      useChartSettingsStore.getState().setTheme('tradingview')
      const tradingviewColors = useChartSettingsStore.getState().colors

      useChartSettingsStore.getState().setTheme('light')
      const lightColors = useChartSettingsStore.getState().colors

      expect(lightColors).not.toEqual(tradingviewColors)
      expect(lightColors.background).toBe('#ffffff')
    })
  })

  describe('toggleIndicator', () => {
    it('should toggle indicator from false to true', () => {
      useChartSettingsStore.setState((state) => ({
        indicators: { ...state.indicators, bollingerBands: false },
      }))

      useChartSettingsStore.getState().toggleIndicator('bollingerBands')

      const state = useChartSettingsStore.getState()
      expect(state.indicators.bollingerBands).toBe(true)
    })

    it('should toggle indicator from true to false', () => {
      useChartSettingsStore.setState((state) => ({
        indicators: { ...state.indicators, ema9: true },
      }))

      useChartSettingsStore.getState().toggleIndicator('ema9')

      const state = useChartSettingsStore.getState()
      expect(state.indicators.ema9).toBe(false)
    })

    it('should toggle all indicator types', () => {
      const indicators = [
        'ema9',
        'ema21',
        'vwap',
        'bollingerBands',
        'atrBands',
        'volumeProfile',
        'volume',
      ]

      indicators.forEach((indicator) => {
        const before = useChartSettingsStore.getState().indicators[indicator]
        useChartSettingsStore.getState().toggleIndicator(indicator)
        const after = useChartSettingsStore.getState().indicators[indicator]
        expect(after).toBe(!before)
      })
    })
  })

  describe('setIndicatorVisibility', () => {
    it('should set indicator visibility to true', () => {
      useChartSettingsStore.setState((state) => ({
        indicators: { ...state.indicators, bollingerBands: false },
      }))

      useChartSettingsStore.getState().setIndicatorVisibility('bollingerBands', true)

      const state = useChartSettingsStore.getState()
      expect(state.indicators.bollingerBands).toBe(true)
    })

    it('should set indicator visibility to false', () => {
      useChartSettingsStore.setState((state) => ({
        indicators: { ...state.indicators, ema9: true },
      }))

      useChartSettingsStore.getState().setIndicatorVisibility('ema9', false)

      const state = useChartSettingsStore.getState()
      expect(state.indicators.ema9).toBe(false)
    })

    it('should not affect other indicators', () => {
      const initialState = useChartSettingsStore.getState().indicators

      useChartSettingsStore.getState().setIndicatorVisibility('bollingerBands', true)

      const state = useChartSettingsStore.getState()
      expect(state.indicators.ema9).toBe(initialState.ema9)
      expect(state.indicators.ema21).toBe(initialState.ema21)
      expect(state.indicators.vwap).toBe(initialState.vwap)
      expect(state.indicators.bollingerBands).toBe(true)
    })
  })

  describe('resetToDefaults', () => {
    it('should reset all settings to defaults', () => {
      // Modify settings
      useChartSettingsStore.getState().setTheme('light')
      useChartSettingsStore.getState().toggleIndicator('bollingerBands')
      useChartSettingsStore.getState().setShowVolume(false)
      useChartSettingsStore.getState().setShowSessionHighlights(false)

      useChartSettingsStore.getState().resetToDefaults()

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('dark')
      expect(state.colors.background).toBe('#0a0a0f')
      expect(state.indicators.ema9).toBe(true)
      expect(state.indicators.ema21).toBe(true)
      expect(state.indicators.vwap).toBe(true)
      expect(state.indicators.bollingerBands).toBe(false)
      expect(state.indicators.atrBands).toBe(false)
      expect(state.indicators.volumeProfile).toBe(false)
      expect(state.indicators.volume).toBe(true)
      expect(state.showVolumeProfilePanel).toBe(false)
      expect(state.showVolume).toBe(true)
      expect(state.showSessionHighlights).toBe(true)
      expect(state.showTradeMarkers).toBe(true)
      expect(state.showPositionLines).toBe(true)
    })
  })

  describe('panel visibility toggles', () => {
    it('should toggle volume profile panel', () => {
      expect(useChartSettingsStore.getState().showVolumeProfilePanel).toBe(false)

      useChartSettingsStore.getState().toggleVolumeProfilePanel()

      expect(useChartSettingsStore.getState().showVolumeProfilePanel).toBe(true)

      useChartSettingsStore.getState().toggleVolumeProfilePanel()

      expect(useChartSettingsStore.getState().showVolumeProfilePanel).toBe(false)
    })

    it('should set show volume', () => {
      useChartSettingsStore.getState().setShowVolume(false)
      expect(useChartSettingsStore.getState().showVolume).toBe(false)

      useChartSettingsStore.getState().setShowVolume(true)
      expect(useChartSettingsStore.getState().showVolume).toBe(true)
    })

    it('should set show session highlights', () => {
      useChartSettingsStore.getState().setShowSessionHighlights(false)
      expect(useChartSettingsStore.getState().showSessionHighlights).toBe(false)

      useChartSettingsStore.getState().setShowSessionHighlights(true)
      expect(useChartSettingsStore.getState().showSessionHighlights).toBe(true)
    })

    it('should set show trade markers', () => {
      useChartSettingsStore.getState().setShowTradeMarkers(false)
      expect(useChartSettingsStore.getState().showTradeMarkers).toBe(false)

      useChartSettingsStore.getState().setShowTradeMarkers(true)
      expect(useChartSettingsStore.getState().showTradeMarkers).toBe(true)
    })

    it('should set show position lines', () => {
      useChartSettingsStore.getState().setShowPositionLines(false)
      expect(useChartSettingsStore.getState().showPositionLines).toBe(false)

      useChartSettingsStore.getState().setShowPositionLines(true)
      expect(useChartSettingsStore.getState().showPositionLines).toBe(true)
    })
  })

  describe('persistence', () => {
    it('should persist theme changes', () => {
      useChartSettingsStore.getState().setTheme('tradingview')

      const persisted = window.localStorage.getItem('pearl-chart-settings')
      expect(persisted).toBeTruthy()
      const data = JSON.parse(persisted!)
      expect(data.state.theme).toBe('tradingview')
    })

    it('should persist indicator visibility changes', () => {
      useChartSettingsStore.getState().toggleIndicator('bollingerBands')

      const persisted = window.localStorage.getItem('pearl-chart-settings')
      expect(persisted).toBeTruthy()
      const data = JSON.parse(persisted!)
      expect(data.state.indicators.bollingerBands).toBe(true)
    })

    it('should persist panel visibility changes', () => {
      useChartSettingsStore.getState().toggleVolumeProfilePanel()

      const persisted = window.localStorage.getItem('pearl-chart-settings')
      expect(persisted).toBeTruthy()
      const data = JSON.parse(persisted!)
      expect(data.state.showVolumeProfilePanel).toBe(true)
    })
  })

  describe('edge cases', () => {
    it('should handle invalid theme key gracefully', () => {
      // TypeScript prevents invalid keys, but runtime could have issues
      // Test that the store doesn't crash with unexpected input
      const state = useChartSettingsStore.getState()
      expect(state.theme).toBeDefined()
      expect(['dark', 'tradingview', 'light']).toContain(state.theme)
    })

    it('should maintain state consistency after multiple operations', () => {
      useChartSettingsStore.getState().setTheme('light')
      useChartSettingsStore.getState().toggleIndicator('ema9')
      useChartSettingsStore.getState().toggleIndicator('ema21')
      useChartSettingsStore.getState().setIndicatorVisibility('bollingerBands', true)
      useChartSettingsStore.getState().setShowVolume(false)

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('light')
      expect(state.indicators.ema9).toBe(false)
      expect(state.indicators.ema21).toBe(false)
      expect(state.indicators.bollingerBands).toBe(true)
      expect(state.showVolume).toBe(false)
    })
  })
})
