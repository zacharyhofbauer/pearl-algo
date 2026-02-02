'use client'

import { memo, useMemo } from 'react'
import type { Position } from '@/stores'
import { calculateUnrealizedPnL, MNQ_POINT_VALUE } from '@/lib/position'

interface PositionsStripProps {
  positions: Position[]
  latestPrice: number | null
  pointValue?: number // Dollar value per point (default: MNQ_POINT_VALUE = $2)
}

interface PositionCardProps {
  position: Position
  latestPrice: number | null
  pointValue: number
}

// Calculate distance in points
function calculateDistance(from: number, to: number | undefined): number | null {
  if (to === undefined) return null
  return Math.abs(to - from)
}

// Format time in trade
function formatTimeInTrade(entryTime: string | undefined): string {
  if (!entryTime) return '--'

  try {
    const entry = new Date(entryTime)
    const now = new Date()
    const diffMs = now.getTime() - entry.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return '<1m'
    if (diffMins < 60) return `${diffMins}m`

    const hours = Math.floor(diffMins / 60)
    const mins = diffMins % 60
    if (hours < 24) return `${hours}h ${mins}m`

    const days = Math.floor(hours / 24)
    const remainingHours = hours % 24
    return `${days}d ${remainingHours}h`
  } catch {
    return '--'
  }
}

// Calculate Risk/Reward ratio
function calculateRiskReward(
  position: Position,
  latestPrice: number | null
): { risk: number | null; reward: number | null; ratio: number | null } {
  if (!position.stop_loss || !position.take_profit) {
    return { risk: null, reward: null, ratio: null }
  }

  const entryPrice = position.entry_price
  const sl = position.stop_loss
  const tp = position.take_profit

  const risk = Math.abs(entryPrice - sl)
  const reward = Math.abs(tp - entryPrice)
  const ratio = risk > 0 ? reward / risk : null

  return { risk, reward, ratio }
}

// Individual position card component
const PositionCard = memo(function PositionCard({
  position,
  latestPrice,
  pointValue,
}: PositionCardProps) {
  const unrealizedPnL = useMemo(
    () => calculateUnrealizedPnL(position, latestPrice, pointValue),
    [position, latestPrice, pointValue]
  )

  const slDistance = useMemo(
    () => calculateDistance(position.entry_price, position.stop_loss),
    [position.entry_price, position.stop_loss]
  )

  const tpDistance = useMemo(
    () => calculateDistance(position.entry_price, position.take_profit),
    [position.entry_price, position.take_profit]
  )

  const timeInTrade = useMemo(
    () => formatTimeInTrade(position.entry_time),
    [position.entry_time]
  )

  const riskReward = useMemo(
    () => calculateRiskReward(position, latestPrice),
    [position, latestPrice]
  )

  const isLong = position.direction === 'long'
  const isProfitable = unrealizedPnL !== null && unrealizedPnL >= 0

  return (
    <div className="position-card">
      {/* Direction Badge */}
      <div className={`position-direction ${isLong ? 'long' : 'short'}`}>
        <span className="direction-arrow">{isLong ? '↑' : '↓'}</span>
        <span className="direction-label">{isLong ? 'LONG' : 'SHORT'}</span>
      </div>

      {/* Price Info */}
      <div className="position-prices">
        <div className="price-row">
          <span className="price-label">Entry</span>
          <span className="price-value">{position.entry_price.toFixed(2)}</span>
        </div>
        {latestPrice !== null && (
          <div className="price-row">
            <span className="price-label">Current</span>
            <span className="price-value">{latestPrice.toFixed(2)}</span>
          </div>
        )}
      </div>

      {/* Unrealized P&L */}
      <div className={`position-pnl ${isProfitable ? 'profit' : 'loss'}`}>
        <span className="pnl-label">Unrealized</span>
        <span className="pnl-value">
          {unrealizedPnL !== null
            ? `${unrealizedPnL >= 0 ? '+' : ''}$${unrealizedPnL.toFixed(2)}`
            : '--'}
        </span>
      </div>

      {/* SL/TP Distances */}
      <div className="position-levels">
        <div className="level-item sl">
          <span className="level-label">SL</span>
          <span className="level-value">
            {slDistance !== null ? `${slDistance.toFixed(2)} pts` : '--'}
          </span>
        </div>
        <div className="level-item tp">
          <span className="level-label">TP</span>
          <span className="level-value">
            {tpDistance !== null ? `${tpDistance.toFixed(2)} pts` : '--'}
          </span>
        </div>
      </div>

      {/* Time & R:R */}
      <div className="position-meta">
        <div className="meta-item">
          <span className="meta-label">Time</span>
          <span className="meta-value">{timeInTrade}</span>
        </div>
        {riskReward.ratio !== null && (
          <div className="meta-item">
            <span className="meta-label">R:R</span>
            <span className="meta-value">1:{riskReward.ratio.toFixed(1)}</span>
          </div>
        )}
      </div>

      {/* Risk/Reward Progress Bar */}
      {riskReward.risk !== null && riskReward.reward !== null && latestPrice !== null && (
        <div className="rr-bar-container">
          <RiskRewardBar
            position={position}
            latestPrice={latestPrice}
            risk={riskReward.risk}
            reward={riskReward.reward}
          />
        </div>
      )}
    </div>
  )
})

// Risk/Reward visualization bar
const RiskRewardBar = memo(function RiskRewardBar({
  position,
  latestPrice,
  risk,
  reward,
}: {
  position: Position
  latestPrice: number
  risk: number
  reward: number
}) {
  // Calculate position in the SL->TP range
  const sl = position.stop_loss!
  const tp = position.take_profit!
  const entry = position.entry_price

  const totalRange = risk + reward
  const riskPercent = (risk / totalRange) * 100

  // Calculate where current price sits
  let progressPercent: number
  if (position.direction === 'long') {
    // Long: SL < Entry < TP
    progressPercent = ((latestPrice - sl) / (tp - sl)) * 100
  } else {
    // Short: TP < Entry < SL
    progressPercent = ((sl - latestPrice) / (sl - tp)) * 100
  }

  // Clamp to 0-100
  progressPercent = Math.max(0, Math.min(100, progressPercent))

  return (
    <div className="rr-bar">
      <div className="rr-bar-risk" style={{ width: `${riskPercent}%` }} />
      <div className="rr-bar-reward" style={{ width: `${100 - riskPercent}%` }} />
      <div
        className="rr-bar-marker entry"
        style={{ left: `${riskPercent}%` }}
        title={`Entry: ${entry.toFixed(2)}`}
      />
      <div
        className="rr-bar-marker current"
        style={{ left: `${progressPercent}%` }}
        title={`Current: ${latestPrice.toFixed(2)}`}
      />
    </div>
  )
})

// Main PositionsStrip component
function PositionsStrip({
  positions,
  latestPrice,
  pointValue = MNQ_POINT_VALUE,
}: PositionsStripProps) {
  if (positions.length === 0) {
    return null // Don't render if no positions
  }

  return (
    <div className="positions-strip">
      <div className="positions-strip-header">
        <span className="strip-title">Open Positions</span>
        <span className="strip-count">{positions.length}</span>
      </div>
      <div className="positions-strip-content">
        {positions.map((position) => (
          <PositionCard
            key={position.signal_id}
            position={position}
            latestPrice={latestPrice}
            pointValue={pointValue}
          />
        ))}
      </div>
    </div>
  )
}

export default memo(PositionsStrip)
