'use client'

import React, { useMemo } from 'react'
import Sparkline from '@/components/Sparkline'
import type { EquityCurvePoint, TradovateAccount } from '@/stores/agentStore'
import { formatPnL } from '@/lib/formatters'

interface EquityCurveStripProps {
  curve: EquityCurvePoint[]
  /** Tradovate account snapshot — the authoritative net P&L source */
  tradovate?: TradovateAccount | null
}

/**
 * Bloomberg-style equity strip.
 *
 * **Ground truth source hierarchy:**
 *   1. `tradovate.realized_pnl` — **net** of commissions, from Tradovate's
 *      /cashBalance endpoint. This is the number on the broker's screen.
 *      Used as the headline.
 *   2. `tradovate.open_pnl` — unrealized on the current position.
 *   3. `tradovate.week_realized_pnl` — week total for context.
 *   4. `curve` (agentState.equity_curve) — used only for the sparkline shape
 *      since the broker doesn't ship a historical curve directly. Its absolute
 *      values are gross (see Phase C — fix planned) but its *shape* is still
 *      representative of intra-session movement.
 *
 * When the broker is unreachable we fall back to the curve's tail value.
 */
function EquityCurveStrip({ curve, tradovate }: EquityCurveStripProps) {
  // Compute sparkline stats (shape only — absolute values are gross-biased).
  const spark = useMemo(() => {
    if (!Array.isArray(curve) || curve.length === 0) {
      return { values: [] as number[], peak: null as number | null, sessionStart: null as number | null }
    }
    const values = curve.map((p) => p.value)
    return {
      values,
      peak: Math.max(...values),
      sessionStart: values[0],
    }
  }, [curve])

  // Authoritative broker numbers — these are what the trader is accountable for.
  const brokerRealizedNet = tradovate?.realized_pnl ?? null
  const brokerOpen = tradovate?.open_pnl ?? null
  const brokerWeek = tradovate?.week_realized_pnl ?? null

  // Implied commission drag = gross-walk − broker-net.  If the curve's last
  // point represents today's running gross (which it does post Phase A fix),
  // this is the fee bite.  When the curve is empty or missing we show "—".
  const implied = useMemo(() => {
    if (spark.values.length === 0 || brokerRealizedNet == null) return null
    const gross = spark.values[spark.values.length - 1]
    const fees = gross - brokerRealizedNet
    // Only show the fee line if it's non-trivial and of the expected sign.
    if (!Number.isFinite(fees) || Math.abs(fees) < 1) return null
    return { gross, fees }
  }, [spark.values, brokerRealizedNet])

  const empty = spark.values.length < 2
  const sparkColorTrend = brokerRealizedNet != null ? brokerRealizedNet >= 0 : true

  return (
    <section className="info-strip-section info-strip-equity" aria-label="Session P&L">
      <div className="info-strip-equity-spark">
        {empty ? (
          <div className="info-strip-equity-spark-empty" aria-hidden>
            <span>—</span>
          </div>
        ) : (
          <Sparkline
            data={spark.values}
            width={132}
            height={32}
            colorByTrend={!sparkColorTrend /* invert so a negative day shows red */}
          />
        )}
      </div>
      <div className="info-strip-equity-stats">
        <div className="info-strip-equity-headline">
          <span className="info-strip-label">Day Net</span>
          <span
            className={`info-strip-equity-value ${
              brokerRealizedNet == null
                ? ''
                : brokerRealizedNet >= 0
                  ? 'positive'
                  : 'negative'
            }`}
            title="Tradovate realized_pnl — commission-deducted, broker source of truth"
          >
            {brokerRealizedNet != null ? formatPnL(brokerRealizedNet) : '—'}
          </span>
        </div>
        <div className="info-strip-equity-row">
          <span className="info-strip-mini">
            <span className="info-strip-mini-label">Open</span>
            <span
              className={`info-strip-mini-value ${
                brokerOpen == null || brokerOpen === 0
                  ? ''
                  : brokerOpen > 0
                    ? 'positive'
                    : 'negative'
              }`}
              title="Tradovate open_pnl on current position"
            >
              {brokerOpen != null ? formatPnL(brokerOpen) : '—'}
            </span>
          </span>
          <span className="info-strip-mini">
            <span className="info-strip-mini-label">Week</span>
            <span
              className={`info-strip-mini-value ${
                brokerWeek == null || brokerWeek === 0
                  ? ''
                  : brokerWeek > 0
                    ? 'positive'
                    : 'negative'
              }`}
              title="Tradovate week_realized_pnl"
            >
              {brokerWeek != null ? formatPnL(brokerWeek) : '—'}
            </span>
          </span>
          {implied && (
            <span className="info-strip-mini" title="Implied commission drag: gross walk minus broker net">
              <span className="info-strip-mini-label">Fees</span>
              <span className="info-strip-mini-value negative">
                {formatPnL(-Math.abs(implied.fees))}
              </span>
            </span>
          )}
        </div>
      </div>
    </section>
  )
}

export default React.memo(EquityCurveStrip)
