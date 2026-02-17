'use client'

interface ExitReason {
  reason: string
  count: number
}

interface Props {
  reasons: ExitReason[]
  total: number
}

const REASON_COLORS: Record<string, string> = {
  take_profit: 'var(--accent-green)',
  stop_loss: 'var(--accent-red)',
  close_all_requested: 'var(--accent-yellow)',
  daily_auto_flat: 'var(--accent-cyan)',
  weekend_flatten: 'var(--accent-purple)',
  manual_close_requested: 'var(--text-tertiary)',
}

const REASON_LABELS: Record<string, string> = {
  take_profit: 'Take Profit',
  stop_loss: 'Stop Loss',
  close_all_requested: 'Close All',
  daily_auto_flat: 'Daily Flat',
  weekend_flatten: 'Weekend Flat',
  manual_close_requested: 'Manual',
}

export default function ExitReasonBar({ reasons, total }: Props) {
  if (!reasons.length || total === 0) return null

  return (
    <div className="exit-reason-breakdown">
      <div className="exit-reason-bar">
        {reasons.map((r) => (
          <div
            key={r.reason}
            className="exit-reason-segment"
            style={{
              width: `${(r.count / total) * 100}%`,
              backgroundColor: REASON_COLORS[r.reason] ?? 'var(--text-muted)',
            }}
            title={`${REASON_LABELS[r.reason] ?? r.reason}: ${r.count} (${((r.count / total) * 100).toFixed(1)}%)`}
          />
        ))}
      </div>
      <div className="exit-reason-legend">
        {reasons.map((r) => (
          <span key={r.reason} className="exit-reason-item">
            <span
              className="exit-reason-dot"
              style={{ backgroundColor: REASON_COLORS[r.reason] ?? 'var(--text-muted)' }}
            />
            <span className="exit-reason-name">{REASON_LABELS[r.reason] ?? r.reason}</span>
            <span className="exit-reason-count">{r.count}</span>
          </span>
        ))}
      </div>
    </div>
  )
}
