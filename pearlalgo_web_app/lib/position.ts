import type { Position } from '@/stores'

/** MNQ: $2 per point (1 point = 4 ticks at $0.50 per tick) */
export const MNQ_POINT_VALUE = 2.0

/**
 * Calculate unrealized P&L for a position.
 *
 * @param position - The position to calculate P&L for
 * @param currentPrice - Current market price (null/undefined returns null)
 * @param pointValue - Dollar value per point movement (default: MNQ_POINT_VALUE)
 * @returns Unrealized P&L in dollars, or null if currentPrice is unavailable
 */
export function calculateUnrealizedPnL(
  position: Position,
  currentPrice: number | null | undefined,
  pointValue: number = MNQ_POINT_VALUE
): number | null {
  if (currentPrice == null) return null
  const priceDiff = currentPrice - position.entry_price
  const directionMultiplier = position.direction === 'long' ? 1 : -1
  return priceDiff * directionMultiplier * pointValue
}
