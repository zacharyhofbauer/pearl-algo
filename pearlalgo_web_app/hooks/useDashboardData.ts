'use client'

import { useEffect, useCallback, useRef } from 'react'
import { useAgentStore, useChartStore, useUIStore, type Timeframe } from '@/stores'
import { useWebSocket, getWebSocketUrl } from '@/hooks/useWebSocket'
import { apiFetch } from '@/lib/api'
import type { Position, DataSource } from '@/stores'

// Configuration constants
const REFRESH_INTERVAL = 10000 // 10 seconds (fallback when WebSocket disconnected)
const WS_REFRESH_INTERVAL = 30000 // 30 seconds (slower when WebSocket connected)
const MIN_BARS = 500 // Minimum bars to request for a full chart
const MARKER_HOURS = 72 // Fetch 72 hours (3 days) of markers - API limit

interface UseDashboardDataOptions {
  onPositionsUpdate?: (positions: Position[], latestPrice: number | null, pointValue: number) => void
}

export function useDashboardData(options: UseDashboardDataOptions = {}) {
  const { onPositionsUpdate } = options

  // Agent store
  const setAgentState = useAgentStore((s) => s.setAgentState)
  const updateFromWebSocket = useAgentStore((s) => s.updateFromWebSocket)

  // Chart store
  const timeframe = useChartStore((s) => s.timeframe)
  const barCount = useChartStore((s) => s.barCount)
  const lastDataHash = useChartStore((s) => s.lastDataHash)
  const setCandles = useChartStore((s) => s.setCandles)
  const setIndicators = useChartStore((s) => s.setIndicators)
  const setMarkers = useChartStore((s) => s.setMarkers)
  const setMarketStatus = useChartStore((s) => s.setMarketStatus)
  const setChartLoading = useChartStore((s) => s.setLoading)
  const setChartError = useChartStore((s) => s.setError)
  const setLastDataHash = useChartStore((s) => s.setLastDataHash)
  const appendCandle = useChartStore((s) => s.appendCandle)

  // UI store
  const wsStatus = useUIStore((s) => s.wsStatus)
  const setWsStatus = useUIStore((s) => s.setWsStatus)
  const setIsLive = useUIStore((s) => s.setIsLive)
  const setLastUpdate = useUIStore((s) => s.setLastUpdate)
  const setIsFetching = useUIStore((s) => s.setIsFetching)
  const recordFetch = useUIStore((s) => s.recordFetch)

  // Track fetch start time for duration calculation
  const fetchStartRef = useRef<number>(0)

  // WebSocket connection for real-time updates
  useWebSocket({
    url: getWebSocketUrl(),
    reconnect: true,
    reconnectInterval: 3000,
    maxReconnectAttempts: 10,
    pingInterval: 30000,
    onStatusChange: setWsStatus,
    onMessage: (message) => {
      if (message.type === 'initial_state' || message.type === 'state_update' || message.type === 'full_refresh') {
        const data = message.data
        if (data) {
          updateFromWebSocket(data)
          setLastUpdate(new Date())
          setIsLive(true)
        }
      }

      // Handle real-time candle updates
      if (message.type === 'candle_update') {
        const candle = message.data
        if (candle && typeof candle.time === 'number') {
          appendCandle(candle)
          setLastUpdate(new Date())
        }
      }
    },
  })

  const fetchData = useCallback(async (tf: Timeframe, bars: number) => {
    // Track fetch timing and state
    fetchStartRef.current = performance.now()
    setIsFetching(true)

    try {
      // Ensure we always request at least MIN_BARS
      const requestBars = Math.max(MIN_BARS, bars)

      // Fetch all data in parallel (apiFetch includes auth headers when configured)
      const [candlesRes, indicatorsRes, markersRes, stateRes, marketStatusRes, analyticsRes, positionsRes] = await Promise.all([
        apiFetch(`/api/candles?symbol=MNQ&timeframe=${tf}&bars=${requestBars}`),
        apiFetch(`/api/indicators?symbol=MNQ&timeframe=${tf}&bars=${requestBars}`),
        apiFetch(`/api/markers?hours=${MARKER_HOURS}`),
        apiFetch(`/api/state`),
        apiFetch(`/api/market-status`),
        apiFetch(`/api/analytics`).catch(() => null),  // Analytics is optional
        apiFetch(`/api/positions`).catch(() => null),  // Positions for chart lines
      ])

      // Update market status
      if (marketStatusRes.ok) {
        const marketData = await marketStatusRes.json()
        setMarketStatus(marketData)
      }

      // Handle 503 (data unavailable) specifically
      if (candlesRes.status === 503) {
        const errorData = await candlesRes.json().catch(() => ({}))
        throw new Error(errorData?.detail?.message || 'No Data — Agent Not Running')
      }

      if (!candlesRes.ok) throw new Error(`API Error: ${candlesRes.status}`)

      const candlesData = await candlesRes.json()
      const indicatorsData = indicatorsRes.ok ? await indicatorsRes.json() : {}
      const markersData = markersRes.ok ? await markersRes.json() : []
      const stateData = stateRes.ok ? await stateRes.json() : null

      // Filter markers to only those within the candle time range
      let filteredMarkers = markersData
      if (candlesData.length > 0 && markersData.length > 0) {
        const firstCandleTime = candlesData[0].time
        const lastCandleTime = candlesData[candlesData.length - 1].time
        filteredMarkers = markersData.filter(
          (m: { time: number }) => m.time >= firstCandleTime && m.time <= lastCandleTime
        )
      }

      // Only update if data changed (include timeframe in hash to force update on tf change)
      const dataHash = `${tf}:${JSON.stringify(candlesData.slice(-3))}`
      if (dataHash !== lastDataHash) {
        setLastDataHash(dataHash)
        setCandles(candlesData)
        setIndicators(indicatorsData)
        setMarkers(filteredMarkers)
      }

      if (stateData && !stateData.error) {
        // Include analytics in state if available
        if (analyticsRes && analyticsRes.ok) {
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

      // Update positions for chart price lines
      // API now returns { positions: [...], latest_price: number, tick_value: number }
      if (positionsRes && positionsRes.ok) {
        try {
          const positionsData = await positionsRes.json()
          // Handle both old array format and new object format
          if (Array.isArray(positionsData)) {
            onPositionsUpdate?.(positionsData, null, 2.0)
          } else {
            onPositionsUpdate?.(
              positionsData.positions || [],
              positionsData.latest_price ?? null,
              positionsData.tick_value ?? 2.0
            )
          }
        } catch {
          onPositionsUpdate?.([], null, 2.0)
        }
      } else {
        onPositionsUpdate?.([], null, 2.0)
      }

      // Calculate fetch duration and determine data source
      const fetchDuration = performance.now() - fetchStartRef.current
      // Detect cached data: if candles response has x-data-source header
      const dataSourceHeader = candlesRes.headers.get('x-data-source')
      const detectedSource: DataSource = dataSourceHeader === 'cache' ? 'cached' : 'live'

      // Record successful fetch with timing and source
      recordFetch(fetchDuration, detectedSource)
      setIsLive(true)
      setChartError(null)

      // Always clear loading and fetching states when we have data
      if (candlesData.length > 0) {
        setChartLoading(false)
      }
      setIsFetching(false)
    } catch (err) {
      setChartError(err instanceof Error ? err.message : 'Failed to fetch')
      setIsLive(false)
      setChartLoading(false)
      setIsFetching(false)
    }
  }, [
    lastDataHash,
    onPositionsUpdate,
    setAgentState,
    setCandles,
    setIndicators,
    setMarkers,
    setMarketStatus,
    setLastDataHash,
    setChartError,
    setChartLoading,
    setIsLive,
    setIsFetching,
    recordFetch,
  ])

  // Initial fetch and periodic refresh
  useEffect(() => {
    fetchData(timeframe, barCount)
    // Use slower polling when WebSocket is connected (WS handles state updates)
    // Use faster polling when WebSocket is disconnected
    const refreshInterval = wsStatus === 'connected' ? WS_REFRESH_INTERVAL : REFRESH_INTERVAL
    const interval = setInterval(() => fetchData(timeframe, barCount), refreshInterval)
    return () => clearInterval(interval)
  }, [timeframe, barCount, wsStatus, fetchData])

  // Force refresh function for manual refresh
  const forceRefresh = useCallback(() => {
    fetchData(timeframe, barCount)
  }, [fetchData, timeframe, barCount])

  return {
    fetchData,
    forceRefresh,
  }
}
