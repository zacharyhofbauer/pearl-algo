'use client'

import { useMemo } from 'react'
import type { VolumeProfile, CandleData } from '@/stores'
import { useChartSettingsStore } from '@/stores'

interface VolumeProfilePanelProps {
  data: VolumeProfile | null
  currentPrice?: number
  height?: number
}

export default function VolumeProfilePanel({
  data,
  currentPrice,
  height = 400
}: VolumeProfilePanelProps) {
  const colors = useChartSettingsStore((s) => s.colors)

  // Find max volume for scaling
  const maxVolume = useMemo(() => {
    if (!data?.levels?.length) return 0
    return Math.max(...data.levels.map(l => l.volume))
  }, [data])

  if (!data || !data.levels?.length) {
    return (
      <div className="indicator-panel volume-profile-panel">
        <div className="indicator-header">
          <div className="indicator-title">
            <span className="indicator-name">Volume Profile</span>
          </div>
        </div>
        <div className="volume-profile-empty">
          No volume profile data
        </div>
      </div>
    )
  }

  // Sort levels by price descending (highest at top)
  const sortedLevels = [...data.levels].sort((a, b) => b.price - a.price)

  return (
    <div className="indicator-panel volume-profile-panel" style={{ height: `${height}px` }}>
      <div className="indicator-header">
        <div className="indicator-title">
          <span className="indicator-name">Volume Profile</span>
          <span className="indicator-params">(Session)</span>
        </div>
        <div className="indicator-values">
          <span className="vp-stat poc">
            <span className="vp-label">POC</span>
            <span className="vp-value">{data.poc?.toFixed(2) || '-'}</span>
          </span>
          <span className="vp-stat vah">
            <span className="vp-label">VAH</span>
            <span className="vp-value">{data.vah?.toFixed(2) || '-'}</span>
          </span>
          <span className="vp-stat val">
            <span className="vp-label">VAL</span>
            <span className="vp-value">{data.val?.toFixed(2) || '-'}</span>
          </span>
        </div>
      </div>

      <div className="volume-profile-chart">
        <div className="vp-price-axis">
          {sortedLevels.filter((_, i) => i % 5 === 0).map((level) => (
            <div
              key={level.price}
              className="vp-price-label"
              style={{
                top: `${((sortedLevels[0].price - level.price) / (sortedLevels[0].price - sortedLevels[sortedLevels.length - 1].price)) * 100}%`
              }}
            >
              {level.price.toFixed(2)}
            </div>
          ))}
        </div>

        <div className="vp-bars">
          {sortedLevels.map((level) => {
            const widthPercent = maxVolume > 0 ? (level.volume / maxVolume) * 100 : 0
            const buyPercent = level.volume > 0 ? (level.buyVolume / level.volume) * 100 : 50
            const isPOC = Math.abs(level.price - data.poc) < 0.5
            const isInValueArea = level.price >= data.val && level.price <= data.vah
            const isCurrentPrice = currentPrice && Math.abs(level.price - currentPrice) < 1

            return (
              <div
                key={level.price}
                className={`vp-bar-row ${isPOC ? 'poc' : ''} ${isInValueArea ? 'value-area' : ''} ${isCurrentPrice ? 'current-price' : ''}`}
                title={`Price: ${level.price.toFixed(2)} | Vol: ${level.volume.toLocaleString()} | Buy: ${level.buyVolume.toLocaleString()} | Sell: ${level.sellVolume.toLocaleString()}`}
              >
                <div
                  className="vp-bar"
                  style={{ width: `${widthPercent}%` }}
                >
                  <div
                    className="vp-bar-buy"
                    style={{ width: `${buyPercent}%` }}
                  />
                  <div
                    className="vp-bar-sell"
                    style={{ width: `${100 - buyPercent}%` }}
                  />
                </div>
                {isPOC && <span className="vp-poc-marker">POC</span>}
              </div>
            )
          })}
        </div>

        {/* Value Area Boundaries */}
        <div className="vp-value-area-lines">
          {data.vah && sortedLevels.length > 0 && (
            <div
              className="vp-vah-line"
              style={{
                top: `${((sortedLevels[0].price - data.vah) / (sortedLevels[0].price - sortedLevels[sortedLevels.length - 1].price)) * 100}%`
              }}
            >
              <span className="vp-line-label">VAH</span>
            </div>
          )}
          {data.val && sortedLevels.length > 0 && (
            <div
              className="vp-val-line"
              style={{
                top: `${((sortedLevels[0].price - data.val) / (sortedLevels[0].price - sortedLevels[sortedLevels.length - 1].price)) * 100}%`
              }}
            >
              <span className="vp-line-label">VAL</span>
            </div>
          )}
        </div>

        {/* Current Price Line */}
        {currentPrice && sortedLevels.length > 0 && (
          <div
            className="vp-current-price-line"
            style={{
              top: `${Math.max(0, Math.min(100, ((sortedLevels[0].price - currentPrice) / (sortedLevels[0].price - sortedLevels[sortedLevels.length - 1].price)) * 100))}%`
            }}
          >
            <span className="vp-current-label">{currentPrice.toFixed(2)}</span>
          </div>
        )}
      </div>

      <div className="vp-legend">
        <span className="vp-legend-item buy">
          <span className="vp-legend-color buy"></span>
          Buy Volume
        </span>
        <span className="vp-legend-item sell">
          <span className="vp-legend-color sell"></span>
          Sell Volume
        </span>
        <span className="vp-legend-item value-area">
          <span className="vp-legend-color value-area"></span>
          Value Area (70%)
        </span>
      </div>
    </div>
  )
}

// Helper function to calculate Volume Profile from candle data
export function calculateVolumeProfile(
  candles: CandleData[],
  numLevels: number = 50,
  valueAreaPercent: number = 0.70
): VolumeProfile {
  if (!candles?.length) {
    return { levels: [], poc: 0, vah: 0, val: 0 }
  }

  // Find price range
  const allHighs = candles.map(c => c.high)
  const allLows = candles.map(c => c.low)
  const maxPrice = Math.max(...allHighs)
  const minPrice = Math.min(...allLows)
  const priceRange = maxPrice - minPrice
  const levelHeight = priceRange / numLevels

  // Initialize levels
  const levels: Map<number, { volume: number; buyVolume: number; sellVolume: number }> = new Map()
  for (let i = 0; i < numLevels; i++) {
    const levelPrice = minPrice + (levelHeight * i) + (levelHeight / 2)
    levels.set(Math.round(levelPrice * 100) / 100, { volume: 0, buyVolume: 0, sellVolume: 0 })
  }

  // Distribute volume to price levels
  for (const candle of candles) {
    const vol = candle.volume || 0
    const isBullish = candle.close >= candle.open

    // Simple distribution: assign volume to levels within the candle's range
    const candleHigh = candle.high
    const candleLow = candle.low

    levels.forEach((levelData, price) => {
      if (price >= candleLow && price <= candleHigh) {
        // Distribute volume proportionally
        const levelVol = vol / ((candleHigh - candleLow) / levelHeight || 1)
        levelData.volume += levelVol

        if (isBullish) {
          levelData.buyVolume += levelVol * 0.6  // Assume 60% buy on bullish
          levelData.sellVolume += levelVol * 0.4
        } else {
          levelData.buyVolume += levelVol * 0.4
          levelData.sellVolume += levelVol * 0.6  // Assume 60% sell on bearish
        }
      }
    })
  }

  // Convert to array and calculate POC
  const volumeLevels = Array.from(levels.entries()).map(([price, data]) => ({
    price,
    ...data
  }))

  // Find POC (Point of Control - highest volume level)
  let poc = volumeLevels[0]?.price || 0
  let maxVol = 0
  for (const level of volumeLevels) {
    if (level.volume > maxVol) {
      maxVol = level.volume
      poc = level.price
    }
  }

  // Calculate Value Area (70% of volume centered on POC)
  const totalVolume = volumeLevels.reduce((sum, l) => sum + l.volume, 0)
  const targetVolume = totalVolume * valueAreaPercent

  // Start from POC and expand outward
  const sortedByPrice = [...volumeLevels].sort((a, b) => a.price - b.price)
  const pocIndex = sortedByPrice.findIndex(l => l.price === poc)

  let cumVolume = sortedByPrice[pocIndex]?.volume || 0
  let vahIndex = pocIndex
  let valIndex = pocIndex

  while (cumVolume < targetVolume && (vahIndex < sortedByPrice.length - 1 || valIndex > 0)) {
    const upperVol = vahIndex < sortedByPrice.length - 1 ? sortedByPrice[vahIndex + 1]?.volume || 0 : 0
    const lowerVol = valIndex > 0 ? sortedByPrice[valIndex - 1]?.volume || 0 : 0

    if (upperVol >= lowerVol && vahIndex < sortedByPrice.length - 1) {
      vahIndex++
      cumVolume += sortedByPrice[vahIndex].volume
    } else if (valIndex > 0) {
      valIndex--
      cumVolume += sortedByPrice[valIndex].volume
    }
  }

  const vah = sortedByPrice[vahIndex]?.price || maxPrice
  const val = sortedByPrice[valIndex]?.price || minPrice

  return {
    levels: volumeLevels,
    poc,
    vah,
    val
  }
}
