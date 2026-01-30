'use client'

import { DataPanel } from './DataPanelsContainer'

interface ShadowCounters {
  would_block_total: number
  would_block_by_reason: Record<string, number>
  ml_would_skip: number
  ml_total_decisions: number
  ml_execute_rate: number
}

interface AIStatusPanelProps {
  aiStatus: {
    bandit_mode: 'off' | 'shadow' | 'live'
    contextual_mode: 'off' | 'shadow' | 'live'
    ml_filter: {
      enabled: boolean
      mode: string
      lift: {
        lift_ok?: boolean
        lift_win_rate?: number
        lift_avg_pnl?: number
      }
    }
    direction_gating: {
      enabled: boolean
      blocks: number
      shadow_regime: number
      shadow_trigger: number
    }
  }
  shadowCounters?: ShadowCounters | null
}

type Mode = 'off' | 'shadow' | 'live'

function ModePill({ label, mode }: { label: string; mode: Mode }) {
  const getModeClass = () => {
    switch (mode) {
      case 'live':
        return 'ai-pill-live'
      case 'shadow':
        return 'ai-pill-shadow'
      default:
        return 'ai-pill-off'
    }
  }

  const getModeLabel = () => {
    switch (mode) {
      case 'live':
        return 'LIVE'
      case 'shadow':
        return 'SHADOW'
      default:
        return 'OFF'
    }
  }

  return (
    <div className={`ai-pill ${getModeClass()}`}>
      <span className="ai-pill-label">{label}</span>
      <span className="ai-pill-mode">{getModeLabel()}</span>
    </div>
  )
}

export default function AIStatusPanel({ aiStatus, shadowCounters }: AIStatusPanelProps) {
  const mlMode = aiStatus.ml_filter.enabled
    ? (aiStatus.ml_filter.mode === 'live' ? 'live' : 'shadow')
    : 'off'

  return (
    <DataPanel title="AI Status" icon="🤖">
      <div className="ai-pills">
        <ModePill label="Bandit" mode={aiStatus.bandit_mode as Mode} />
        <ModePill label="Contextual" mode={aiStatus.contextual_mode as Mode} />
        <ModePill label="ML Filter" mode={mlMode as Mode} />
      </div>

      {aiStatus.ml_filter.enabled && aiStatus.ml_filter.lift && (
        <div className="ai-lift-status">
          <span className={`ai-lift-indicator ${aiStatus.ml_filter.lift.lift_ok ? 'lift-ok' : 'lift-fail'}`}>
            Lift: {aiStatus.ml_filter.lift.lift_ok ? 'OK' : 'N/A'}
          </span>
          {aiStatus.ml_filter.lift.lift_win_rate !== undefined && (
            <span className="ai-lift-value">
              WR: {(aiStatus.ml_filter.lift.lift_win_rate * 100).toFixed(1)}%
            </span>
          )}
          {aiStatus.ml_filter.lift.lift_avg_pnl !== undefined && (
            <span className={`ai-lift-value ${aiStatus.ml_filter.lift.lift_avg_pnl >= 0 ? 'lift-pnl-positive' : 'lift-pnl-negative'}`}>
              P&L: {aiStatus.ml_filter.lift.lift_avg_pnl >= 0 ? '+' : ''}${aiStatus.ml_filter.lift.lift_avg_pnl.toFixed(2)}
            </span>
          )}
        </div>
      )}

      {aiStatus.direction_gating.enabled && (
        <div className="ai-gating">
          <div className="ai-gating-header">
            <span className="ai-gating-label">Direction Gating</span>
            <span className="ai-gating-enabled">ON</span>
          </div>
          <div className="ai-gating-stats">
            {aiStatus.direction_gating.blocks > 0 && (
              <span className="ai-gating-stat">
                <span className="gating-count">{aiStatus.direction_gating.blocks}</span>
                <span className="gating-label">blocks</span>
              </span>
            )}
            {aiStatus.direction_gating.shadow_regime > 0 && (
              <span className="ai-gating-stat">
                <span className="gating-count">{aiStatus.direction_gating.shadow_regime}</span>
                <span className="gating-label">regime (shadow)</span>
              </span>
            )}
            {aiStatus.direction_gating.shadow_trigger > 0 && (
              <span className="ai-gating-stat">
                <span className="gating-count">{aiStatus.direction_gating.shadow_trigger}</span>
                <span className="gating-label">trigger (shadow)</span>
              </span>
            )}
          </div>
        </div>
      )}

      {/* Shadow Mode Counters */}
      {shadowCounters && shadowCounters.would_block_total > 0 && (
        <div className="ai-shadow-counters">
          <div className="shadow-counter-header">
            <span className="shadow-counter-label">Shadow Mode Activity</span>
          </div>
          <div className="shadow-counter-row">
            <span className="shadow-counter-text">
              Would have blocked <strong>{shadowCounters.would_block_total}</strong> signals today
            </span>
          </div>
          {shadowCounters.ml_would_skip > 0 && (
            <div className="shadow-counter-row">
              <span className="shadow-counter-text">
                ML would skip <strong>{shadowCounters.ml_would_skip}</strong> of {shadowCounters.ml_total_decisions}
              </span>
              <span className="shadow-counter-rate">
                ({((1 - shadowCounters.ml_execute_rate) * 100).toFixed(0)}%)
              </span>
            </div>
          )}
        </div>
      )}
    </DataPanel>
  )
}
