'use client'

interface DirectionStats {
  trades: number
  wins: number
  total_pnl: number
  avg_pnl: number
  avg_hold: number
  win_rate: number
}

interface Props {
  directions: Record<string, DirectionStats>
}

function formatPnL(n: number): string {
  const s = Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
  return n >= 0 ? `+$${s}` : `-$${s}`
}

export default function DirectionBreakdown({ directions }: Props) {
  const long = directions['long']
  const short = directions['short']
  if (!long && !short) return null

  const maxPnl = Math.max(Math.abs(long?.total_pnl ?? 0), Math.abs(short?.total_pnl ?? 0))

  return (
    <div className="dir-breakdown">
      {[
        { label: 'Long', data: long, className: 'dir-long' },
        { label: 'Short', data: short, className: 'dir-short' },
      ].map(({ label, data, className }) =>
        data ? (
          <div key={label} className={`dir-breakdown-col ${className}`}>
            <span className="dir-breakdown-label">{label}</span>
            <span className="dir-breakdown-pnl">{formatPnL(data.total_pnl)}</span>
            <div className="dir-breakdown-bar-track">
              <div
                className="dir-breakdown-bar-fill"
                style={{ width: `${maxPnl > 0 ? (Math.abs(data.total_pnl) / maxPnl) * 100 : 0}%` }}
              />
            </div>
            <div className="dir-breakdown-meta">
              <span>{data.trades} trades</span>
              <span>{data.win_rate}% WR</span>
              <span>avg {formatPnL(data.avg_pnl)}</span>
            </div>
          </div>
        ) : null
      )}
    </div>
  )
}
