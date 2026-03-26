'use client'

import React, { useState, useEffect, useRef } from 'react'
import { useOperatorStore } from '@/stores'
import { getApiUrl } from '@/lib/api'

// FIXED 2026-03-25: Session-only unlock modal. Validates passphrase against backend.
// Unlocked for the entire page session — hard reload resets.

interface OperatorUnlockModalProps {
  isOpen: boolean
  onClose: () => void
  onUnlocked?: () => void
}

export default function OperatorUnlockModal({ isOpen, onClose, onUnlocked }: OperatorUnlockModalProps) {
  const [input, setInput] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const unlock = useOperatorStore((s) => s.unlock)

  useEffect(() => {
    if (isOpen) {
      setInput('')
      setError('')
      setTimeout(() => inputRef.current?.focus(), 80)
    }
  }, [isOpen])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const phrase = input.trim()
    if (!phrase) return
    setLoading(true)
    setError('')

    try {
      const res = await fetch(getApiUrl() + '/api/operator/ping', {
        method: 'GET',
        headers: { 'X-PEARL-OPERATOR': phrase },
      })
      if (res.ok) {
        unlock(phrase)
        setInput('')
        onClose()
        onUnlocked?.()
      } else {
        setError('Incorrect passphrase')
        setInput('')
        inputRef.current?.focus()
      }
    } catch {
      setError('Connection error — try again')
    } finally {
      setLoading(false)
    }
  }

  if (!isOpen) return null

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 9999,
        background: 'rgba(0,0,0,0.75)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div style={{
        background: '#131722',
        border: '1px solid #2a2e39',
        borderRadius: 8,
        padding: '28px 32px',
        width: 320,
        boxShadow: '0 8px 40px rgba(0,0,0,0.7)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
          <span style={{ fontSize: 20 }}>🔒</span>
          <div>
            <div style={{ color: '#e0e3eb', fontWeight: 600, fontSize: 14 }}>Operator Access Required</div>
            <div style={{ color: '#64748b', fontSize: 11, marginTop: 2 }}>Enter passphrase to unlock controls</div>
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="password"
            value={input}
            onChange={e => { setInput(e.target.value); setError('') }}
            placeholder="Passphrase"
            autoComplete="current-password"
            style={{
              width: '100%',
              background: '#0f1117',
              border: `1px solid ${error ? '#f44336' : '#2a2e39'}`,
              borderRadius: 4,
              color: '#e0e3eb',
              padding: '9px 12px',
              fontSize: 14,
              outline: 'none',
              boxSizing: 'border-box',
              fontFamily: 'inherit',
              transition: 'border-color 0.15s',
            }}
          />
          {error && (
            <div style={{ color: '#f44336', fontSize: 11, marginTop: 6 }}>{error}</div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 16 }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                flex: 1, padding: '9px 0', borderRadius: 4,
                border: '1px solid #2a2e39', background: 'transparent',
                color: '#64748b', cursor: 'pointer', fontSize: 13,
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading || !input.trim()}
              style={{
                flex: 1, padding: '9px 0', borderRadius: 4,
                border: 'none',
                background: loading || !input.trim() ? '#1a2332' : '#1565c0',
                color: loading || !input.trim() ? '#546e7a' : '#fff',
                cursor: loading || !input.trim() ? 'not-allowed' : 'pointer',
                fontSize: 13, fontWeight: 600, transition: 'background 0.15s',
              }}
            >
              {loading ? 'Verifying…' : 'Unlock'}
            </button>
          </div>
        </form>

        <div style={{ color: '#37474f', fontSize: 10, textAlign: 'center', marginTop: 14 }}>
          Unlocked for this session — resets on page reload
        </div>
      </div>
    </div>
  )
}
