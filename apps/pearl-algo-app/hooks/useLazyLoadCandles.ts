'use client'

import { useCallback, useEffect, useRef } from 'react'
import type { IChartApi, ITimeScaleApi, LogicalRange } from 'lightweight-charts'
import { apiFetchJson } from '@/lib/api'

/**
 * Auto-fetch older bars from the archive when the user pans the chart
 * toward the leftmost loaded bar.
 *
 * Wiring: the parent owns candle data in state. This hook listens to the
 * chart's ``subscribeVisibleLogicalRangeChange``; when the visible left
 * edge gets within ``LEFT_EDGE_THRESHOLD`` bars of index 0, it calls
 * ``/api/candles/range`` with ``to_ts = leftmost_ts - 1`` to pull the
 * next older window, and hands the result to ``onOlderBars``.
 *
 * The parent then prepends to its data array (deduping by ``time`` just
 * in case). The chart's existing data useEffect picks up the new bars
 * via ``candleSeries.setData(...)``. Before setData, we snapshot the
 * current visible logical range; after setData, we restore it — so the
 * chart doesn't jump, the user's pan is preserved, and they can keep
 * panning left to load more.
 *
 * Debounced so a continuous drag doesn't spam requests. Exits as a
 * no-op once the archive returns an empty window (end of history).
 */

export interface LazyBar {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

interface UseLazyLoadCandlesOpts {
  /** Chart instance from useChartManager / CandlestickChart onChartReady */
  chart: IChartApi | null
  /** Current bars shown in the chart; used to find the leftmost timestamp */
  data: LazyBar[]
  /** Symbol (e.g. MNQ) */
  symbol: string
  /** Timeframe ('1m', '5m', ...) */
  timeframe: string
  /** Called with older bars to be prepended to parent state */
  onOlderBars: (older: LazyBar[]) => void
  /** How many bars to fetch per lazy-load hit */
  pageSize?: number
  /** Distance (in bars) from the left edge that triggers a fetch */
  edgeThreshold?: number
}

const DEFAULT_PAGE_SIZE = 500
const DEFAULT_EDGE_THRESHOLD = 20
const DEBOUNCE_MS = 150

export function useLazyLoadCandles({
  chart,
  data,
  symbol,
  timeframe,
  onOlderBars,
  pageSize = DEFAULT_PAGE_SIZE,
  edgeThreshold = DEFAULT_EDGE_THRESHOLD,
}: UseLazyLoadCandlesOpts) {
  const fetchingRef = useRef(false)
  const exhaustedRef = useRef(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const lastFetchedCursorRef = useRef<number | null>(null)

  // Reset "exhausted" when symbol or timeframe changes — switching TF
  // is a fresh context with its own archive coverage.
  useEffect(() => {
    exhaustedRef.current = false
    lastFetchedCursorRef.current = null
  }, [symbol, timeframe])

  const tryFetchOlder = useCallback(async () => {
    if (fetchingRef.current || exhaustedRef.current) return
    if (!data.length) return

    const leftmost = data[0]
    if (!leftmost || typeof leftmost.time !== 'number') return

    // Deduplicate: don't refetch the same cursor twice in a row.
    if (lastFetchedCursorRef.current === leftmost.time) return
    lastFetchedCursorRef.current = leftmost.time

    const toTs = leftmost.time - 1
    const url =
      `/api/candles/range?symbol=${encodeURIComponent(symbol)}` +
      `&timeframe=${encodeURIComponent(timeframe)}` +
      `&to_ts=${toTs}&limit=${pageSize}`

    fetchingRef.current = true
    try {
      const older = await apiFetchJson<LazyBar[]>(url)
      if (!Array.isArray(older) || older.length === 0) {
        exhaustedRef.current = true
        return
      }
      onOlderBars(older)
    } catch (err) {
      // Silently stop on error — user can keep live chart working. We
      // don't mark exhausted on error so a transient 503/timeout will
      // be retried on the next pan.
      console.warn('[lazy-load] /api/candles/range failed', err)
      lastFetchedCursorRef.current = null
    } finally {
      fetchingRef.current = false
    }
  }, [data, symbol, timeframe, pageSize, onOlderBars])

  // Subscribe to visible-range changes and trigger debounced fetches.
  useEffect(() => {
    if (!chart) return

    const timeScale: ITimeScaleApi<any> = chart.timeScale()

    const handler = (range: LogicalRange | null) => {
      if (!range) return
      if (range.from > edgeThreshold) return

      if (debounceRef.current) clearTimeout(debounceRef.current)
      debounceRef.current = setTimeout(() => {
        tryFetchOlder()
      }, DEBOUNCE_MS)
    }

    timeScale.subscribeVisibleLogicalRangeChange(handler)
    return () => {
      timeScale.unsubscribeVisibleLogicalRangeChange(handler)
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [chart, edgeThreshold, tryFetchOlder])
}

/**
 * Merge a batch of older bars into a rolling array in ascending time
 * order, deduping by ``time``. Mutates nothing — returns a fresh array.
 * Exported separately so parents can call it from their setState
 * updater without a closure over hook state.
 */
export function mergeOlderBars(existing: LazyBar[], older: LazyBar[]): LazyBar[] {
  if (older.length === 0) return existing
  const seen = new Set<number>()
  const merged: LazyBar[] = []
  // Older bars are ascending from the API; existing is ascending too.
  for (const b of older) {
    if (seen.has(b.time)) continue
    seen.add(b.time)
    merged.push(b)
  }
  for (const b of existing) {
    if (seen.has(b.time)) continue
    seen.add(b.time)
    merged.push(b)
  }
  // Ensure final order (defensive — inputs should already be sorted).
  merged.sort((a, b) => a.time - b.time)
  return merged
}
