'use client'

import { useState, useEffect, useRef } from 'react'
import { useAdminStore } from '@/stores'

export default function AdminAuthModal() {
  const { showAuthModal, authenticate, closeAuthModal } = useAdminStore()
  const [password, setPassword] = useState('')
  const [error, setError] = useState(false)
  const [attempts, setAttempts] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // Focus input when modal opens
  useEffect(() => {
    if (showAuthModal && inputRef.current) {
      inputRef.current.focus()
    }
  }, [showAuthModal])

  // Reset state when modal closes
  useEffect(() => {
    if (!showAuthModal) {
      setPassword('')
      setError(false)
    }
  }, [showAuthModal])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const success = authenticate(password.toLowerCase().trim())
    if (!success) {
      setError(true)
      setAttempts(prev => prev + 1)
      setPassword('')
      inputRef.current?.focus()
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      closeAuthModal()
    }
  }

  // Fun error messages
  const getErrorMessage = () => {
    const messages = [
      "Hmm, that is not quite right, boss.",
      "Pearl does not recognize that phrase.",
      "Access denied. Try the magic words?",
      "Nope. I am gonna need the real passphrase.",
      "Nice try, but Pearl is not that easy.",
    ]
    return messages[attempts % messages.length]
  }

  if (!showAuthModal) return null

  return (
    <div className="admin-auth-overlay" onClick={closeAuthModal} onKeyDown={handleKeyDown}>
      <div className="admin-auth-modal pearl-auth-modal" onClick={(e) => e.stopPropagation()}>
        <div className="auth-modal-header">
          <span className="auth-modal-icon">🦪</span>
          <span className="auth-modal-title">Pearl Protocol</span>
        </div>
        <div className="pearl-greeting">
          Good {new Date().getHours() < 12 ? 'morning' : new Date().getHours() < 18 ? 'afternoon' : 'evening'}, boss.
          <br />
          <span className="pearl-subtext">Authentication required.</span>
        </div>
        <form onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            className={`auth-modal-input ${error ? 'error' : ''}`}
            placeholder="Speak the words..."
            value={password}
            onChange={(e) => {
              setPassword(e.target.value)
              setError(false)
            }}
            autoComplete="off"
          />
          {error && <div className="auth-modal-error">{getErrorMessage()}</div>}
          <div className="auth-modal-actions">
            <button type="button" className="auth-btn auth-btn-cancel" onClick={closeAuthModal}>
              Nevermind
            </button>
            <button type="submit" className="auth-btn auth-btn-submit" disabled={!password}>
              Unlock
            </button>
          </div>
        </form>
        <div className="pearl-footer">
          <span className="pearl-status">
            <span className="status-dot"></span>
            Systems ready
          </span>
        </div>
      </div>
    </div>
  )
}
