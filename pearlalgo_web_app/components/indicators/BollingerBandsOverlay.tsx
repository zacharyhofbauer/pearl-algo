'use client'

import { useEffect, useRef } from 'react'
import type { IChartApi, ISeriesApi, Time } from 'lightweight-charts'
import type { BollingerBandsData } from '@/stores'
import { getChartColors } from '@/utils/chartColors'

interface BollingerBandsOverlayProps {
  chart: IChartApi | null
  data: BollingerBandsData[]
  visible?: boolean
}

// Colors for Bollinger Bands - from token system (U1.2)
const getBBColors = () => {
  const colors = getChartColors()
  return {
    upper: colors.bbUpper,
    middle: colors.bbMiddle,
    lower: colors.bbLower,
    fill: 'rgba(41, 98, 255, 0.1)',  // Light fill (could be tokenized later)
  }
}

export default function BollingerBandsOverlay({
  chart,
  data,
  visible = true
}: BollingerBandsOverlayProps) {
  const upperBandRef = useRef<ISeriesApi<'Line'> | null>(null)
  const middleBandRef = useRef<ISeriesApi<'Line'> | null>(null)
  const lowerBandRef = useRef<ISeriesApi<'Line'> | null>(null)
  const upperFillRef = useRef<ISeriesApi<'Area'> | null>(null)
  const lowerFillRef = useRef<ISeriesApi<'Area'> | null>(null)

  // Initialize series on chart
  useEffect(() => {
    if (!chart) return

    // Get colors from token system (U1.2)
    const BB_COLORS = getBBColors()

    // Create series for Bollinger Bands
    // Using area series for fill effect between bands

    // Upper band fill (area from middle to upper)
    const upperFill = chart.addAreaSeries({
      topColor: BB_COLORS.fill,
      bottomColor: 'transparent',
      lineColor: 'transparent',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Lower band fill (area from lower to middle)
    const lowerFill = chart.addAreaSeries({
      topColor: 'transparent',
      bottomColor: BB_COLORS.fill,
      lineColor: 'transparent',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Upper band line
    const upperBand = chart.addLineSeries({
      color: BB_COLORS.upper,
      lineWidth: 1,
      lineStyle: 0,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Middle band (SMA)
    const middleBand = chart.addLineSeries({
      color: BB_COLORS.middle,
      lineWidth: 1,
      lineStyle: 2, // dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // Lower band line
    const lowerBand = chart.addLineSeries({
      color: BB_COLORS.lower,
      lineWidth: 1,
      lineStyle: 0,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    upperBandRef.current = upperBand
    middleBandRef.current = middleBand
    lowerBandRef.current = lowerBand
    upperFillRef.current = upperFill
    lowerFillRef.current = lowerFill

    return () => {
      // Clean up series when component unmounts
      try {
        if (upperBandRef.current) chart.removeSeries(upperBandRef.current)
        if (middleBandRef.current) chart.removeSeries(middleBandRef.current)
        if (lowerBandRef.current) chart.removeSeries(lowerBandRef.current)
        if (upperFillRef.current) chart.removeSeries(upperFillRef.current)
        if (lowerFillRef.current) chart.removeSeries(lowerFillRef.current)
      } catch {
        // Chart may already be removed
      }
      upperBandRef.current = null
      middleBandRef.current = null
      lowerBandRef.current = null
      upperFillRef.current = null
      lowerFillRef.current = null
    }
  }, [chart])

  // Update data
  useEffect(() => {
    if (!upperBandRef.current || !middleBandRef.current ||
        !lowerBandRef.current || !data?.length) return

    const upperData = data.map(d => ({ time: d.time as Time, value: d.upper }))
    const middleData = data.map(d => ({ time: d.time as Time, value: d.middle }))
    const lowerData = data.map(d => ({ time: d.time as Time, value: d.lower }))

    upperBandRef.current.setData(upperData)
    middleBandRef.current.setData(middleData)
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
    const visibility = visible ? 'visible' : 'hidden'

    if (upperBandRef.current) {
      upperBandRef.current.applyOptions({
        visible: visible,
      })
    }
    if (middleBandRef.current) {
      middleBandRef.current.applyOptions({
        visible: visible,
      })
    }
    if (lowerBandRef.current) {
      lowerBandRef.current.applyOptions({
        visible: visible,
      })
    }
    if (upperFillRef.current) {
      upperFillRef.current.applyOptions({
        visible: visible,
      })
    }
    if (lowerFillRef.current) {
      lowerFillRef.current.applyOptions({
        visible: visible,
      })
    }
  }, [visible])

  // This component manages chart series, no DOM output
  return null
}

// Helper function to calculate Bollinger Bands from candle data (for standalone use)
export function calculateBollingerBands(
  closes: number[],
  times: number[],
  period: number = 20,
  stdDev: number = 2
): BollingerBandsData[] {
  const result: BollingerBandsData[] = []

  for (let i = period - 1; i < closes.length; i++) {
    // Calculate SMA
    let sum = 0
    for (let j = i - period + 1; j <= i; j++) {
      sum += closes[j]
    }
    const sma = sum / period

    // Calculate standard deviation
    let sqSum = 0
    for (let j = i - period + 1; j <= i; j++) {
      sqSum += Math.pow(closes[j] - sma, 2)
    }
    const std = Math.sqrt(sqSum / period)

    result.push({
      time: times[i],
      upper: sma + stdDev * std,
      middle: sma,
      lower: sma - stdDev * std,
    })
  }

  return result
}
