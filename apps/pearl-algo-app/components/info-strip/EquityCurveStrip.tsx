'use client'

import React, { useMemo } from 'react'
import Sparkline from '@/components/Sparkline'
import type { EquityCurvePoint } from '@/stores/agentStore'
import { formatPnL } from '@/lib/formatters'

interface EquityCurveStripProps {
  curve: EquityCurvePoint[]
  /** Current equity (Tradovate netLiq if available) for the headline number */
  currentEquity?: number | null
}

/**
 * Slim equity curve display: sparkline + headline equity + session/peak/drawdown stats.
 *
 * Reads agentState.equity_curve directly. Each point is { time, value }.
 * Shows: peak, current drawdown from peak, change since session open.
 */
function EquityCurveStrip({ curve, currentEquity }: EquityCurveStripProps) {
  const stats = useMemo(() => {
    if (!Array.isArray(curve) || curve.length === 0) {
      return { values: [], peak: null, drawdown: null, sessionDelta: null, latest: null }
    }
    const values = curve.map((p) => p.value)
    const latest = values[values.length - 1]
    const peak = Math.max(...values)
    const drawdown = latest - peak // <= 0
    const sessionStart = values[0]
    const sessionDelta = latest - sessionStart
    return { values, peak, drawdown, sessionDelta, latest }
  }, [curve])

  const headline = currentEquity ?? stats.latest
  const empty = stats.values.length < 2

  return (
    <section className="info-strip-section info-strip-equity" aria-label="Equity curve">
      <div className="info-strip-equity-spark">
        {empty ? (
          <div className="info-strip-equity-spark-empty" aria-hidden>
            <span>—</span>
          </div>
        ) : (
          <Sparkline data={stats.values} width={132} height={32} colorByTrend />
        )}
      </div>
      <div className="info-strip-equity-stats">
        <div className="info-strip-equity-headline">
          <span className="info-strip-label">Equity</span>
          <span className="info-strip-equity-value">
            {headline != null
              ? `$${headline.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
              : '—'}
          </span>
        </div>
        <div className="info-strip-equity-row">
          <span className="info-strip-mini">
            <span className="info-strip-mini-label">Session</span>
            <span
              className={`info-strip-mini-value ${
                stats.sessionDelta == null ? '' : stats.sessionDelta >= 0 ? 'positive' : 'negative'
              }`}
            >
              {stats.sessionDelta != null ? formatPnL(stats.sessionDelta) : '—'}
            </span>
          </span>
          <span className="info-strip-mini">
            <span className="info-strip-mini-label">Peak</span>
            <span className="info-strip-mini-value">
              {stats.peak != null
                ? `$${stats.peak.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
                : '—'}
            </span>
          </span>
          <span className="info-strip-mini">
            <span className="info-strip-mini-label">DD</span>
            <span
              className={`info-strip-mini-value ${
                stats.drawdown == null || stats.drawdown === 0 ? '' : 'negative'
              }`}
              title="Drawdown from session peak"
            >
              {stats.drawdown != null && stats.drawdown < 0 ? formatPnL(stats.drawdown) : '$0.00'}
            </span>
          </span>
        </div>
      </div>
    </section>
  )
}

export default React.memo(EquityCurveStrip)
