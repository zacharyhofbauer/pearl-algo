'use client'

import { useEffect, useRef } from 'react'
import { createChart, ColorType, CrosshairMode, IChartApi, ISeriesApi } from 'lightweight-charts'

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

interface MarkerData {
  time: number
  position: 'aboveBar' | 'belowBar'
  color: string
  shape: 'arrowUp' | 'arrowDown' | 'circle'
  text: string
}

interface ChartProps {
  data: CandleData[]
  indicators?: {
    ema9?: IndicatorData[]
    ema21?: IndicatorData[]
    vwap?: IndicatorData[]
    rsi?: IndicatorData[]
  }
  markers?: MarkerData[]
}

export default function CandlestickChart({ data, indicators, markers }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null)
  const ema9SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const ema21SeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const vwapSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)

  // Initialize chart
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: containerRef.current.clientHeight || 600,
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
        scaleMargins: { top: 0.1, bottom: 0.2 },
      },
      timeScale: {
        borderColor: '#2a2a3a',
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 8,  // Empty space (bars) to the right of the last candle
        barSpacing: 8,   // Space between bars
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: '#758696',
          width: 1,
          style: 3,
          labelBackgroundColor: '#2a2a3a',
        },
        horzLine: {
          color: '#758696',
          width: 1,
          style: 3,
          labelBackgroundColor: '#2a2a3a',
        },
      },
    })

    // Candlestick series with price line extending to right
    const candleSeries = chart.addCandlestickSeries({
      upColor: '#00e676',
      downColor: '#ff5252',
      borderVisible: false,
      wickUpColor: '#00e676',
      wickDownColor: '#ff5252',
      priceFormat: { type: 'price', precision: 2, minMove: 0.25 },
      lastValueVisible: true,
      priceLineVisible: true,
      priceLineWidth: 1,
      priceLineColor: '#ff5252',
      priceLineStyle: 2,  // Dashed line extending to right edge
    })

    // Volume series (histogram at bottom - increased height)
    const volumeSeries = chart.addHistogramSeries({
      color: '#26a69a',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.75, bottom: 0 },  // Taller volume bars (was 0.85)
    })

    // EMA 9 line (cyan)
    const ema9Series = chart.addLineSeries({
      color: '#00d4ff',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // EMA 21 line (yellow)
    const ema21Series = chart.addLineSeries({
      color: '#ffc107',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    // VWAP line (purple, dashed)
    const vwapSeries = chart.addLineSeries({
      color: '#ab47bc',
      lineWidth: 2,
      lineStyle: 2, // Dashed
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    })

    chartRef.current = chart
    candleSeriesRef.current = candleSeries
    volumeSeriesRef.current = volumeSeries
    ema9SeriesRef.current = ema9Series
    ema21SeriesRef.current = ema21Series
    vwapSeriesRef.current = vwapSeries

    // Handle resize
    const handleResize = () => {
      if (containerRef.current) {
        chart.applyOptions({
          width: containerRef.current.clientWidth,
          height: containerRef.current.clientHeight || 600,
        })
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  // Update candle data
  useEffect(() => {
    if (!candleSeriesRef.current || !volumeSeriesRef.current || !data?.length) return

    candleSeriesRef.current.setData(data)

    // Volume data with color based on candle direction
    const volumeData = data.map((d) => ({
      time: d.time,
      value: d.volume || 0,
      color: d.close >= d.open ? 'rgba(0, 230, 118, 0.3)' : 'rgba(255, 82, 82, 0.3)',
    }))
    volumeSeriesRef.current.setData(volumeData)

    // Scroll to show latest with right offset preserved
    chartRef.current?.timeScale().scrollToRealTime()
  }, [data])

  // Update indicators
  useEffect(() => {
    if (!indicators) return

    if (ema9SeriesRef.current && indicators.ema9?.length) {
      ema9SeriesRef.current.setData(indicators.ema9)
    }
    if (ema21SeriesRef.current && indicators.ema21?.length) {
      ema21SeriesRef.current.setData(indicators.ema21)
    }
    if (vwapSeriesRef.current && indicators.vwap?.length) {
      vwapSeriesRef.current.setData(indicators.vwap)
    }
  }, [indicators])

  // Update markers
  useEffect(() => {
    if (!candleSeriesRef.current || !markers?.length) return
    
    try {
      candleSeriesRef.current.setMarkers(
        markers.map((m) => ({
          time: m.time as any,
          position: m.position,
          color: m.color,
          shape: m.shape,
          text: m.text,
        }))
      )
    } catch (e) {
      console.warn('Failed to set markers:', e)
    }
  }, [markers])

  return (
    <div ref={containerRef} style={{ width: '100%', height: '100%', minHeight: 500 }} />
  )
}
