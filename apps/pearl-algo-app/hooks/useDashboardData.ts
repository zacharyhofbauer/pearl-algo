'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAgentStore, useChartStore, useUIStore } from '@/stores'
import type { Timeframe, DataSource, Position } from '@/stores'
import type { RecentTradeRow, PerformanceSummary, RecentSignalEvent } from '@/components/TradeDockPanel'
import { apiFetch } from '@/lib/api'

const REFRESH_INTERVAL = 10000 // 10 seconds when HTTP remains the primary live path
const WS_REFRESH_INTERVAL = 30000 // 30 seconds for socket-backed steady state
const ANALYTICS_REFRESH_INTERVAL = 120000 // slower-changing trade-dock analytics
const MIN_BARS = 500
const MARKER_HOURS = 72
const FETCH_TIMEOUT_MS = 10000 // 10 seconds
const RETRY_DELAY_MS = 2000 // 2 seconds

type DashboardResponse = Response | null
type DashboardResponses = [
  DashboardResponse,
  DashboardResponse,
  DashboardResponse,
  DashboardResponse,
  DashboardResponse,
  DashboardResponse,
  DashboardResponse,
  DashboardResponse,
  DashboardResponse,
  DashboardResponse,
]

function restoreLastGoodArray<T>(
  lastGoodRef: { current: T[] },
  setValue: (value: T[]) => void
): void {
  if (lastGoodRef.current.length > 0) {
    setValue(lastGoodRef.current)
  }
}

async function applyArrayResponse<T>(
  response: DashboardResponse,
  lastGoodRef: { current: T[] },
  setValue: (value: T[]) => void
): Promise<void> {
  if (!response?.ok) {
    restoreLastGoodArray(lastGoodRef, setValue)
    return
  }

  try {
    const data = await response.json()
    const nextValue = Array.isArray(data) ? data : []
    setValue(nextValue)
    lastGoodRef.current = nextValue
  } catch {
    restoreLastGoodArray(lastGoodRef, setValue)
  }
}

async function applyNullableResponse<T>(
  response: DashboardResponse,
  lastGoodRef: { current: T | null },
  setValue: (value: T | null) => void
): Promise<void> {
  if (!response?.ok) {
    setValue(lastGoodRef.current)
    return
  }

  try {
    const nextValue = (await response.json()) || null
    setValue(nextValue)
    lastGoodRef.current = nextValue
  } catch {
    setValue(lastGoodRef.current)
  }
}

interface UseDashboardDataOptions {
  timeframe: Timeframe
  barCount: number
  wsStatus: 'connecting' | 'connected' | 'disconnected' | 'error'
}

interface UseDashboardDataReturn {
  positions: Position[]
  recentTrades: RecentTradeRow[]
  recentSignals: RecentSignalEvent[]
  performanceSummary: PerformanceSummary | null
  handleTradeRefresh: () => void
  // Callbacks for WebSocket message handlers to update state
  updatePositions: (positions: Position[]) => void
  updateRecentTrades: (trades: RecentTradeRow[]) => void
  updatePerformanceSummary: (summary: PerformanceSummary | null) => void
}

/**
 * Hook for managing dashboard data fetching (HTTP polling fallback).
 * Handles WebSocket message dispatch, data hash deduplication, and state management.
 * Includes AbortController, timeout, retry logic, and preserve-last-good-state.
 */
export function useDashboardData({
  timeframe,
  barCount,
  wsStatus,
}: UseDashboardDataOptions): UseDashboardDataReturn {
  const agentState = useAgentStore((s) => s.agentState)
  const setAgentState = useAgentStore((s) => s.setAgentState)
  
  const candles = useChartStore((s) => s.candles)
  const setCandles = useChartStore((s) => s.setCandles)
  const setIndicators = useChartStore((s) => s.setIndicators)
  const setMarkers = useChartStore((s) => s.setMarkers)
  const setMarketStatus = useChartStore((s) => s.setMarketStatus)
  const setChartError = useChartStore((s) => s.setError)
  const setChartLoading = useChartStore((s) => s.setLoading)
  
  const setIsLive = useUIStore((s) => s.setIsLive)
  const setIsFetching = useUIStore((s) => s.setIsFetching)
  const recordFetch = useUIStore((s) => s.recordFetch)
  
  // Local state for positions, trades, and performance summary
  const [positions, setPositions] = useState<Position[]>([])
  const [recentTrades, setRecentTrades] = useState<RecentTradeRow[]>([])
  const [recentSignals, setRecentSignals] = useState<RecentSignalEvent[]>([])
  const [performanceSummary, setPerformanceSummary] = useState<PerformanceSummary | null>(null)
  
  // Use refs to preserve last-good state
  const lastGoodPositionsRef = useRef<Position[]>([])
  const lastGoodTradesRef = useRef<RecentTradeRow[]>([])
  const lastGoodSignalsRef = useRef<RecentSignalEvent[]>([])
  const lastGoodPerformanceRef = useRef<PerformanceSummary | null>(null)
  
  const lastDataHashRef = useRef('')
  const lastAnalyticsFetchRef = useRef(0)
  const fetchStartRef = useRef<number>(0)
  const abortControllerRef = useRef<AbortController | null>(null)
  const mountedRef = useRef(true)

  // Fetch data with timeout, retry, and abort support
  const fetchData = useCallback(async (tf: Timeframe, bars: number, retryCount = 0) => {
    // Abort previous request if still pending
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
    }
    
    // Create new AbortController for this request
    const abortController = new AbortController()
    abortControllerRef.current = abortController
    
    if (!mountedRef.current) return
    
    fetchStartRef.current = performance.now()
    setIsFetching(true)

    try {
      const requestBars = Math.max(MIN_BARS, bars)
      const sym = agentState?.config?.symbol || 'MNQ'

      // Set up timeout to abort all requests
      const timeoutId = setTimeout(() => {
        abortController.abort()
      }, FETCH_TIMEOUT_MS)

      const includeSocketOwnedData = wsStatus !== 'connected'
      const nowMs = Date.now()
      const shouldFetchAnalytics =
        wsStatus !== 'connected' ||
        nowMs - lastAnalyticsFetchRef.current >= ANALYTICS_REFRESH_INTERVAL

      // Fetch all data in parallel with abort support.
      // When the WebSocket is healthy, it owns the hot state/trades/positions
      // paths and HTTP only refreshes colder chart/supporting resources.
      const fetchOptions = { signal: abortController.signal }
      const fetchPromises = [
        apiFetch(`/api/candles?symbol=${sym}&timeframe=${tf}&bars=${requestBars}`, fetchOptions),
        apiFetch(`/api/indicators?symbol=${sym}&timeframe=${tf}&bars=${requestBars}`, fetchOptions),
        apiFetch(`/api/markers?hours=${MARKER_HOURS}`, fetchOptions),
        includeSocketOwnedData ? apiFetch(`/api/state`, fetchOptions) : Promise.resolve(null),
        apiFetch(`/api/market-status`, fetchOptions),
        shouldFetchAnalytics ? apiFetch(`/api/analytics`, fetchOptions).catch(() => null) : Promise.resolve(null),
        includeSocketOwnedData ? apiFetch(`/api/positions`, fetchOptions).catch(() => null) : Promise.resolve(null),
        includeSocketOwnedData ? apiFetch(`/api/trades?limit=50`, fetchOptions).catch(() => null) : Promise.resolve(null),
        apiFetch(`/api/signals?limit=80&collapse_content=true`, fetchOptions).catch(() => null),
        includeSocketOwnedData
          ? apiFetch(`/api/performance-summary`, fetchOptions).catch(() => null)
          : Promise.resolve(null),
      ]

      let results: DashboardResponses
      try {
        results = (await Promise.all(fetchPromises)) as DashboardResponses
        clearTimeout(timeoutId)
      } catch (err) {
        clearTimeout(timeoutId)
        if (abortController.signal.aborted) {
          throw new Error('Request timeout')
        }
        throw err
      }

      // Check if aborted
      if (abortController.signal.aborted) {
        return
      }

      const [candlesRes, indicatorsRes, markersRes, stateRes, marketStatusRes, analyticsRes, positionsRes, tradesRes, signalsRes, perfSummaryRes] = results

      // Handle 503 (data unavailable) - preserve last-good state, don't clear dashboard
      if (candlesRes?.status === 503) {
        const errorData = await candlesRes.json().catch(() => ({}))
        console.warn('Data unavailable (503):', errorData?.detail?.message || 'Agent not running')
        // Preserve last-good state - don't clear dashboard
        setIsLive(false)
        setIsFetching(false)
        return
      }

      if (!candlesRes?.ok) {
        // Retry once on transient errors (503, network errors)
        if (retryCount === 0 && (candlesRes?.status === 503 || !candlesRes)) {
          setTimeout(() => {
            if (mountedRef.current) {
              fetchData(tf, bars, 1)
            }
          }, RETRY_DELAY_MS)
          return
        }
        throw new Error(`API Error: ${candlesRes?.status || 'Network error'}`)
      }

      // Update market status
      if (marketStatusRes?.ok) {
        try {
          const marketData = await marketStatusRes.json()
          setMarketStatus(marketData)
        } catch {
          // Ignore market status errors
        }
      }

      const candlesData = await candlesRes.json()
      const indicatorsData = indicatorsRes?.ok ? await indicatorsRes.json().catch(() => ({})) : {}
      const markersData = markersRes?.ok ? await markersRes.json().catch(() => []) : []
      const stateData = stateRes?.ok ? await stateRes.json().catch(() => null) : null

      // Filter markers to candle time range
      let filteredMarkers = markersData
      if (candlesData.length > 0 && markersData.length > 0) {
        const firstCandleTime = candlesData[0].time
        const lastCandleTime = candlesData[candlesData.length - 1].time
        filteredMarkers = markersData.filter(
          (m: { time: number }) => m.time >= firstCandleTime && m.time <= lastCandleTime
        )
      }

      // Only update if data changed
      const dataHash = `${tf}:${JSON.stringify(candlesData.slice(-3))}`
      if (dataHash !== lastDataHashRef.current) {
        lastDataHashRef.current = dataHash
        setCandles(candlesData)
        setIndicators(indicatorsData)
        setMarkers(filteredMarkers)
      }

      if (stateData && !stateData.error) {
        let nextAnalytics = agentState?.analytics
        if (analyticsRes?.ok) {
          try {
            nextAnalytics = await analyticsRes.json()
            lastAnalyticsFetchRef.current = nowMs
          } catch {
            nextAnalytics = agentState?.analytics
          }
        }
        setAgentState(nextAnalytics ? { ...stateData, analytics: nextAnalytics } : stateData)
      }

      await applyArrayResponse(positionsRes, lastGoodPositionsRef, setPositions)
      await applyArrayResponse(tradesRes, lastGoodTradesRef, setRecentTrades)
      await applyArrayResponse(signalsRes, lastGoodSignalsRef, setRecentSignals)
      await applyNullableResponse(perfSummaryRes, lastGoodPerformanceRef, setPerformanceSummary)

      // Record successful fetch
      const fetchDuration = performance.now() - fetchStartRef.current
      const dataSourceHeader = candlesRes.headers?.get('x-data-source')
      const detectedSource: DataSource = dataSourceHeader === 'cache' ? 'cached' : 'live'
      recordFetch(fetchDuration, detectedSource)
      setIsLive(true)
      setChartError(null)
      setIsFetching(false)

      if (candlesData.length > 0) {
        setChartLoading(false)
      }
    } catch (err) {
      if (abortController.signal.aborted || !mountedRef.current) {
        return
      }
      
      console.error('Failed to fetch data:', err)
      
      // Preserve last-good state on error - don't clear dashboard
      setChartError(err instanceof Error ? err.message : 'Failed to fetch')
      setIsLive(false)
      setChartLoading(false)
      setIsFetching(false)
    }
  }, [
    agentState?.config?.symbol,
    setAgentState,
    setCandles,
    setIndicators,
    setMarkers,
    setMarketStatus,
    setChartError,
    setChartLoading,
    setIsLive,
    setIsFetching,
    recordFetch,
    wsStatus,
  ])

  // Polling effect
  useEffect(() => {
    if (!mountedRef.current) return
    
    fetchData(timeframe, barCount)
    const refreshInterval = wsStatus === 'connected' ? WS_REFRESH_INTERVAL : REFRESH_INTERVAL
    const interval = setInterval(() => {
      if (mountedRef.current) {
        fetchData(timeframe, barCount)
      }
    }, refreshInterval)
    
    return () => {
      clearInterval(interval)
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [timeframe, barCount, wsStatus, fetchData])

  // Initialize last-good refs from current state on mount
  useEffect(() => {
    if (positions.length > 0) {
      lastGoodPositionsRef.current = positions
    }
    if (recentTrades.length > 0) {
      lastGoodTradesRef.current = recentTrades
    }
    if (recentSignals.length > 0) {
      lastGoodSignalsRef.current = recentSignals
    }
    if (performanceSummary !== null) {
      lastGoodPerformanceRef.current = performanceSummary
    }
  }, []) // Only on mount

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      if (abortControllerRef.current) {
        abortControllerRef.current.abort()
      }
    }
  }, [])

  const handleTradeRefresh = useCallback(() => {
    lastAnalyticsFetchRef.current = 0
    fetchData(timeframe, barCount)
  }, [fetchData, timeframe, barCount])

  // Expose update functions for WebSocket message handlers
  const updatePositions = useCallback((newPositions: Position[]) => {
    const positionsArray = Array.isArray(newPositions) ? newPositions : []
    setPositions(positionsArray)
    lastGoodPositionsRef.current = positionsArray
  }, [])

  const updateRecentTrades = useCallback((newTrades: RecentTradeRow[]) => {
    const tradesArray = Array.isArray(newTrades) ? newTrades : []
    setRecentTrades(tradesArray)
    lastGoodTradesRef.current = tradesArray
  }, [])

  const updatePerformanceSummary = useCallback((summary: PerformanceSummary | null) => {
    setPerformanceSummary(summary)
    lastGoodPerformanceRef.current = summary
  }, [])

  return {
    positions,
    recentTrades,
    recentSignals,
    performanceSummary,
    handleTradeRefresh,
    updatePositions,
    updateRecentTrades,
    updatePerformanceSummary,
  }
}
