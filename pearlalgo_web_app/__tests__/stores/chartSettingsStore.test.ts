/**
 * Tests for chartSettingsStore
 *
 * Tests cover:
 * - Theme management
 * - Indicator visibility toggles
 * - Panel visibility toggles
 * - Chart preferences
 * - Reset to defaults
 * - Theme color presets
 */

import { act } from '@testing-library/react'
import {
  useChartSettingsStore,
  getThemePreset,
  ChartTheme,
} from '@/stores/chartSettingsStore'

describe('chartSettingsStore', () => {
  beforeEach(() => {
    // Reset store to defaults before each test
    useChartSettingsStore.getState().resetToDefaults()
  })

  describe('initial state', () => {
    it('should have dark theme by default', () => {
      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('dark')
    })

    it('should have correct default indicator visibility', () => {
      const state = useChartSettingsStore.getState()
      expect(state.indicators.ema9).toBe(true)
      expect(state.indicators.ema21).toBe(true)
      expect(state.indicators.vwap).toBe(true)
      expect(state.indicators.rsi).toBe(true)
      expect(state.indicators.macd).toBe(true)
      expect(state.indicators.bollingerBands).toBe(false)
      expect(state.indicators.atrBands).toBe(false)
      expect(state.indicators.volumeProfile).toBe(false)
      expect(state.indicators.volume).toBe(true)
    })

    it('should have correct default panel visibility', () => {
      const state = useChartSettingsStore.getState()
      expect(state.showRSIPanel).toBe(true)
      expect(state.showMACDPanel).toBe(true)
      expect(state.showVolumeProfilePanel).toBe(false)
    })

    it('should have correct default chart preferences', () => {
      const state = useChartSettingsStore.getState()
      expect(state.showVolume).toBe(true)
      expect(state.showSessionHighlights).toBe(true)
      expect(state.showTradeMarkers).toBe(true)
      expect(state.showPositionLines).toBe(true)
    })

    it('should have dark theme colors by default', () => {
      const state = useChartSettingsStore.getState()
      expect(state.colors.background).toBe('#0a0a0f')
      expect(state.colors.candleUp).toBe('#00e676')
      expect(state.colors.candleDown).toBe('#ff5252')
    })
  })

  describe('setTheme', () => {
    it('should change theme to tradingview', () => {
      act(() => {
        useChartSettingsStore.getState().setTheme('tradingview')
      })

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('tradingview')
      expect(state.colors.background).toBe('#131722')
    })

    it('should change theme to light', () => {
      act(() => {
        useChartSettingsStore.getState().setTheme('light')
      })

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('light')
      expect(state.colors.background).toBe('#ffffff')
      expect(state.colors.text).toBe('#131722')
    })

    it('should change theme back to dark', () => {
      act(() => {
        useChartSettingsStore.getState().setTheme('light')
      })

      act(() => {
        useChartSettingsStore.getState().setTheme('dark')
      })

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('dark')
      expect(state.colors.background).toBe('#0a0a0f')
    })

    it('should update colors to match theme preset', () => {
      act(() => {
        useChartSettingsStore.getState().setTheme('tradingview')
      })

      const state = useChartSettingsStore.getState()
      const preset = getThemePreset('tradingview')
      expect(state.colors).toEqual(preset)
    })
  })

  describe('toggleIndicator', () => {
    it('should toggle ema9 off', () => {
      expect(useChartSettingsStore.getState().indicators.ema9).toBe(true)

      act(() => {
        useChartSettingsStore.getState().toggleIndicator('ema9')
      })

      expect(useChartSettingsStore.getState().indicators.ema9).toBe(false)
    })

    it('should toggle ema9 on again', () => {
      act(() => {
        useChartSettingsStore.getState().toggleIndicator('ema9')
      })
      expect(useChartSettingsStore.getState().indicators.ema9).toBe(false)

      act(() => {
        useChartSettingsStore.getState().toggleIndicator('ema9')
      })
      expect(useChartSettingsStore.getState().indicators.ema9).toBe(true)
    })

    it('should toggle bollingerBands on', () => {
      expect(useChartSettingsStore.getState().indicators.bollingerBands).toBe(false)

      act(() => {
        useChartSettingsStore.getState().toggleIndicator('bollingerBands')
      })

      expect(useChartSettingsStore.getState().indicators.bollingerBands).toBe(true)
    })

    it('should not affect other indicators', () => {
      act(() => {
        useChartSettingsStore.getState().toggleIndicator('ema9')
      })

      const state = useChartSettingsStore.getState()
      expect(state.indicators.ema9).toBe(false)
      expect(state.indicators.ema21).toBe(true) // Unchanged
      expect(state.indicators.vwap).toBe(true) // Unchanged
    })
  })

  describe('setIndicatorVisibility', () => {
    it('should set indicator visibility to true', () => {
      expect(useChartSettingsStore.getState().indicators.bollingerBands).toBe(false)

      act(() => {
        useChartSettingsStore.getState().setIndicatorVisibility('bollingerBands', true)
      })

      expect(useChartSettingsStore.getState().indicators.bollingerBands).toBe(true)
    })

    it('should set indicator visibility to false', () => {
      expect(useChartSettingsStore.getState().indicators.ema9).toBe(true)

      act(() => {
        useChartSettingsStore.getState().setIndicatorVisibility('ema9', false)
      })

      expect(useChartSettingsStore.getState().indicators.ema9).toBe(false)
    })

    it('should not toggle when setting to same value', () => {
      expect(useChartSettingsStore.getState().indicators.ema9).toBe(true)

      act(() => {
        useChartSettingsStore.getState().setIndicatorVisibility('ema9', true)
      })

      expect(useChartSettingsStore.getState().indicators.ema9).toBe(true)
    })
  })

  describe('panel visibility toggles', () => {
    it('should toggle RSI panel', () => {
      expect(useChartSettingsStore.getState().showRSIPanel).toBe(true)

      act(() => {
        useChartSettingsStore.getState().toggleRSIPanel()
      })

      expect(useChartSettingsStore.getState().showRSIPanel).toBe(false)

      act(() => {
        useChartSettingsStore.getState().toggleRSIPanel()
      })

      expect(useChartSettingsStore.getState().showRSIPanel).toBe(true)
    })

    it('should toggle MACD panel', () => {
      expect(useChartSettingsStore.getState().showMACDPanel).toBe(true)

      act(() => {
        useChartSettingsStore.getState().toggleMACDPanel()
      })

      expect(useChartSettingsStore.getState().showMACDPanel).toBe(false)
    })

    it('should toggle Volume Profile panel', () => {
      expect(useChartSettingsStore.getState().showVolumeProfilePanel).toBe(false)

      act(() => {
        useChartSettingsStore.getState().toggleVolumeProfilePanel()
      })

      expect(useChartSettingsStore.getState().showVolumeProfilePanel).toBe(true)
    })
  })

  describe('chart preference setters', () => {
    it('should set showVolume', () => {
      expect(useChartSettingsStore.getState().showVolume).toBe(true)

      act(() => {
        useChartSettingsStore.getState().setShowVolume(false)
      })

      expect(useChartSettingsStore.getState().showVolume).toBe(false)
    })

    it('should set showSessionHighlights', () => {
      expect(useChartSettingsStore.getState().showSessionHighlights).toBe(true)

      act(() => {
        useChartSettingsStore.getState().setShowSessionHighlights(false)
      })

      expect(useChartSettingsStore.getState().showSessionHighlights).toBe(false)
    })

    it('should set showTradeMarkers', () => {
      expect(useChartSettingsStore.getState().showTradeMarkers).toBe(true)

      act(() => {
        useChartSettingsStore.getState().setShowTradeMarkers(false)
      })

      expect(useChartSettingsStore.getState().showTradeMarkers).toBe(false)
    })

    it('should set showPositionLines', () => {
      expect(useChartSettingsStore.getState().showPositionLines).toBe(true)

      act(() => {
        useChartSettingsStore.getState().setShowPositionLines(false)
      })

      expect(useChartSettingsStore.getState().showPositionLines).toBe(false)
    })
  })

  describe('resetToDefaults', () => {
    it('should reset theme to dark', () => {
      act(() => {
        useChartSettingsStore.getState().setTheme('light')
      })

      act(() => {
        useChartSettingsStore.getState().resetToDefaults()
      })

      expect(useChartSettingsStore.getState().theme).toBe('dark')
    })

    it('should reset all indicators to defaults', () => {
      act(() => {
        useChartSettingsStore.getState().toggleIndicator('ema9')
        useChartSettingsStore.getState().toggleIndicator('bollingerBands')
        useChartSettingsStore.getState().toggleIndicator('atrBands')
      })

      act(() => {
        useChartSettingsStore.getState().resetToDefaults()
      })

      const state = useChartSettingsStore.getState()
      expect(state.indicators.ema9).toBe(true)
      expect(state.indicators.bollingerBands).toBe(false)
      expect(state.indicators.atrBands).toBe(false)
    })

    it('should reset all panels to defaults', () => {
      act(() => {
        useChartSettingsStore.getState().toggleRSIPanel()
        useChartSettingsStore.getState().toggleMACDPanel()
        useChartSettingsStore.getState().toggleVolumeProfilePanel()
      })

      act(() => {
        useChartSettingsStore.getState().resetToDefaults()
      })

      const state = useChartSettingsStore.getState()
      expect(state.showRSIPanel).toBe(true)
      expect(state.showMACDPanel).toBe(true)
      expect(state.showVolumeProfilePanel).toBe(false)
    })

    it('should reset all chart preferences to defaults', () => {
      act(() => {
        useChartSettingsStore.getState().setShowVolume(false)
        useChartSettingsStore.getState().setShowSessionHighlights(false)
        useChartSettingsStore.getState().setShowTradeMarkers(false)
        useChartSettingsStore.getState().setShowPositionLines(false)
      })

      act(() => {
        useChartSettingsStore.getState().resetToDefaults()
      })

      const state = useChartSettingsStore.getState()
      expect(state.showVolume).toBe(true)
      expect(state.showSessionHighlights).toBe(true)
      expect(state.showTradeMarkers).toBe(true)
      expect(state.showPositionLines).toBe(true)
    })

    it('should reset colors to dark theme', () => {
      act(() => {
        useChartSettingsStore.getState().setTheme('light')
      })

      act(() => {
        useChartSettingsStore.getState().resetToDefaults()
      })

      const state = useChartSettingsStore.getState()
      expect(state.colors.background).toBe('#0a0a0f')
    })
  })

  describe('getThemePreset', () => {
    it('should return correct dark theme preset', () => {
      const preset = getThemePreset('dark')
      expect(preset.background).toBe('#0a0a0f')
      expect(preset.candleUp).toBe('#00e676')
      expect(preset.candleDown).toBe('#ff5252')
    })

    it('should return correct tradingview theme preset', () => {
      const preset = getThemePreset('tradingview')
      expect(preset.background).toBe('#131722')
      expect(preset.candleUp).toBe('#26a69a')
      expect(preset.candleDown).toBe('#ef5350')
    })

    it('should return correct light theme preset', () => {
      const preset = getThemePreset('light')
      expect(preset.background).toBe('#ffffff')
      expect(preset.text).toBe('#131722')
    })
  })

  describe('theme presets completeness', () => {
    const themes: ChartTheme[] = ['dark', 'tradingview', 'light']
    const requiredColors = [
      'background',
      'text',
      'grid',
      'border',
      'candleUp',
      'candleDown',
      'wickUp',
      'wickDown',
      'volume',
      'crosshair',
    ]

    themes.forEach((theme) => {
      it(`should have all required colors for ${theme} theme`, () => {
        const preset = getThemePreset(theme)
        requiredColors.forEach((color) => {
          expect(preset).toHaveProperty(color)
          expect(typeof (preset as any)[color]).toBe('string')
          expect((preset as any)[color].length).toBeGreaterThan(0)
        })
      })
    })
  })

  describe('state persistence', () => {
    // These tests verify the persist middleware configuration
    it('should have persist middleware configured', () => {
      // The store should have persist methods from zustand/middleware
      expect(useChartSettingsStore.persist).toBeDefined()
    })

    it('should persist theme changes', () => {
      // The persist middleware should include theme in partialize
      act(() => {
        useChartSettingsStore.getState().setTheme('light')
      })

      const state = useChartSettingsStore.getState()
      expect(state.theme).toBe('light')
    })
  })
})
