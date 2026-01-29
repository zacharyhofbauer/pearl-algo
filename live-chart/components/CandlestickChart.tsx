'use client'

import { useEffect, useRef } from 'react'
import { createChart, ColorType } from 'lightweight-charts'

interface CandleData {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export default function CandlestickChart({ data }: { data: CandleData[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<any>(null)
  const seriesRef = useRef<any>(null)

  useEffect(() => {
    if (!containerRef.current) return
    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 600,
      layout: { background: { type: ColorType.Solid, color: "#0a0a0f" }, textColor: "#8a94a6" },
      grid: { vertLines: { color: "#1e222d" }, horzLines: { color: "#1e222d" } },
      rightPriceScale: { borderColor: "#2a2a3a" },
      timeScale: { borderColor: "#2a2a3a", timeVisible: true },
    })
    const series = chart.addCandlestickSeries({
      upColor: "#00e676", downColor: "#ff5252", borderVisible: false,
      wickUpColor: "#00e676", wickDownColor: "#ff5252",
    })
    chartRef.current = chart
    seriesRef.current = series
    const handleResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight || 600 })
    }
    window.addEventListener("resize", handleResize)
    return () => { window.removeEventListener("resize", handleResize); chart.remove() }
  }, [])

  useEffect(() => {
    if (!seriesRef.current || !data?.length) return
    seriesRef.current.setData(data)
    chartRef.current?.timeScale().fitContent()
  }, [data])

  return <div ref={containerRef} style={{ width: "100%", height: "100%", minHeight: 500 }} />
}
