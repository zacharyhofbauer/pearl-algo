'use client'

import { useEffect, useState, useCallback } from 'react'
import { apiFetchJson } from '@/lib/api'

interface Tier {
  min_confidence: number
  max_confidence: number
  contracts: number
}

interface ConfidenceScalingConfig {
  enabled: boolean
  tiers: Tier[]
  max_contracts: number
  long_only_scaling: boolean
}

/**
 * ContractScalingCard — Settings card for confidence-based contract scaling.
 * GATED: enabled flag stays false until 200+ clean baseline trades.
 */
export default function ContractScalingCard() {
  const [config, setConfig] = useState<ConfidenceScalingConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [toggling, setToggling] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchConfig = useCallback(async () => {
    try {
      const data = await apiFetchJson<ConfidenceScalingConfig>('/api/confidence-scaling')
      setConfig(data)
      setError(null)
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Failed to load scaling config'
      setError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  const handleToggle = async () => {
    if (!config || toggling) return
    setToggling(true)
    try {
      const updated = await apiFetchJson<ConfidenceScalingConfig>('/api/confidence-scaling', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled: !config.enabled }),
      })
      setConfig(updated)
      setError(null)
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Toggle failed'
      setError(message)
    } finally {
      setToggling(false)
    }
  }

  /**
   * Map a tier's contract count to a semantic variant class. Color comes from
   * design tokens (--accent-green / --accent-yellow / --accent-purple), not
   * hardcoded hex.
   */
  const tierVariant = (contracts: number): string => {
    if (contracts <= 1) return 'tier-one'
    if (contracts === 2) return 'tier-two'
    return 'tier-three'
  }

  // Each tier's confidence range as a fraction of the full 0–28% spread the
  // backend currently emits, used to size the visual bar. Kept inline (not in
  // CSS) because it depends on per-tier numeric data.
  const tierBarWidth = (tier: Tier): number => {
    const span = (tier.max_confidence - tier.min_confidence) * 100
    return Math.max(8, Math.min(100, (span / 28) * 100))
  }

  if (loading) {
    return (
      <div className="settings-section">
        <h3 className="settings-section-title">Contract Scaling</h3>
        <div className="contract-scaling-loading">Loading…</div>
      </div>
    )
  }

  return (
    <div className="settings-section">
      <h3 className="settings-section-title contract-scaling-title">
        Contract Scaling
        <span
          className={`contract-scaling-status ${
            config?.enabled ? 'is-active' : 'is-gated'
          }`}
        >
          {config?.enabled ? 'ACTIVE' : 'GATED'}
        </span>
      </h3>

      <div className="contract-scaling-warning" role="note">
        <span className="contract-scaling-warning-icon" aria-hidden>⚠️</span>
        <span className="contract-scaling-warning-text">
          GATED — enable only after 200+ clean baseline trades
        </span>
      </div>

      {error && <div className="contract-scaling-error">{error}</div>}

      <div className="contract-scaling-toggle-row">
        <div>
          <div className="contract-scaling-toggle-label">Confidence Scaling</div>
          <div className="contract-scaling-toggle-sub">
            Scale contracts 1→3 based on signal confidence
          </div>
        </div>
        <button
          type="button"
          onClick={handleToggle}
          disabled={toggling}
          className={`contract-scaling-toggle ${config?.enabled ? 'is-on' : 'is-off'} ${
            toggling ? 'is-busy' : ''
          }`}
          title={config?.enabled ? 'Disable scaling' : 'Enable scaling'}
          aria-pressed={config?.enabled}
        >
          <span className="contract-scaling-toggle-knob" />
        </button>
      </div>

      <div className="contract-scaling-tiers">
        <div className="contract-scaling-tiers-label">Confidence Tiers</div>
        {(config?.tiers || []).map((tier, i) => {
          const variant = tierVariant(tier.contracts)
          return (
            <div key={i} className="contract-scaling-tier">
              <div className={`contract-scaling-tier-badge ${variant}`}>
                {tier.contracts}
              </div>
              <div className="contract-scaling-tier-info">
                <div className="contract-scaling-tier-name">
                  {tier.contracts === 1 ? '1 contract' : `${tier.contracts} contracts`}
                </div>
                <div className="contract-scaling-tier-range">
                  confidence {(tier.min_confidence * 100).toFixed(0)}% – {(tier.max_confidence * 100).toFixed(0)}%
                </div>
              </div>
              <div className="contract-scaling-tier-bar">
                <div
                  className={`contract-scaling-tier-bar-fill ${variant}`}
                  style={{ width: `${tierBarWidth(tier).toFixed(0)}%` }}
                />
              </div>
            </div>
          )
        })}
      </div>

      <div className="contract-scaling-footer">
        <div className="contract-scaling-footer-item">
          Max contracts:{' '}
          <span className="contract-scaling-footer-value">{config?.max_contracts ?? 3}</span>
        </div>
        <div className="contract-scaling-footer-item">
          Long-only scaling:{' '}
          <span className="contract-scaling-footer-value">
            {config?.long_only_scaling ? 'yes' : 'no'}
          </span>
        </div>
      </div>
    </div>
  )
}
