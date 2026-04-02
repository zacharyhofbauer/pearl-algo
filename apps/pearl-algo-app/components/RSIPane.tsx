'use client'

import React, { useEffect, useRef, useState, useMemo } from 'react'
import { createChart, ColorType, IChartApi, ISeriesApi, Time, LineSeries } from 'lightweight-charts'
import type { IndicatorData } from '@/stores'

interface RSIPaneProps {
  rsiData?: IndicatorData[]
  mainChart?: IChartApi | null
  barSpacing?: number
}

function RSIPane({ rsiData, mainChart, barSpacing = 10 }: RSIPaneProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const rsiSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const syncingRef = useRef(false)

  // Current RSI value for Bull/Bear label
  const currentRSI = useMemo(() => {
    if (!rsiData || rsiData.length === 0) return null
    return rsiData[rsiData.length - 1].value
  }, [rsiData])

  const rsiLabel = currentRSI !== null
    ? (currentRSI >= 50 ? 'Bull' : 'Bear')
    : null
  const rsiColor = currentRSI !== null
    ? (currentRSI >= 50 ? '#26a69a' : '#ef5350')
    : '#8a94a6'

  // Initialize RSI chart
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: '#131722' },
        textColor: '#8a94a6',
        fontSize: 10,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { visible: false },
      },
      rightPriceScale: {
        borderColor: '#2a2e39',
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        visible: false,
        rightOffset: 15,
        barSpacing: barSpacing,
      },
      crosshair: {
        vertLine: { color: '#758696', width: 1, style: 3, labelVisible: false },
        horzLine: { color: '#758696', width: 1, style: 3, labelBackgroundColor: '#363a45' },
      },
    })

    // RSI line series
    const rsiSeries = chart.addSeries(LineSeries, {
      color: '#7c4dff',
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
      priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
    })

    // Overbought/Oversold reference lines
    rsiSeries.createPriceLine({
      price: 70,
      color: 'rgba(239,83,80,0.4)',
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: '',
    })
    rsiSeries.createPriceLine({
      price: 30,
      color: 'rgba(38,166,154,0.4)',
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: '',
    })
    rsiSeries.createPriceLine({
      price: 50,
      color: 'rgba(120,120,120,0.3)',
      lineWidth: 1,
      lineStyle: 1,
      axisLabelVisible: false,
      title: '',
    })

    chartRef.current = chart
    rsiSeriesRef.current = rsiSeries

    return () => {
      chart.remove()
      chartRef.current = null
      rsiSeriesRef.current = null
    }
  }, [barSpacing])

  // Sync time scale with main chart
  useEffect(() => {
    if (!mainChart || !chartRef.current) return

    const rsiChart = chartRef.current
    const mainTimeScale = mainChart.timeScale()
    const rsiTimeScale = rsiChart.timeScale()

    const syncFromMain = (range: any) => {
      if (syncingRef.current) return
      syncingRef.current = true
      try {
        if (range) {
          rsiTimeScale.setVisibleLogicalRange(range)
        }
      } catch {}
      syncingRef.current = false
    }

    const syncFromRsi = (range: any) => {
      if (syncingRef.current) return
      syncingRef.current = true
      try {
        if (range) {
          mainTimeScale.setVisibleLogicalRange(range)
        }
      } catch {}
      syncingRef.current = false
    }

    mainTimeScale.subscribeVisibleLogicalRangeChange(syncFromMain)
    rsiTimeScale.subscribeVisibleLogicalRangeChange(syncFromRsi)

    // Initial sync
    const currentRange = mainTimeScale.getVisibleLogicalRange()
    if (currentRange) {
      rsiTimeScale.setVisibleLogicalRange(currentRange)
    }

    return () => {
      mainTimeScale.unsubscribeVisibleLogicalRangeChange(syncFromMain)
      rsiTimeScale.unsubscribeVisibleLogicalRangeChange(syncFromRsi)
    }
  }, [mainChart])

  // Update RSI data
  useEffect(() => {
    if (!rsiSeriesRef.current || !rsiData?.length) return
    try {
      const formatted = rsiData.map(d => ({ time: d.time as unknown as Time, value: d.value }))
      rsiSeriesRef.current.setData(formatted)
    } catch (e) {
      console.warn('RSI setData error:', e)
    }
  }, [rsiData])

  if (!rsiData?.length) return null

  return (
    <div style={{ position: 'relative', width: '100%', height: '80px', borderTop: '1px solid #2a2e39' }}>
      {/* RSI label overlay */}
      <div style={{
        position: 'absolute', top: 2, left: 8, zIndex: 10,
        display: 'flex', gap: '6px', alignItems: 'center',
        fontSize: '10px', fontWeight: 600,
      }}>
        <span style={{ color: '#8a94a6' }}>RSI(14)</span>
        {rsiLabel && (
          <span style={{
            color: rsiColor,
            padding: '1px 4px',
            borderRadius: '2px',
            background: `${rsiColor}20`,
            fontSize: '9px',
          }}>
            {rsiLabel}
          </span>
        )}
        {currentRSI !== null && (
          <span style={{ color: '#7c4dff', fontSize: '10px' }}>{currentRSI.toFixed(1)}</span>
        )}
      </div>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
    </div>
  )
}

export default React.memo(RSIPane)
