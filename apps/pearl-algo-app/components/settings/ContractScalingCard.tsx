'use client'

// ADDED 2026-03-25: confidence scaling
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
 * ADDED 2026-03-25: confidence scaling
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
    } catch (e: any) {
      setError(e?.message || 'Failed to load scaling config')
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
    } catch (e: any) {
      setError(e?.message || 'Toggle failed')
    } finally {
      setToggling(false)
    }
  }

  const CONTRACT_COLORS: Record<number, string> = {
    1: '#4ade80',  // green
    2: '#facc15',  // yellow
    3: '#f97316',  // orange
  }

  if (loading) {
    return (
      <div className="settings-section">
        <h3 className="settings-section-title">Contract Scaling</h3>
        <div style={{ padding: '16px', color: '#94a3b8', fontSize: '13px' }}>Loading…</div>
      </div>
    )
  }

  return (
    <div className="settings-section">
      <h3 className="settings-section-title" style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        Contract Scaling
        <span style={{
          fontSize: '11px',
          fontWeight: 500,
          color: config?.enabled ? '#4ade80' : '#94a3b8',
          background: config?.enabled ? 'rgba(74,222,128,0.12)' : 'rgba(148,163,184,0.12)',
          border: `1px solid ${config?.enabled ? 'rgba(74,222,128,0.3)' : 'rgba(148,163,184,0.25)'}`,
          borderRadius: '4px',
          padding: '2px 8px',
        }}>
          {config?.enabled ? 'ACTIVE' : 'GATED'}
        </span>
      </h3>

      {/* Warning banner */}
      <div style={{
        background: 'rgba(251,191,36,0.08)',
        border: '1px solid rgba(251,191,36,0.3)',
        borderRadius: '6px',
        padding: '10px 14px',
        marginBottom: '16px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px',
      }}>
        <span style={{ fontSize: '16px' }}>⚠️</span>
        <span style={{ fontSize: '12px', color: '#fbbf24', fontWeight: 500 }}>
          GATED — enable only after 200+ clean baseline trades
        </span>
      </div>

      {error && (
        <div style={{ color: '#f87171', fontSize: '12px', marginBottom: '12px' }}>
          {error}
        </div>
      )}

      {/* Toggle */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '12px 0',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
        marginBottom: '16px',
      }}>
        <div>
          <div style={{ fontSize: '13px', fontWeight: 500, color: '#e2e8f0' }}>
            Confidence Scaling
          </div>
          <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px' }}>
            Scale contracts 1→3 based on signal confidence
          </div>
        </div>
        <button
          onClick={handleToggle}
          disabled={toggling}
          style={{
            position: 'relative',
            width: '44px',
            height: '24px',
            borderRadius: '12px',
            border: 'none',
            cursor: toggling ? 'not-allowed' : 'pointer',
            background: config?.enabled ? '#22c55e' : '#334155',
            transition: 'background 0.2s',
            outline: 'none',
            opacity: toggling ? 0.6 : 1,
          }}
          title={config?.enabled ? 'Disable scaling' : 'Enable scaling'}
        >
          <span style={{
            position: 'absolute',
            top: '2px',
            left: config?.enabled ? '22px' : '2px',
            width: '20px',
            height: '20px',
            borderRadius: '50%',
            background: '#fff',
            transition: 'left 0.2s',
            display: 'block',
          }} />
        </button>
      </div>

      {/* Tier display */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        <div style={{ fontSize: '11px', color: '#64748b', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Confidence Tiers
        </div>
        {(config?.tiers || []).map((tier, i) => (
          <div key={i} style={{
            display: 'flex',
            alignItems: 'center',
            gap: '12px',
            padding: '10px 14px',
            background: 'rgba(255,255,255,0.03)',
            border: '1px solid rgba(255,255,255,0.06)',
            borderRadius: '6px',
          }}>
            {/* Contract count badge */}
            <div style={{
              minWidth: '28px',
              height: '28px',
              borderRadius: '6px',
              background: `${CONTRACT_COLORS[tier.contracts] || '#94a3b8'}22`,
              border: `1px solid ${CONTRACT_COLORS[tier.contracts] || '#94a3b8'}44`,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '13px',
              fontWeight: 700,
              color: CONTRACT_COLORS[tier.contracts] || '#94a3b8',
              fontFamily: 'monospace',
            }}>
              {tier.contracts}
            </div>
            {/* Confidence range */}
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: '12px', color: '#e2e8f0', fontWeight: 500 }}>
                {tier.contracts === 1 ? '1 contract' : `${tier.contracts} contracts`}
              </div>
              <div style={{ fontSize: '11px', color: '#64748b', marginTop: '2px', fontFamily: 'monospace' }}>
                confidence {(tier.min_confidence * 100).toFixed(0)}% – {(tier.max_confidence * 100).toFixed(0)}%
              </div>
            </div>
            {/* Visual bar */}
            <div style={{ width: '80px' }}>
              <div style={{
                height: '4px',
                borderRadius: '2px',
                background: 'rgba(255,255,255,0.06)',
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${(tier.max_confidence - tier.min_confidence) * 100 / 0.28 * 100}%`,
                  background: CONTRACT_COLORS[tier.contracts] || '#94a3b8',
                  borderRadius: '2px',
                  opacity: 0.7,
                }} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Footer info */}
      <div style={{ marginTop: '16px', display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
        <div style={{ fontSize: '11px', color: '#64748b' }}>
          Max contracts: <span style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>{config?.max_contracts ?? 3}</span>
        </div>
        <div style={{ fontSize: '11px', color: '#64748b' }}>
          Long-only scaling: <span style={{ color: '#e2e8f0', fontFamily: 'monospace' }}>{config?.long_only_scaling ? 'yes' : 'no'}</span>
        </div>
      </div>
    </div>
  )
}
