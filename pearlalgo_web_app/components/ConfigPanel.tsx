'use client'

import { DataPanel } from './DataPanelsContainer'

interface Config {
  symbol: string
  market: string
  timeframe: string
  scan_interval: number
  session_start: string
  session_end: string
  mode: 'live' | 'shadow' | 'paused' | 'stopped'
}

interface ConfigPanelProps {
  config: Config
}

// Market name mapping
const MARKET_NAMES: Record<string, string> = {
  'ES': 'E-mini S&P 500',
  'MES': 'Micro E-mini S&P 500',
  'NQ': 'E-mini Nasdaq-100',
  'MNQ': 'Micro E-mini Nasdaq-100',
  'RTY': 'E-mini Russell 2000',
  'M2K': 'Micro E-mini Russell 2000',
  'YM': 'E-mini Dow',
  'MYM': 'Micro E-mini Dow',
  'CL': 'Crude Oil',
  'GC': 'Gold',
}

export default function ConfigPanel({ config }: ConfigPanelProps) {
  const getModeClass = () => {
    switch (config.mode) {
      case 'live': return 'mode-live'
      case 'shadow': return 'mode-shadow'
      case 'paused': return 'mode-paused'
      case 'stopped': return 'mode-stopped'
      default: return ''
    }
  }

  const getModeLabel = () => {
    switch (config.mode) {
      case 'live': return 'LIVE'
      case 'shadow': return 'SHADOW'
      case 'paused': return 'PAUSED'
      case 'stopped': return 'STOPPED'
    }
  }

  const getMarketDescription = () => {
    const symbol = config.symbol || config.market
    return MARKET_NAMES[symbol] || MARKET_NAMES[config.market] || ''
  }

  return (
    <DataPanel title="Config" icon="⚙️">
      <div className="config-panel-content">
        {/* Market/Symbol */}
        <div className="config-row">
          <span className="config-label">Market</span>
          <span className="config-value">
            <span className="config-symbol">{config.symbol || config.market}</span>
            {getMarketDescription() && (
              <span className="config-description">{getMarketDescription()}</span>
            )}
          </span>
        </div>

        {/* Timeframe */}
        <div className="config-row">
          <span className="config-label">Timeframe</span>
          <span className="config-value">{config.timeframe}</span>
        </div>

        {/* Scan Interval */}
        <div className="config-row">
          <span className="config-label">Interval</span>
          <span className="config-value">{config.scan_interval}s</span>
        </div>

        {/* Session Times */}
        <div className="config-row">
          <span className="config-label">Session</span>
          <span className="config-value">
            {config.session_start} - {config.session_end} ET
          </span>
        </div>

        {/* Agent Mode */}
        <div className="config-row">
          <span className="config-label">Mode</span>
          <span className={`config-mode ${getModeClass()}`}>
            <span className="mode-dot"></span>
            {getModeLabel()}
          </span>
        </div>
      </div>
    </DataPanel>
  )
}
