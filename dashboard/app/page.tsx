'use client'

import { useEffect, useState } from 'react'
import CandlestickChart from '@/components/CandlestickChart'

interface CandleData {
  time: number
  open: number
  high: number
  low: number
  close: number
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
const REFRESH_INTERVAL = 5000 // 5 seconds

export default function Dashboard() {
  const [candles, setCandles] = useState<CandleData[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null)
  const [isLive, setIsLive] = useState(false)

  const fetchCandles = async () => {
    try {
      const response = await fetch(`${API_URL}/api/candles?symbol=MNQ&timeframe=5m&bars=72`)
      if (!response.ok) {
        throw new Error(`API error: ${response.status}`)
      }
      const data = await response.json()
      setCandles(data)
      setLastUpdate(new Date())
      setIsLive(true)
      setError(null)
    } catch (err) {
      console.error('Failed to fetch candles:', err)
      setError(err instanceof Error ? err.message : 'Failed to fetch data')
      setIsLive(false)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    // Initial fetch
    fetchCandles()

    // Set up polling
    const interval = setInterval(fetchCandles, REFRESH_INTERVAL)

    return () => clearInterval(interval)
  }, [])

  const formatTime = (date: Date | null) => {
    if (!date) return '--:--'
    return date.toLocaleTimeString('en-US', { 
      hour: '2-digit', 
      minute: '2-digit',
      second: '2-digit',
      hour12: false 
    })
  }

  return (
    <div className="dashboard">
      <header className="header">
        <h1>
          <span className="symbol">MNQ</span>
          <span className="timeframe"> 6h (5m)</span>
        </h1>
        <div className="status">
          <span className={`status-dot ${isLive ? '' : 'offline'}`}></span>
          <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
            {isLive ? 'Live' : 'Offline'} • {formatTime(lastUpdate)}
          </span>
        </div>
      </header>

      <div className="chart-container">
        {loading && <div className="loading">Loading chart data...</div>}
        {error && !loading && <div className="error">Error: {error}</div>}
        {!loading && !error && candles.length > 0 && (
          <CandlestickChart data={candles} />
        )}
      </div>
    </div>
  )
}
