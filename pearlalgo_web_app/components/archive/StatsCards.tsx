'use client'

interface StatsCardsProps {
  totalPnl: number
  totalTrades: number
  winRate: number
  bestDay?: number
  bestDayDate?: string
  worstDay?: number
  worstDayDate?: string
  profitFactor?: number
  expectancy?: number
  avgHoldMinutes?: number
}

function formatPnL(n: number): string {
  const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return n >= 0 ? `+$${s}` : `-$${s}`
}

function formatHold(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)}m`
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  return m > 0 ? `${h}h ${m}m` : `${h}h`
}

function formatShortDate(dateStr: string): string {
  try {
    const d = new Date(dateStr + 'T00:00:00')
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  } catch {
    return dateStr
  }
}

export default function StatsCards({
  totalPnl, totalTrades, winRate, bestDay, bestDayDate,
  worstDay, worstDayDate, profitFactor, expectancy, avgHoldMinutes,
}: StatsCardsProps) {
  return (
    <div className="archive-stats-grid">
      <div className={`archive-stat-card ${totalPnl >= 0 ? 'positive' : 'negative'}`}>
        <span className="archive-stat-label">Total P&L</span>
        <span className="archive-stat-value">{formatPnL(totalPnl)}</span>
      </div>
      <div className="archive-stat-card">
        <span className="archive-stat-label">Win Rate</span>
        <span className="archive-stat-value">{winRate.toFixed(1)}%</span>
      </div>
      <div className="archive-stat-card">
        <span className="archive-stat-label">Profit Factor</span>
        <span className={`archive-stat-value ${(profitFactor ?? 0) >= 1 ? 'positive' : 'negative'}`}>
          {profitFactor != null ? profitFactor.toFixed(2) : '—'}
        </span>
      </div>
      <div className="archive-stat-card">
        <span className="archive-stat-label">Expectancy</span>
        <span className={`archive-stat-value ${(expectancy ?? 0) >= 0 ? 'positive' : 'negative'}`}>
          {expectancy != null ? formatPnL(expectancy) : '—'}
        </span>
      </div>
      <div className="archive-stat-card">
        <span className="archive-stat-label">Trades</span>
        <span className="archive-stat-value">{totalTrades.toLocaleString()}</span>
      </div>
      <div className="archive-stat-card">
        <span className="archive-stat-label">Avg Hold</span>
        <span className="archive-stat-value">
          {avgHoldMinutes != null ? formatHold(avgHoldMinutes) : '—'}
        </span>
      </div>
      {bestDay != null && (
        <div className="archive-stat-card positive">
          <span className="archive-stat-label">
            Best Day{bestDayDate ? ` (${formatShortDate(bestDayDate)})` : ''}
          </span>
          <span className="archive-stat-value">{formatPnL(bestDay)}</span>
        </div>
      )}
      {worstDay != null && (
        <div className="archive-stat-card negative">
          <span className="archive-stat-label">
            Worst Day{worstDayDate ? ` (${formatShortDate(worstDayDate)})` : ''}
          </span>
          <span className="archive-stat-value">{formatPnL(worstDay)}</span>
        </div>
      )}
    </div>
  )
}
