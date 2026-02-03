'use client'

import Image from 'next/image'
import {
  useAgentStore,
  useChartStore,
  selectAIMode,
  selectRegimeBadge,
  type Timeframe,
} from '@/stores'
import { formatPnL } from '@/lib/formatters'

const formatMarketCountdown = (marketStatus: { is_open: boolean; next_open?: string | null } | null) => {
  if (!marketStatus) return null

  if (marketStatus.is_open) {
    return null
  } else if (marketStatus.next_open) {
    try {
      const nextOpen = new Date(marketStatus.next_open)
      const now = new Date()
      const diffMs = nextOpen.getTime() - now.getTime()
      if (diffMs <= 0) return null

      const hours = Math.floor(diffMs / (1000 * 60 * 60))
      const minutes = Math.floor((diffMs % (1000 * 60 * 60)) / (1000 * 60))

      if (hours > 24) {
        const days = Math.floor(hours / 24)
        return `Opens in ${days}d ${hours % 24}h`
      }
      return `Opens in ${hours}h ${minutes}m`
    } catch {
      return null
    }
  }
  return null
}

interface DashboardHeaderProps {
  variant?: 'standard' | 'ultrawide'
}

export function DashboardHeader({ variant = 'standard' }: DashboardHeaderProps) {
  // Agent store
  const agentState = useAgentStore((s) => s.agentState)
  const aiMode = useAgentStore(selectAIMode)
  const regimeBadge = useAgentStore(selectRegimeBadge)

  // Chart store
  const timeframe = useChartStore((s) => s.timeframe)
  const setTimeframe = useChartStore((s) => s.setTimeframe)
  const marketStatus = useChartStore((s) => s.marketStatus)

  const countdown = formatMarketCountdown(marketStatus)
  const dirGate = agentState?.ai_status?.direction_gating

  // Ultrawide compact header
  if (variant === 'ultrawide') {
    return (
      <div className="ultrawide-header">
        <div className="uw-brand">
          <Image src="/logo.png" alt="PEARL" width={20} height={20} priority />
          <span className="uw-symbol">MNQ</span>
        </div>
        <div className="uw-stats">
          <span className={`uw-pnl ${(agentState?.daily_pnl || 0) >= 0 ? 'positive' : 'negative'}`}>
            {(agentState?.daily_pnl || 0) >= 0 ? '+' : ''}${(agentState?.daily_pnl || 0).toFixed(0)}
          </span>
          <span className="uw-trades">
            {agentState?.daily_wins || 0}W/{agentState?.daily_losses || 0}L
          </span>
        </div>
        <div className="uw-timeframe">
          {(['1m', '5m', '15m', '30m', '1h', '4h', '1D'] as Timeframe[]).map((tf) => (
            <button
              key={tf}
              className={`uw-tf-btn ${timeframe === tf ? 'active' : ''}`}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>
    )
  }

  // Standard header
  return (
    <header className="header-combined">
      {/* Main Header Row */}
      <div className="header-row-main">
        {/* Brand */}
        <div className="header-brand">
          <Image src="/logo.png" alt="PEARL" width={28} height={28} className="header-logo" priority />
          <div className="header-titles">
            <span className="header-symbol">MNQ</span>
            <span className="header-app-name">Pearl Algo Web App</span>
          </div>
        </div>

        {/* Stats - with ARIA live region for real-time updates */}
        {agentState && (
          <div className="header-stats-row" aria-live="polite" aria-atomic="true">
            <div className={`stat-item pnl ${agentState.daily_pnl >= 0 ? 'positive' : 'negative'}`}>
              <span className="stat-label">P&L</span>
              <span className="stat-value" aria-label={`Daily P&L: ${formatPnL(agentState.daily_pnl)}`}>
                {formatPnL(agentState.daily_pnl)}
              </span>
            </div>
            <div className="stat-item trades">
              <span className="stat-label">W/L</span>
              <span className="stat-value" aria-label={`Wins: ${agentState.daily_wins}, Losses: ${agentState.daily_losses}`}>
                <span className="win">{agentState.daily_wins}</span>/<span className="loss">{agentState.daily_losses}</span>
              </span>
            </div>
            {agentState.active_trades_count > 0 && (
              <div className="stat-item positions">
                <span className="stat-value highlight" aria-label={`${agentState.active_trades_count} active positions`}>
                  {agentState.active_trades_count} pos
                </span>
              </div>
            )}
          </div>
        )}

        {/* Timeframe */}
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
      </div>

      {/* Secondary Row - Badges, Health, Legends */}
      <div className="header-row-secondary">
        {/* Badges - with ARIA live region for status changes */}
        <div className="header-badges" role="status" aria-live="polite">
          {agentState && (
            <span
              className={`badge agent-badge ${agentState.running ? (agentState.paused ? 'paused' : 'running') : 'stopped'}`}
              aria-label={`Agent status: ${agentState.running ? (agentState.paused ? 'paused' : 'running') : 'stopped'}`}
            >
              <span className="badge-dot" aria-hidden="true"></span>
              {agentState.running ? (agentState.paused ? 'PAUSED' : 'RUNNING') : 'STOPPED'}
            </span>
          )}
          {aiMode && (
            <span className={`badge ai-badge ${aiMode}`}>
              🧠 {aiMode.toUpperCase()}
            </span>
          )}
          {regimeBadge && (
            <span className={`badge regime-badge`}>
              {regimeBadge.icon} {regimeBadge.label}
            </span>
          )}
          {marketStatus && (
            <span className={`badge market-badge ${marketStatus.is_open ? 'open' : 'closed'}`}>
              {marketStatus.is_open ? '🟢 OPEN' : '🔴 CLOSED'}
              {countdown && <span className="countdown">{countdown}</span>}
            </span>
          )}
        </div>

        {/* Health Indicators */}
        {agentState && (
          <div className="header-health">
            <span className={`health-dot ${agentState.gateway_status?.status === 'online' ? 'ok' : 'error'}`}></span>
            <span className="health-label">GW</span>
            <span className={`health-dot ${agentState.data_fresh ? 'ok' : 'error'}`}></span>
            <span className="health-label">Data</span>
            <span className={`health-dot ${agentState.futures_market_open ? 'ok' : 'warning'}`}></span>
            <span className="health-label">Mkt</span>
            {dirGate?.enabled && (
              <>
                <span className={`health-dot ${dirGate.blocks > 0 ? 'warning' : 'ok'}`}></span>
                <span className="health-label">{dirGate.blocks > 0 ? `${dirGate.blocks}🚫` : 'Gate✓'}</span>
              </>
            )}
          </div>
        )}

        {/* Chart Legend */}
        <div className="header-legend">
          <span className="legend-item"><span className="legend-line ema9"></span>EMA9</span>
          <span className="legend-item"><span className="legend-line ema21"></span>EMA21</span>
          <span className="legend-item"><span className="legend-line vwap"></span>VWAP</span>
          <span className="legend-item"><span className="legend-marker long">▲</span>Long</span>
          <span className="legend-item"><span className="legend-marker short">▼</span>Short</span>
          <span className="legend-item"><span className="legend-marker win">●</span>Win</span>
          <span className="legend-item"><span className="legend-marker loss">●</span>Loss</span>
        </div>
      </div>
    </header>
  )
}

export default DashboardHeader
