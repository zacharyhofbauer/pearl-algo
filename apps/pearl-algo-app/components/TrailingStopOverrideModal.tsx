'use client'

import React, { useEffect, useRef, useState } from 'react'
import { apiFetch } from '@/lib/api'
import { useUIStore } from '@/stores'

interface TrailingStopOverrideModalProps {
  isOpen: boolean
  onClose: () => void
  /** Optional defaults to seed the form with current effective values. */
  defaultTrailMult?: number
  defaultActivationMult?: number
}

type ForcePhase = '' | 'breakeven' | 'lock_profit' | 'tight_trail'

interface FormState {
  trailMult: string
  activationMult: string
  forcePhase: ForcePhase
  ttlMinutes: string
  reason: string
}

const INITIAL_FORM: FormState = {
  trailMult: '1.0',
  activationMult: '1.0',
  forcePhase: '',
  ttlMinutes: '30',
  reason: '',
}

// Backend bounds — server.py:trailing_stop_override
const TRAIL_MIN = 0.5
const TRAIL_MAX = 2.0
const ACT_MIN = 0.5
const ACT_MAX = 2.0
const TTL_MIN = 1
const TTL_MAX = 120

function validate(form: FormState): { ok: boolean; errors: Partial<Record<keyof FormState, string>> } {
  const errors: Partial<Record<keyof FormState, string>> = {}

  const trail = Number(form.trailMult)
  if (!Number.isFinite(trail) || trail < TRAIL_MIN || trail > TRAIL_MAX) {
    errors.trailMult = `Must be ${TRAIL_MIN}–${TRAIL_MAX}`
  }

  const act = Number(form.activationMult)
  if (!Number.isFinite(act) || act < ACT_MIN || act > ACT_MAX) {
    errors.activationMult = `Must be ${ACT_MIN}–${ACT_MAX}`
  }

  const ttl = Number(form.ttlMinutes)
  if (!Number.isFinite(ttl) || !Number.isInteger(ttl) || ttl < TTL_MIN || ttl > TTL_MAX) {
    errors.ttlMinutes = `Integer ${TTL_MIN}–${TTL_MAX}`
  }

  if (!form.reason.trim()) {
    errors.reason = 'Required — explain why'
  } else if (form.reason.trim().length < 6) {
    errors.reason = 'Need at least 6 chars'
  }

  return { ok: Object.keys(errors).length === 0, errors }
}

function describeDelta(form: FormState, defaultTrail?: number, defaultAct?: number): string {
  const trailNew = Number(form.trailMult)
  const actNew = Number(form.activationMult)
  const parts: string[] = []
  if (defaultTrail != null && trailNew !== defaultTrail) {
    parts.push(`trail ${defaultTrail.toFixed(2)} → ${trailNew.toFixed(2)}`)
  } else {
    parts.push(`trail × ${trailNew.toFixed(2)}`)
  }
  if (defaultAct != null && actNew !== defaultAct) {
    parts.push(`activate ${defaultAct.toFixed(2)} → ${actNew.toFixed(2)}`)
  } else {
    parts.push(`activate × ${actNew.toFixed(2)}`)
  }
  if (form.forcePhase) parts.push(`force ${form.forcePhase}`)
  parts.push(`expires in ${form.ttlMinutes}m`)
  return parts.join('  ·  ')
}

function TrailingStopOverrideModal({
  isOpen,
  onClose,
  defaultTrailMult,
  defaultActivationMult,
}: TrailingStopOverrideModalProps) {
  const [form, setForm] = useState<FormState>(INITIAL_FORM)
  const [stage, setStage] = useState<'edit' | 'confirm' | 'submitting'>('edit')
  const [serverError, setServerError] = useState<string | null>(null)
  const firstFieldRef = useRef<HTMLInputElement>(null)
  const addNotification = useUIStore((s) => s.addNotification)

  // Reset on open and seed defaults from current effective values when known.
  useEffect(() => {
    if (!isOpen) return
    setForm({
      ...INITIAL_FORM,
      trailMult: defaultTrailMult != null ? defaultTrailMult.toFixed(2) : INITIAL_FORM.trailMult,
      activationMult:
        defaultActivationMult != null ? defaultActivationMult.toFixed(2) : INITIAL_FORM.activationMult,
    })
    setStage('edit')
    setServerError(null)
    setTimeout(() => firstFieldRef.current?.focus(), 80)
  }, [isOpen, defaultTrailMult, defaultActivationMult])

  // Lock body scroll while modal is open and close on Escape.
  useEffect(() => {
    if (!isOpen) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && stage !== 'submitting') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, stage, onClose])

  if (!isOpen) return null

  const { ok, errors } = validate(form)

  const handleField = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setServerError(null)
  }

  const handleSubmit = async () => {
    if (!ok) return
    setStage('submitting')
    setServerError(null)
    try {
      const body = {
        trail_atr_multiplier: Number(form.trailMult),
        activation_atr_multiplier: Number(form.activationMult),
        force_phase: form.forcePhase || null,
        ttl_minutes: Number(form.ttlMinutes),
        source: 'manual',
        reason: form.reason.trim(),
      }
      const res = await apiFetch('/api/trailing-stop/override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      const text = await res.text()
      let payload: { ok?: boolean; message?: string; warning?: string; detail?: unknown } = {}
      try {
        payload = text ? JSON.parse(text) : {}
      } catch {
        // empty body or non-JSON
      }
      if (!res.ok) {
        const detail =
          (typeof payload.detail === 'string' && payload.detail) ||
          payload.message ||
          (text && text.trim()) ||
          `HTTP ${res.status}`
        throw new Error(detail)
      }
      addNotification({
        type: 'success',
        title: 'Trailing override applied',
        message: payload.warning || payload.message || describeDelta(form, defaultTrailMult, defaultActivationMult),
      })
      onClose()
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : 'Override request failed'
      setServerError(message)
      setStage('edit')
      addNotification({
        type: 'error',
        title: 'Trailing override failed',
        message,
      })
    }
  }

  return (
    <div
      className="ts-modal-backdrop"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ts-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget && stage !== 'submitting') onClose()
      }}
    >
      <div className="ts-modal">
        <header className="ts-modal-header">
          <div>
            <div id="ts-modal-title" className="ts-modal-title">Override Trailing Stop</div>
            <div className="ts-modal-subtitle">Mutates live trailing-stop parameters across all tracked positions.</div>
          </div>
          <button
            type="button"
            className="ts-modal-close"
            onClick={onClose}
            disabled={stage === 'submitting'}
            aria-label="Close override modal"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <line x1="2" y1="2" x2="12" y2="12" />
              <line x1="12" y1="2" x2="2" y2="12" />
            </svg>
          </button>
        </header>

        {stage === 'edit' && (
          <form
            className="ts-modal-form"
            onSubmit={(e) => {
              e.preventDefault()
              if (ok) setStage('confirm')
            }}
          >
            <div className="ts-modal-field-row">
              <label className="ts-modal-field">
                <span className="ts-modal-label">Trail × ATR</span>
                <input
                  ref={firstFieldRef}
                  type="number"
                  step="0.05"
                  min={TRAIL_MIN}
                  max={TRAIL_MAX}
                  value={form.trailMult}
                  onChange={(e) => handleField('trailMult', e.target.value)}
                  className={`ts-modal-input ${errors.trailMult ? 'has-error' : ''}`}
                  required
                />
                <span className="ts-modal-hint">
                  {errors.trailMult || `Range ${TRAIL_MIN}–${TRAIL_MAX}. Default 1.0.`}
                </span>
              </label>

              <label className="ts-modal-field">
                <span className="ts-modal-label">Activate × ATR</span>
                <input
                  type="number"
                  step="0.05"
                  min={ACT_MIN}
                  max={ACT_MAX}
                  value={form.activationMult}
                  onChange={(e) => handleField('activationMult', e.target.value)}
                  className={`ts-modal-input ${errors.activationMult ? 'has-error' : ''}`}
                  required
                />
                <span className="ts-modal-hint">
                  {errors.activationMult || `Range ${ACT_MIN}–${ACT_MAX}. Default 1.0.`}
                </span>
              </label>
            </div>

            <div className="ts-modal-field-row">
              <label className="ts-modal-field">
                <span className="ts-modal-label">Force Phase</span>
                <select
                  className="ts-modal-input ts-modal-select"
                  value={form.forcePhase}
                  onChange={(e) => handleField('forcePhase', e.target.value as ForcePhase)}
                >
                  <option value="">— do not force —</option>
                  <option value="breakeven">breakeven</option>
                  <option value="lock_profit">lock_profit</option>
                  <option value="tight_trail">tight_trail</option>
                </select>
                <span className="ts-modal-hint">Pin every active position to this phase. Leave blank for normal phase progression.</span>
              </label>

              <label className="ts-modal-field">
                <span className="ts-modal-label">TTL (minutes)</span>
                <input
                  type="number"
                  step="1"
                  min={TTL_MIN}
                  max={TTL_MAX}
                  value={form.ttlMinutes}
                  onChange={(e) => handleField('ttlMinutes', e.target.value)}
                  className={`ts-modal-input ${errors.ttlMinutes ? 'has-error' : ''}`}
                  required
                />
                <span className="ts-modal-hint">
                  {errors.ttlMinutes || `Auto-clears after this many minutes. ${TTL_MIN}–${TTL_MAX}.`}
                </span>
              </label>
            </div>

            <label className="ts-modal-field ts-modal-field-full">
              <span className="ts-modal-label">Reason (required)</span>
              <textarea
                className={`ts-modal-input ts-modal-textarea ${errors.reason ? 'has-error' : ''}`}
                value={form.reason}
                onChange={(e) => handleField('reason', e.target.value)}
                rows={2}
                placeholder="e.g. CPI release in 5 min — tighten trail to lock open profit"
                required
              />
              <span className="ts-modal-hint">
                {errors.reason || 'Explain the why. Logged with the override and shown in the panel callout.'}
              </span>
            </label>

            {serverError && <div className="ts-modal-error">{serverError}</div>}

            <div className="ts-modal-actions">
              <button type="button" className="ts-modal-btn ts-modal-btn-neutral" onClick={onClose}>
                Cancel
              </button>
              <button
                type="submit"
                className="ts-modal-btn ts-modal-btn-primary"
                disabled={!ok}
              >
                Review →
              </button>
            </div>
          </form>
        )}

        {(stage === 'confirm' || stage === 'submitting') && (
          <div className="ts-modal-confirm">
            <div className="ts-modal-confirm-warning">
              <span className="ts-modal-confirm-icon" aria-hidden>⚠️</span>
              <span>
                About to mutate live trailing-stop parameters across{' '}
                <strong>every tracked position</strong>. This is an operator action.
              </span>
            </div>

            <div className="ts-modal-confirm-summary">
              <div className="ts-modal-confirm-row">
                <span className="ts-modal-confirm-label">Effective change</span>
                <span className="ts-modal-confirm-value">
                  {describeDelta(form, defaultTrailMult, defaultActivationMult)}
                </span>
              </div>
              <div className="ts-modal-confirm-row">
                <span className="ts-modal-confirm-label">Reason</span>
                <span className="ts-modal-confirm-value ts-modal-confirm-reason">
                  {form.reason.trim()}
                </span>
              </div>
            </div>

            {serverError && <div className="ts-modal-error">{serverError}</div>}

            <div className="ts-modal-actions">
              <button
                type="button"
                className="ts-modal-btn ts-modal-btn-neutral"
                onClick={() => setStage('edit')}
                disabled={stage === 'submitting'}
              >
                ← Back
              </button>
              <button
                type="button"
                className="ts-modal-btn ts-modal-btn-danger"
                onClick={handleSubmit}
                disabled={stage === 'submitting'}
              >
                {stage === 'submitting' ? 'Applying…' : 'Confirm Override'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

export default React.memo(TrailingStopOverrideModal)
