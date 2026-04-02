'use client'

import { useState, useEffect, useMemo } from 'react'
import { useChartStore, useChartSettingsStore, type Timeframe } from '@/stores'
import { useAIStatus } from '@/hooks/useAIStatus'
import type { AgentState } from '@/stores/agentStore'
import type { MarketStatus } from '@/stores/chartStore'
import type { IChartApi } from 'lightweight-charts'

/** Format a price with commas and 2 decimal places (e.g. 24,391.75) */
function fmtPrice(n: number): string {
  return n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

interface ChartHeaderProps {
  agentState: AgentState | null
  marketStatus: MarketStatus | null
  mainChartApi: IChartApi | null
  candles: { time: number; close: number }[]
  isCompactHeader: boolean
}

export default function ChartHeader({
  agentState,
  marketStatus,
  mainChartApi,
  candles,
  isCompactHeader,
}: ChartHeaderProps) {
  const timeframe = useChartStore((s) => s.timeframe)
  const setTimeframe = useChartStore((s) => s.setTimeframe)
  const indicatorSettings = useChartSettingsStore((s) => s.indicators)
  const toggleIndicator = useChartSettingsStore((s) => s.toggleIndicator)

  const [badgeTip, setBadgeTip] = useState<string | null>(null)
  const [showIndicatorsDropdown, setShowIndicatorsDropdown] = useState(false)

  const aiStatus = useAIStatus(agentState?.ai_status ?? null)

  // Close indicators dropdown on outside click
  useEffect(() => {
    if (!showIndicatorsDropdown) return
    const close = () => setShowIndicatorsDropdown(false)
    document.addEventListener('click', close)
    return () => document.removeEventListener('click', close)
  }, [showIndicatorsDropdown])

  const getRegimeBadge = () => {
    if (!agentState?.market_regime) return null
    const regime = agentState.market_regime
    if (regime.confidence === 0 || regime.regime === 'unknown') return null
    const icons: Record<string, string> = {
      'trending_up': '\u{1F4C8}',
      'trending_down': '\u{1F4C9}',
      'ranging': '\u2194\uFE0F',
      'volatile': '\u26A1',
    }
    return {
      icon: icons[regime.regime] || '\u2753',
      label: regime.regime.replace('_', ' ').toUpperCase(),
      confidence: Math.round(regime.confidence * 100),
    }
  }

  const aiMode = aiStatus.aiMode

  // Compute last price + change for mobile price strip
  const priceInfo = useMemo(() => {
    if (!candles || candles.length < 2) return null
    const last = candles[candles.length - 1].close
    const prev = candles[candles.length - 2].close
    const change = last - prev
    const changePct = prev !== 0 ? (change / prev) * 100 : 0
    return { last, change, changePct }
  }, [candles])

  const symbol = agentState?.config?.symbol || 'MNQ'
  const dataFresh = agentState?.data_fresh ?? false

  return (
    <header className="header-combined">
      <div className="header-row-single">
        {/* Left: Timeframe buttons */}
        <div className="header-timeframe">
          {(['1m', '5m', '15m', '30m', '1h', '4h', '1D'] as Timeframe[]).map((tf) => (
            <button
              key={tf}
              className={`tf-btn ${timeframe === tf ? 'active' : ''}`}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>

        {/* Center: Action buttons */}
        <div className="header-actions">
          {/* Indicators toggle */}
          <div style={{ position: 'relative' }}>
            <button
              className="header-action-btn"
              title="Indicators"
              onClick={() => setShowIndicatorsDropdown((v) => !v)}
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="1,12 4,4 8,10 12,2 15,8" />
              </svg>
            </button>
            {showIndicatorsDropdown && (
              <div className="indicators-dropdown" onClick={(e) => e.stopPropagation()}>
                <div className="indicators-section-header">Overlays</div>
                {([
                  { key: 'ema9' as const, label: 'EMA Crossover', color: '#00d4ff' },
                  { key: 'vwap' as const, label: 'VWAP', color: 'rgba(100,181,246,0.85)' },
                  { key: 'vwapBands' as const, label: 'VWAP Bands', color: 'rgba(76,175,80,0.5)' },
                  { key: 'keyLevels' as const, label: 'Key Levels', color: '#08bcd4' },
                  { key: 'sessions' as const, label: 'Sessions', color: 'rgba(8,153,129,0.5)' },
                  { key: 'sdZones' as const, label: 'S/D Zones', color: 'rgba(255,193,7,0.4)' },
                  { key: 'tbtTrendlines' as const, label: 'TBT Trendlines', color: '#ff9800' },
                  { key: 'bollingerBands' as const, label: 'Bollinger Bands', color: 'rgba(41,98,255,0.7)' },
                  { key: 'atrBands' as const, label: 'ATR Bands', color: 'rgba(255,152,0,0.5)' },
                  { key: 'srPowerZones' as const, label: 'S&R Power', color: '#ab47bc' },
                ]).map(({ key, label, color }) => (
                  <div key={key} className="indicator-toggle-item" onClick={() => {
                    if (key === 'ema9') {
                      toggleIndicator('ema9')
                      toggleIndicator('ema21')
                    } else {
                      toggleIndicator(key)
                    }
                  }}>
                    <span className="indicator-color-dot" style={{ background: color }} />
                    <span>{label}</span>
                    <span className={`indicator-dot ${indicatorSettings[key] ? 'active' : ''}`} />
                  </div>
                ))}
                <div className="indicators-section-header">Panes</div>
                {([
                  { key: 'rsi' as const, label: 'RSI (14)', color: '#7c4dff' },
                  { key: 'volume' as const, label: 'Volume', color: '#26a69a' },
                ]).map(({ key, label, color }) => (
                  <div key={key} className="indicator-toggle-item" onClick={() => toggleIndicator(key)}>
                    <span className="indicator-color-dot" style={{ background: color }} />
                    <span>{label}</span>
                    <span className={`indicator-dot ${indicatorSettings[key] ? 'active' : ''}`} />
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Fullscreen */}
          <button
            className="header-action-btn"
            title="Fullscreen"
            onClick={() => {
              if (document.fullscreenElement) {
                document.exitFullscreen()
              } else {
                document.documentElement.requestFullscreen()
              }
            }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="1,5 1,1 5,1" /><polyline points="11,1 15,1 15,5" /><polyline points="15,11 15,15 11,15" /><polyline points="5,15 1,15 1,11" />
            </svg>
          </button>

          {/* Screenshot */}
          <button
            className="header-action-btn"
            title="Screenshot"
            onClick={() => {
              if (mainChartApi) {
                mainChartApi.takeScreenshot()
              }
            }}
          >
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="1" y="3" width="14" height="11" rx="2" /><circle cx="8" cy="9" r="3" /><path d="M5 3L6 1h4l1 2" />
            </svg>
          </button>
        </div>

        {/* Right: Status badges */}
        <div className="header-badges">
          {/* Badge 1: Agent + Market combined */}
          {agentState && (() => {
            const isRunning = Boolean(agentState.running)
            const isPaused = Boolean(agentState.paused)
            const isMarketOpen = Boolean((agentState as any).futures_market_open ?? marketStatus?.is_open ?? true)
            let label: string, cls: string, tip: string
            if (!isRunning) {
              label = isCompactHeader ? 'STOP' : 'STOPPED'; cls = 'stopped'
              tip = 'Agent stopped \u2014 no signals being generated'
            } else if (isPaused) {
              label = 'PAUSED'; cls = 'paused'
              tip = 'Agent paused \u2014 circuit breaker or manual pause active'
            } else if (isMarketOpen) {
              label = 'TRADING'; cls = 'trading'
              tip = 'Agent running \u00B7 Market open \u00B7 Scanning for signals'
            } else {
              label = 'READY'; cls = 'ready'
              tip = 'Agent running \u00B7 Market closed \u00B7 Will trade at open'
            }
            return (
              <span className={`badge agent-market-badge ${cls}`} role="button" tabIndex={0} title={tip}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'agent' ? null : 'agent') }}>
                <span className="badge-dot"></span>{label}
              </span>
            )
          })()}
          {/* Badge 2: IBKR (data feed) */}
          {agentState && (() => {
            const ibkrOk = agentState.gateway_status?.status === 'online'
            return (
              <span className={`badge ibkr-badge ${ibkrOk ? 'ok' : 'error'}`} role="button" tabIndex={0}
                title={`IBKR \u2014 ${ibkrOk ? 'Online \u00B7 Market data flowing' : 'Offline \u00B7 No market data \u2014 check gateway'}`}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'ibkr' ? null : 'ibkr') }}>
                <span className="badge-dot"></span>IBKR
              </span>
            )
          })()}
          {/* Badge 3: TV (Tradovate execution) */}
          {agentState && (() => {
            const exec = (agentState as any).execution || {}
            const tvConnected = Boolean(exec.connected)
            const tvArmed = Boolean(exec.armed)
            const tvOk = tvConnected && tvArmed
            const tvDeg = tvConnected && !tvArmed
            const tvClass = tvOk ? 'ok' : tvDeg ? 'degraded' : 'error'
            const tvTip = tvOk ? `Tradovate \u2014 Connected & armed \u00B7 Paper mode \u00B7 Orders today: ${exec.orders_today ?? 0}`
              : tvDeg ? 'Tradovate \u2014 Connected but not armed \u00B7 Check execution config'
              : 'Tradovate \u2014 Disconnected \u00B7 No trade execution'
            return (
              <span className={`badge tv-badge ${tvClass}`} role="button" tabIndex={0} title={tvTip}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'tv' ? null : 'tv') }}>
                <span className="badge-dot"></span>TV
              </span>
            )
          })()}
          {/* Badge 4: OC (OpenClaw + AI mode) */}
          {agentState && (() => {
            const ocOk = true // OpenClaw runs on Mac gateway, always available
            let label: string, cls: string, tip: string
            if (!ocOk) {
              label = 'OC\u2193'; cls = 'error'
              tip = 'OpenClaw node offline \u2014 AI unavailable'
            } else if (aiMode === 'live') {
              label = isCompactHeader ? 'OC\u00B7L' : 'OC\u00B7LIVE'; cls = 'live'
              tip = 'OpenClaw online \u00B7 ML filter LIVE \u2014 blocking low-confidence signals'
            } else if (aiMode === 'shadow') {
              label = isCompactHeader ? 'OC\u00B7S' : 'OC\u00B7SHDW'; cls = 'shadow'
              tip = 'OpenClaw online \u00B7 ML in shadow mode \u2014 observing signals, not blocking yet'
            } else {
              label = 'OC'; cls = 'ok'
              tip = 'OpenClaw online \u00B7 AI/ML disabled'
            }
            return (
              <span className={`badge oc-ai-badge ${cls}`} role="button" tabIndex={0} title={tip}
                onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'oc' ? null : 'oc') }}>
                {label}
              </span>
            )
          })()}
          {/* Badge 5: DATA (freshness) */}
          {agentState && (
            <span className={`badge data-badge ${agentState.data_fresh ? 'ok' : 'stale'}`} role="button" tabIndex={0}
              title={`Data \u2014 Market feed ${agentState.data_fresh ? 'fresh' : 'STALE \u2014 check IBKR gateway'}`}
              onClick={(e) => { e.stopPropagation(); setBadgeTip(badgeTip === 'data' ? null : 'data') }}>
              <span className="badge-dot"></span>DATA
            </span>
          )}
        </div>
        {/* Badge explanation tooltip */}
        {badgeTip && (
          <div className="badge-tooltip" onClick={() => setBadgeTip(null)}>
            {badgeTip === 'agent' && (
              <p><strong>Status</strong> \u2014 {agentState?.running
                ? (agentState?.paused ? 'PAUSED \u2014 circuit breaker or manual pause. POST /api/resume to unpause.'
                  : ((agentState as any)?.futures_market_open ?? true) ? 'TRADING \u2014 agent scanning for signals, market open.'
                  : 'READY \u2014 agent running, market closed. Will trade at open.')
                : 'STOPPED \u2014 agent process not running. Use soft-restart.'}</p>
            )}
            {badgeTip === 'ibkr' && (
              <p><strong>IBKR Gateway</strong> \u2014 {agentState?.gateway_status?.status === 'online'
                ? `Online on port ${agentState?.gateway_status?.port}. Providing market data.`
                : 'Offline. Try gateway restart first. Warm restart is preferred; IBKR auth is only needed if the session cannot be preserved.'}</p>
            )}
            {badgeTip === 'tv' && (
              <p><strong>Tradovate</strong> \u2014 {(() => {
                const exec = (agentState as any)?.execution || {}
                return exec.connected && exec.armed
                  ? `Connected & armed. Paper mode. ${exec.orders_today ?? 0} orders today.`
                  : exec.connected ? 'Connected but not armed. Check execution config.'
                  : 'Disconnected. Agent restart may fix this.'
              })()}</p>
            )}
            {badgeTip === 'oc' && (
              <p><strong>OpenClaw</strong> \u2014 {agentState?.openclaw_status?.status === 'online'
                ? `Online (port ${agentState?.openclaw_status?.port}). `
                : 'Offline. '}{(() => {
                const ai = (agentState as any)?.ai_status
                const mode = ai?.ml_filter?.mode
                return mode === 'shadow'
                  ? 'ML filter in SHADOW \u2014 recording predictions, not blocking trades.'
                  : mode === 'live' ? 'ML filter LIVE \u2014 actively blocking low-confidence signals.'
                  : 'AI/ML disabled.'
              })()}</p>
            )}
            {badgeTip === 'data' && (
              <p><strong>Data Feed</strong> \u2014 {agentState?.data_fresh ? 'Fresh.' : 'STALE \u2014 market data not updating.'} {(() => {
                const dq = (agentState as any)?.data_quality
                return dq ? `Bar age: ${dq.latest_bar_age_minutes?.toFixed(1) ?? '?'} min (stale after ${dq.stale_threshold_minutes} min).` : ''
              })()}</p>
            )}
          </div>
        )}
      </div>
    </header>
  )
}
