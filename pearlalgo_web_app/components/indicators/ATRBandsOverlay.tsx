'use client'

import { useEffect, useRef } from 'react'
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import type { ATRBandsData } from '@/stores'
import { getChartColors } from '@/utils/chartColors'

interface ATRBandsOverlayProps {
  chart: IChartApi | null
  data: ATRBandsData[]
  visible?: boolean
}

// Colors for ATR Bands - from token system (U1.2)
const getATRColors = () => {
  const colors = getChartColors()
  return {
    upper: colors.atrUpper,
    lower: colors.atrLower,
    fill: 'rgba(255, 152, 0, 0.08)',  // Light fill (could be tokenized later)
  }
}

export default function ATRBandsOverlay({
  chart,
  data,
  visible = true
}: ATRBandsOverlayProps) {
  const upperBandRef = useRef<ISeriesApi<'Line'> | null>(null)
  const lowerBandRef = useRef<ISeriesApi<'Line'> | null>(null)
  const upperFillRef = useRef<ISeriesApi<'Area'> | null>(null)
  const lowerFillRef = useRef<ISeriesApi<'Area'> | null>(null)

  // Initialize series on chart
  useEffect(() => {
    if (!chart) return

    // Get colors from token system (U1.2)
    const ATR_COLORS = getATRColors()

    // Upper band fill (area)
    const upperFill = chart.addAreaSeries({
      topColor: ATR_COLORS.fill,
      bottomColor: 'transparent',
      lineColor: 'transparent',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Lower band fill (area)
    const lowerFill = chart.addAreaSeries({
      topColor: 'transparent',
      bottomColor: ATR_COLORS.fill,
      lineColor: 'transparent',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Upper band line
    const upperBand = chart.addLineSeries({
      color: ATR_COLORS.upper,
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Lower band line
    const lowerBand = chart.addLineSeries({
      color: ATR_COLORS.lower,
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    upperBandRef.current = upperBand
    lowerBandRef.current = lowerBand
    upperFillRef.current = upperFill
    lowerFillRef.current = lowerFill

    return () => {
      try {
        if (upperBandRef.current) chart.removeSeries(upperBandRef.current)
        if (lowerBandRef.current) chart.removeSeries(lowerBandRef.current)
        if (upperFillRef.current) chart.removeSeries(upperFillRef.current)
        if (lowerFillRef.current) chart.removeSeries(lowerFillRef.current)
      } catch {
        // Chart may already be removed
      }
      upperBandRef.current = null
      lowerBandRef.current = null
      upperFillRef.current = null
      lowerFillRef.current = null
    }
  }, [chart])

  // Update data
  useEffect(() => {
    if (!upperBandRef.current || !lowerBandRef.current || !data?.length) return

    const upperData = data.map(d => ({ time: d.time as Time, value: d.upper }))
    const lowerData = data.map(d => ({ time: d.time as Time, value: d.lower }))

    upperBandRef.current.setData(upperData)
    lowerBandRef.current.setData(lowerData)

    // Update fill areas
    if (upperFillRef.current) {
      upperFillRef.current.setData(upperData)
    }
    if (lowerFillRef.current) {
      lowerFillRef.current.setData(lowerData)
    }
  }, [data])

  // Update visibility
  useEffect(() => {
    if (upperBandRef.current) {
      upperBandRef.current.applyOptions({ visible })
    }
    if (lowerBandRef.current) {
      lowerBandRef.current.applyOptions({ visible })
    }
    if (upperFillRef.current) {
      upperFillRef.current.applyOptions({ visible })
    }
    if (lowerFillRef.current) {
      lowerFillRef.current.applyOptions({ visible })
    }
  }, [visible])

  // This component manages chart series, no DOM output
  return null
}

// Helper function to calculate ATR and ATR Bands from candle data
export function calculateATRBands(
  highs: number[],
  lows: number[],
  closes: number[],
  times: number[],
  period: number = 14,
  multiplier: number = 2
): ATRBandsData[] {
  const result: ATRBandsData[] = []

  // Calculate True Range and ATR
  const trueRanges: number[] = []

  for (let i = 0; i < closes.length; i++) {
    if (i === 0) {
      trueRanges.push(highs[i] - lows[i])
    } else {
      const tr = Math.max(
        highs[i] - lows[i],
        Math.abs(highs[i] - closes[i - 1]),
        Math.abs(lows[i] - closes[i - 1])
      )
      trueRanges.push(tr)
    }
  }

  // Calculate ATR using EMA
  let atr = 0
  for (let i = 0; i < closes.length; i++) {
    if (i < period) {
      // Build up initial ATR (simple average)
      if (i === period - 1) {
        let sum = 0
        for (let j = 0; j < period; j++) {
          sum += trueRanges[j]
        }
        atr = sum / period
      }
    } else {
      // EMA-style ATR calculation
      atr = ((atr * (period - 1)) + trueRanges[i]) / period
    }

    if (i >= period - 1) {
      const midpoint = (highs[i] + lows[i] + closes[i]) / 3  // Typical price

      result.push({
        time: times[i],
        upper: midpoint + (multiplier * atr),
        lower: midpoint - (multiplier * atr),
        atr: atr,
      })
    }
  }

  return result
}
