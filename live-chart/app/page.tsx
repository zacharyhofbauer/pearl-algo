'use client'

import { useEffect, useState, useRef } from 'react'
import Image from 'next/image'
import CandlestickChart from '@/components/CandlestickChart'
import type { IChartApi } from 'lightweight-charts'

interface CandleData {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume?: number
}

interface IndicatorData {
  time: number
  value: number
}

interface Indicators {
  ema9?: IndicatorData[]
  ema21?: IndicatorData[]
  vwap?: IndicatorData[]
  rsi?: IndicatorData[]
}

interface MarkerData {
  time: number
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle'
  text: string
}

interface AgentState {
  running: boolean
  paused: boolean
  daily_pnl: number
  daily_trades: number
  daily_wins: number
  daily_losses: number
  active_trades_count: number
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const REFRESH_INTERVAL = 10000 // 10 seconds

type Timeframe = '1m' | '5m' | '15m' | '1h'

// Calculate hours of marker data based on timeframe
const TIMEFRAME_HOURS: Record<Timeframe, number> = {
  '1m': 2,
  '5m': 6,
  '15m': 12,
  '1h': 24,
}

export default function LiveMainChart() {
  const [candles, setCandles] = useState<CandleData[]>([])
  const [indicators, setIndicators] = useState<Indicators>({})
  const [markers, setMarkers] = useState<MarkerData[]>([])
  const [agentState, setAgentState] = useState<AgentState | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [isLive, setIsLive] = useState(false)
  const [timeframe, setTimeframe] = useState<Timeframe>('5m')
  const [barCount, setBarCount] = useState(72)
  const [mainChartApi, setMainChartApi] = useState<IChartApi | null>(null)
  const lastDataHash = useRef<string>('')

  // Calculate bar count based on viewport width
  const calculateBarCount = () => {
    if (typeof window === 'undefined') return 72
    const width = window.innerWidth
    const barSpacing = 8
    const priceScaleWidth = 60
    const availableWidth = width - priceScaleWidth - 40
    return Math.max(30, Math.min(200, Math.floor(availableWidth / barSpacing * 0.8)))
  }

  // Update bar count on resize
  useEffect(() => {
    const update = () => setBarCount(calculateBarCount())
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [])

  // Reset data hash when timeframe changes to force refresh
  useEffect(() => {
    lastDataHash.current = ''
  }, [timeframe])

  const fetchData = async (tf: Timeframe, bars: number) => {
    const markerHours = TIMEFRAME_HOURS[tf]
    try {
      // Fetch all data in parallel
      const [candlesRes, indicatorsRes, markersRes, stateRes] = await Promise.all([
        fetch(`${API_URL}/api/candles?symbol=MNQ&timeframe=${tf}&bars=${bars}`),
        fetch(`${API_URL}/api/indicators?symbol=MNQ&timeframe=${tf}&bars=${bars}`),
        fetch(`${API_URL}/api/markers?hours=${markerHours}`),
        fetch(`${API_URL}/api/state`),
      ])

      if (!candlesRes.ok) throw new Error(`Candles API error: ${candlesRes.status}`)

      const candlesData = await candlesRes.json()
      const indicatorsData = indicatorsRes.ok ? await indicatorsRes.json() : {}
      const markersData = markersRes.ok ? await markersRes.json() : []
      const stateData = stateRes.ok ? await stateRes.json() : null

      // Only update if data changed (include timeframe in hash to force update on tf change)
      const dataHash = `${tf}:${JSON.stringify(candlesData.slice(-3))}`
      if (dataHash !== lastDataHash.current) {
        lastDataHash.current = dataHash
        setCandles(candlesData)
        setIndicators(indicatorsData)
        setMarkers(markersData)
      }

      if (stateData && !stateData.error) {
        setAgentState(stateData)
      }

      setLastUpdate(new Date())
      setIsLive(true)
      setError(null)
    } catch (err) {
      console.error('Failed to fetch data:', err)
      setError(err instanceof Error ? err.message : 'Failed to fetch data')
      setIsLive(false)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchData(timeframe, barCount)
    const interval = setInterval(() => fetchData(timeframe, barCount), REFRESH_INTERVAL)
    return () => clearInterval(interval)
  }, [timeframe, barCount])

  const formatTime = (date: Date | null) => {
    if (!date) return '--:--'
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    })
  }

  const formatPnL = (pnl: number) => {
    const sign = pnl >= 0 ? '+' : ''
    return `${sign}$${pnl.toFixed(2)}`
  }

  // Format display text for timeframe window
  const getTimeframeDisplay = () => {
    const hours = TIMEFRAME_HOURS[timeframe]
    return hours >= 24 ? `${hours / 24}d` : `${hours}h`
  }

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="header">
        <div className="title-group">
          <Image src="/logo.png" alt="PEARL" width={28} height={28} className="logo" priority />
          <h1>
            <span className="symbol">MNQ</span>
            <span className="timeframe"> {getTimeframeDisplay()} ({timeframe}) • Live Main Chart</span>
          </h1>
        </div>
        {/* Timeframe Selector */}
        <div className="timeframe-selector">
          {(['1m', '5m', '15m', '1h'] as Timeframe[]).map((tf) => (
            <button
              key={tf}
              className={timeframe === tf ? 'active' : ''}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>
        <div className="status">
          <span className={`status-dot ${isLive ? '' : 'offline'}`}></span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
            {isLive ? 'Live' : 'Offline'} • {formatTime(lastUpdate)}
          </span>
        </div>
      </header>

      {/* Status Panel */}
      {(agentState || candles.length > 0) && (
        <div className="status-panel">
          {/* Current Price */}
          {candles.length > 0 && (
            <div className="stat price-stat">
              <span className="stat-label">Price</span>
              <span className={`stat-value price-value ${candles[candles.length-1]?.close >= candles[candles.length-1]?.open ? 'positive' : 'negative'}`}>
                {candles[candles.length-1]?.close.toFixed(2)}
              </span>
            </div>
          )}
          {agentState && (
            <>
              <div className="stat">
                <span className="stat-label">Agent</span>
                <span className={`stat-value ${agentState.running ? 'positive' : 'negative'}`}>
                  {agentState.running ? (agentState.paused ? '⏸️ Paused' : '🟢 Running') : '🔴 Stopped'}
                </span>
              </div>
              <div className="stat">
                <span className="stat-label">Day P&L</span>
                <span className={`stat-value ${agentState.daily_pnl >= 0 ? 'positive' : 'negative'}`}>
                  {formatPnL(agentState.daily_pnl)}
                </span>
              </div>
              <div className="stat">
                <span className="stat-label">Trades</span>
                <span className="stat-value">
                  {agentState.daily_wins}W / {agentState.daily_losses}L
                </span>
              </div>
              <div className="stat">
                <span className="stat-label">Open Pos</span>
                <span className={`stat-value ${agentState.active_trades_count > 0 ? 'highlight' : ''}`}>
                  {agentState.active_trades_count}
                </span>
              </div>
            </>
          )}
          {/* Indicator Legend */}
          <div className="indicator-legend">
            <span className="legend-item"><span className="legend-color ema9"></span>EMA9</span>
            <span className="legend-item"><span className="legend-color ema21"></span>EMA21</span>
            <span className="legend-item"><span className="legend-color vwap"></span>VWAP</span>
          </div>
          {/* Marker Legend */}
          <div className="marker-legend">
            <span className="legend-item">
              <span className="marker-icon entry-long">▲</span>
              <span className="marker-icon entry-short">▼</span>
              Entry
            </span>
            <span className="legend-item">
              <span className="marker-icon exit-win">●</span>
              <span className="marker-icon exit-loss">●</span>
              Exit
            </span>
          </div>
        </div>
      )}

      {/* Chart */}
      <div className="chart-wrapper">
        <div className="chart-actions">
          <button
            className="chart-action-btn"
            onClick={() => mainChartApi?.timeScale().fitContent()}
            title="Fit All"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
            </svg>
          </button>
          <button
            className="chart-action-btn"
            onClick={() => mainChartApi?.timeScale().scrollToRealTime()}
            title="Go Live"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <polygon points="5 3 19 12 5 21 5 3" />
            </svg>
          </button>
        </div>
        <div className="chart-container">
          {loading && <div className="loading">Loading chart data...</div>}
          {error && !loading && <div className="error">Error: {error}</div>}
          {!loading && !error && candles.length > 0 && (
            <CandlestickChart
              data={candles}
              indicators={indicators}
              markers={markers}
              onChartReady={setMainChartApi}
            />
          )}
        </div>
      </div>

      {/* RSI Panel */}
      {indicators.rsi && indicators.rsi.length > 0 && (
        <div className="rsi-panel">
          <RSIChart data={indicators.rsi} />
        </div>
      )}
    </div>
  )
}

// Simple RSI Chart Component
function RSIChart({ data }: { data: IndicatorData[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<any>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const { createChart, ColorType } = require('lightweight-charts')
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 120,  // Increased to accommodate x-axis labels
      layout: {
        background: { type: ColorType.Solid, color: '#0a0a0f' },
        textColor: '#8a94a6',
      },
      grid: {
        vertLines: { color: '#1e222d' },
        horzLines: { color: '#1e222d' },
      },
      rightPriceScale: {
        borderColor: '#2a2a3a',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        visible: true,
        borderColor: '#2a2a3a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,  // Match main chart
        barSpacing: 8,
        tickMarkFormatter: (time: number) => {
          const date = new Date(time * 1000)
          const hours = date.getHours().toString().padStart(2, '0')
          const minutes = date.getMinutes().toString().padStart(2, '0')
          return `${hours}:${minutes}`
        },
      },
    })

    const series = chart.addLineSeries({
      color: '#00d4ff',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    })

    // Add overbought/oversold lines (more visible)
    const ob = chart.addLineSeries({ 
      color: 'rgba(255, 82, 82, 0.8)', 
      lineWidth: 1, 
      lineStyle: 2,  // Dashed
      priceLineVisible: false, 
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })
    const os = chart.addLineSeries({ 
      color: 'rgba(0, 230, 118, 0.8)', 
      lineWidth: 1, 
      lineStyle: 2,  // Dashed
      priceLineVisible: false, 
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    chartRef.current = { chart, series, ob, os }

    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth })
    }
    window.addEventListener('resize', handleResize)
    return () => { window.removeEventListener('resize', handleResize); chart.remove() }
  }, [])

  useEffect(() => {
    if (!chartRef.current || !data?.length) return
    chartRef.current.series.setData(data)
    
    // Overbought (70) and oversold (30) lines
    const obData = data.map(d => ({ time: d.time, value: 70 }))
    const osData = data.map(d => ({ time: d.time, value: 30 }))
    chartRef.current.ob.setData(obData)
    chartRef.current.os.setData(osData)
  }, [data])

  return (
    <div className="rsi-container">
      <span className="rsi-label">RSI(14)</span>
      <div ref={containerRef} style={{ width: '100%', height: 120 }} />
    </div>
  )
}
