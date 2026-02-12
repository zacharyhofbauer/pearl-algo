'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useAgentStore, useChartStore, useUIStore } from '@/stores'
import type { Timeframe, DataSource, Position } from '@/stores'
import type { RecentTradeRow, PerformanceSummary } from '@/components/TradeDockPanel'
import { apiFetch } from '@/lib/api'

const REFRESH_INTERVAL = 10000 // 10 seconds (fallback when WebSocket disconnected)
const WS_REFRESH_INTERVAL = 30000 // 30 seconds (slower when WebSocket connected)
const MIN_BARS = 500
const MARKER_HOURS = 72
const FETCH_TIMEOUT_MS = 10000 // 10 seconds
const RETRY_DELAY_MS = 2000 // 2 seconds

interface UseDashboardDataOptions {
  timeframe: Timeframe
  barCount: number
  wsStatus: 'connecting' | 'connected' | 'disconnected' | 'error'
}

interface UseDashboardDataReturn {
  positions: Position[]
  recentTrades: RecentTradeRow[]
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
  const [performanceSummary, setPerformanceSummary] = useState<PerformanceSummary | null>(null)
  
  // Use refs to preserve last-good state
  const lastGoodPositionsRef = useRef<Position[]>([])
  const lastGoodTradesRef = useRef<RecentTradeRow[]>([])
  const lastGoodPerformanceRef = useRef<PerformanceSummary | null>(null)
  
  const lastDataHashRef = useRef('')
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

      // Fetch all data in parallel with abort support
      const fetchOptions = { signal: abortController.signal }
      const fetchPromises = [
        apiFetch(`/api/candles?symbol=${sym}&timeframe=${tf}&bars=${requestBars}`, fetchOptions),
        apiFetch(`/api/indicators?symbol=${sym}&timeframe=${tf}&bars=${requestBars}`, fetchOptions),
        apiFetch(`/api/markers?hours=${MARKER_HOURS}`, fetchOptions),
        apiFetch(`/api/state`, fetchOptions),
        apiFetch(`/api/market-status`, fetchOptions),
        apiFetch(`/api/analytics`, fetchOptions).catch(() => null),
        apiFetch(`/api/positions`, fetchOptions).catch(() => null),
        apiFetch(`/api/trades?limit=50`, fetchOptions).catch(() => null),
        apiFetch(`/api/performance-summary`, fetchOptions).catch(() => null),
      ]

      let results: any[]
      try {
        results = await Promise.all(fetchPromises)
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

      const [candlesRes, indicatorsRes, markersRes, stateRes, marketStatusRes, analyticsRes, positionsRes, tradesRes, perfSummaryRes] = results

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
        if (analyticsRes?.ok) {
          try {
            const analyticsData = await analyticsRes.json()
            setAgentState({ ...stateData, analytics: analyticsData })
          } catch {
            setAgentState(stateData)
          }
        } else {
          setAgentState(stateData)
        }
      }

      // Update positions (preserve last-good on failure)
      if (positionsRes?.ok) {
        try {
          const positionsData = await positionsRes.json()
          const positionsArray = Array.isArray(positionsData) ? positionsData : []
          setPositions(positionsArray)
          lastGoodPositionsRef.current = positionsArray
        } catch {
          // Preserve last-good state
          if (lastGoodPositionsRef.current.length > 0) {
            setPositions(lastGoodPositionsRef.current)
          }
        }
      } else {
        // Only preserve if we have last-good data (don't overwrite with empty on first failure)
        if (lastGoodPositionsRef.current.length > 0) {
          setPositions(lastGoodPositionsRef.current)
        }
      }

      // Update recent trades (preserve last-good on failure)
      if (tradesRes?.ok) {
        try {
          const tradesData = await tradesRes.json()
          const tradesArray = Array.isArray(tradesData) ? tradesData : []
          setRecentTrades(tradesArray)
          lastGoodTradesRef.current = tradesArray
        } catch {
          if (lastGoodTradesRef.current.length > 0) {
            setRecentTrades(lastGoodTradesRef.current)
          }
        }
      } else {
        if (lastGoodTradesRef.current.length > 0) {
          setRecentTrades(lastGoodTradesRef.current)
        }
      }

      // Update performance summary (preserve last-good on failure)
      if (perfSummaryRes?.ok) {
        try {
          const perfData = await perfSummaryRes.json()
          const perf = perfData || null
          setPerformanceSummary(perf)
          lastGoodPerformanceRef.current = perf
        } catch {
          setPerformanceSummary(lastGoodPerformanceRef.current)
        }
      } else {
        setPerformanceSummary(lastGoodPerformanceRef.current)
      }

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
    performanceSummary,
    handleTradeRefresh,
    updatePositions,
    updateRecentTrades,
    updatePerformanceSummary,
  }
}
