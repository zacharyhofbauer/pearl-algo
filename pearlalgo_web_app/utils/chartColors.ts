/**
 * Chart Colors Utility (U1.2)
 *
 * Provides chart colors that read from CSS custom properties.
 * This allows charts (which need JS color strings) to stay in sync
 * with the design token system.
 *
 * Usage:
 *   import { getChartColors, getSessionColor } from '@/utils/chartColors'
 *   const colors = getChartColors()
 *   chart.applyOptions({ layout: { background: colors.background } })
 */

/**
 * Read a CSS custom property value from :root
 */
function getCSSVar(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

/**
 * Read an RGB CSS variable and return as rgba() string
 */
function getCSSVarRgba(name: string, alpha: number, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  if (!value) return fallback
  return `rgba(${value}, ${alpha})`
}

/**
 * Get session background color based on hour (UTC)
 * Uses CSS session color tokens with low opacity for chart backgrounds
 */
export function getSessionColor(hour: number): string {
  // Map UTC hours to trading sessions
  // Overnight/Pre-Market (23:00-08:00 UTC)
  if (hour >= 23 || hour < 8) {
    return getCSSVarRgba('--session-overnight-rgb', 0.08, 'rgba(147, 112, 219, 0.08)')
  }
  // London (08:00-14:00 UTC)
  if (hour >= 8 && hour < 14) {
    return getCSSVarRgba('--session-london-rgb', 0.08, 'rgba(0, 212, 255, 0.08)')
  }
  // NY RTH (14:00-21:00 UTC)
  if (hour >= 14 && hour < 21) {
    return getCSSVarRgba('--session-us-open-rgb', 0.08, 'rgba(0, 230, 118, 0.08)')
  }
  // Extended (21:00-23:00 UTC)
  return getCSSVarRgba('--session-extended-rgb', 0.06, 'rgba(106, 90, 205, 0.06)')
}

/**
 * Chart color palette - reads from CSS tokens
 * Call this once when initializing the chart
 */
export interface ChartColors {
  // Layout
  background: string
  textColor: string
  gridColor: string
  borderColor: string

  // Candles
  candleUp: string
  candleDown: string
  wickUp: string
  wickDown: string

  // Volume
  volumeUp: string
  volumeDown: string

  // Indicators
  ema9: string
  ema21: string
  vwap: string

  // Bollinger Bands
  bbUpper: string
  bbMiddle: string
  bbLower: string

  // ATR Bands
  atrUpper: string
  atrLower: string

  // Crosshair
  crosshairLine: string
  crosshairLabel: string

  // Price line
  priceLineColor: string

  // Connection line (trade highlight)
  connectionWin: string
  connectionLoss: string

  // Markers
  markerEntry: string
  markerWin: string
  markerLoss: string
  markerGroupWin: string
  markerGroupLoss: string
  markerGroupEntry: string

  // RSI Panel
  rsiLine: string
  rsiOverbought: string
  rsiOversold: string
  rsiMidline: string

  // MACD Panel
  macdLine: string
  macdSignal: string
  macdHistogramUp: string
  macdHistogramUpFade: string
  macdHistogramDown: string
  macdHistogramDownFade: string
  macdZeroLine: string

  // Equity Curve
  equityLineUp: string
  equityLineDown: string
  equityAreaUpTop: string
  equityAreaUpBottom: string
  equityAreaDownTop: string
  equityAreaDownBottom: string

  // Position Lines
  positionLong: string
  positionShort: string
  positionSL: string
  positionTP: string
}

export function getChartColors(): ChartColors {
  return {
    // Layout
    background: getCSSVar('--bg-primary', '#0a0a0f'),
    textColor: getCSSVar('--text-tertiary', '#8a94a6'),
    gridColor: getCSSVar('--grid-color', '#1e222d'),
    borderColor: getCSSVar('--border-color', '#2a2a3a'),

    // Candles
    candleUp: getCSSVar('--accent-green', '#00e676'),
    candleDown: getCSSVar('--accent-red', '#ff5252'),
    wickUp: getCSSVar('--accent-green', '#00e676'),
    wickDown: getCSSVar('--accent-red', '#ff5252'),

    // Volume
    volumeUp: getCSSVarRgba('--accent-green-rgb', 0.3, 'rgba(0, 230, 118, 0.3)'),
    volumeDown: getCSSVarRgba('--accent-red-rgb', 0.3, 'rgba(255, 82, 82, 0.3)'),

    // Indicators
    ema9: getCSSVar('--accent-cyan', '#00d4ff'),
    ema21: getCSSVar('--accent-yellow', '#ffc107'),
    vwap: '#2962ff', // Blue - consider adding token

    // Bollinger Bands (blue, semi-transparent)
    bbUpper: 'rgba(41, 98, 255, 0.5)',
    bbMiddle: 'rgba(41, 98, 255, 0.8)',
    bbLower: 'rgba(41, 98, 255, 0.5)',

    // ATR Bands (orange, semi-transparent)
    atrUpper: getCSSVarRgba('--session-afternoon-rgb', 0.5, 'rgba(255, 152, 0, 0.5)'),
    atrLower: getCSSVarRgba('--session-afternoon-rgb', 0.5, 'rgba(255, 152, 0, 0.5)'),

    // Crosshair
    crosshairLine: '#758696',
    crosshairLabel: getCSSVar('--border-color', '#2a2a3a'),

    // Price line (gold/yellow, subtle)
    priceLineColor: 'rgba(255, 215, 0, 0.35)',

    // Connection line (trade highlight)
    connectionWin: '#00ff88',
    connectionLoss: '#ff3333',

    // Markers
    markerEntry: 'rgba(180, 180, 180, 0.9)',
    markerWin: 'rgba(100, 200, 180, 0.9)',
    markerLoss: 'rgba(220, 140, 100, 0.9)',
    markerGroupWin: 'rgba(100, 200, 180, 0.9)',
    markerGroupLoss: 'rgba(220, 140, 100, 0.9)',
    markerGroupEntry: 'rgba(180, 180, 180, 0.9)',

    // RSI Panel
    rsiLine: getCSSVar('--accent-purple', '#ab47bc'),
    rsiOverbought: getCSSVarRgba('--accent-red-rgb', 0.6, 'rgba(255, 82, 82, 0.6)'),
    rsiOversold: getCSSVarRgba('--accent-green-rgb', 0.6, 'rgba(0, 230, 118, 0.6)'),
    rsiMidline: 'rgba(255, 255, 255, 0.2)',

    // MACD Panel
    macdLine: '#2196F3',  // Blue
    macdSignal: getCSSVar('--session-afternoon', '#ff9800'),  // Orange
    macdHistogramUp: '#26a69a',
    macdHistogramUpFade: '#1e8c7e',
    macdHistogramDown: getCSSVar('--accent-red', '#ef5350'),
    macdHistogramDownFade: '#c62828',
    macdZeroLine: 'rgba(255, 255, 255, 0.3)',

    // Equity Curve
    equityLineUp: getCSSVar('--accent-green', '#00e676'),
    equityLineDown: getCSSVar('--accent-red', '#ff5252'),
    equityAreaUpTop: getCSSVarRgba('--accent-green-rgb', 0.3, 'rgba(0, 230, 118, 0.3)'),
    equityAreaUpBottom: getCSSVarRgba('--accent-green-rgb', 0.0, 'rgba(0, 230, 118, 0.0)'),
    equityAreaDownTop: getCSSVarRgba('--accent-red-rgb', 0.3, 'rgba(255, 82, 82, 0.3)'),
    equityAreaDownBottom: getCSSVarRgba('--accent-red-rgb', 0.0, 'rgba(255, 82, 82, 0.0)'),

    // Position Lines
    positionLong: 'rgba(33, 150, 243, 0.55)',  // Blue
    positionShort: 'rgba(156, 39, 176, 0.55)', // Purple
    positionSL: 'rgba(244, 67, 54, 0.55)',     // Red
    positionTP: 'rgba(76, 175, 80, 0.55)',     // Green
  }
}

/**
 * Get marker color based on trade type and outcome
 */
export function getMarkerColor(
  kind: 'entry' | 'exit',
  pnl?: number,
  isGrouped?: boolean
): string {
  const colors = getChartColors()

  if (kind === 'entry') {
    return isGrouped ? colors.markerGroupEntry : colors.markerEntry
  }

  // Exit marker
  const isWin = (pnl || 0) >= 0
  if (isGrouped) {
    return isWin ? colors.markerGroupWin : colors.markerGroupLoss
  }
  return isWin ? colors.markerWin : colors.markerLoss
}

/**
 * Get profit/loss color with dynamic alpha (for heatmaps, intensity displays)
 */
export function getPnLColor(pnl: number, alpha: number = 1): string {
  if (pnl > 0) {
    return getCSSVarRgba('--accent-green-rgb', alpha, `rgba(0, 230, 118, ${alpha})`)
  } else if (pnl < 0) {
    return getCSSVarRgba('--accent-red-rgb', alpha, `rgba(255, 82, 82, ${alpha})`)
  }
  return 'transparent'
}

/**
 * Default export for convenience
 */
export default {
  getChartColors,
  getSessionColor,
  getMarkerColor,
  getPnLColor,
}
