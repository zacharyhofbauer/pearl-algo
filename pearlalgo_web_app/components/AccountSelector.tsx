'use client'

/**
 * Full-screen account selection prompt.
 *
 * Shown on initial load when no ?account= param is present and no
 * stored preference exists. Lets the user pick which account to view.
 * Remembers the choice in localStorage so it doesn't ask again until
 * the user explicitly clears it or switches via the header dropdown.
 */

import { useEffect, useRef, useCallback } from 'react'
import Image from 'next/image'

interface AccountOption {
  id: string
  label: string
  description: string
  param: string | null  // URL ?account= value (null = default/inception)
  badge: string
  badgeColor: string
}

const ACCOUNTS: AccountOption[] = [
  {
    id: 'inception',
    label: 'Inception',
    description: 'Since-inception data collection and monitoring',
    param: null,
    badge: 'LIVE',
    badgeColor: '#00e676',
  },
  {
    id: 'mffu_eval',
    label: 'MFFU 50K Eval',
    description: 'Prop firm evaluation on Tradovate paper',
    param: 'mffu',
    badge: 'EVAL',
    badgeColor: '#7c4dff',
  },
]

const LS_KEY = 'pearl.account.selected'

interface AccountSelectorProps {
  onSelect: (accountParam: string | null) => void
}

export default function AccountSelector({ onSelect }: AccountSelectorProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const firstButtonRef = useRef<HTMLButtonElement>(null)

  // Focus trap: keep focus within the dialog
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key !== 'Tab') return
    const dialog = dialogRef.current
    if (!dialog) return

    const focusable = dialog.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
    )
    if (focusable.length === 0) return

    const first = focusable[0]
    const last = focusable[focusable.length - 1]

    if (e.shiftKey) {
      if (document.activeElement === first) {
        e.preventDefault()
        last.focus()
      }
    } else {
      if (document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
  }, [])

  // Auto-focus first option on mount; attach focus trap
  useEffect(() => {
    firstButtonRef.current?.focus()
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  return (
    <div
      className="account-selector-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="account-selector-title"
      ref={dialogRef}
    >
      <div className="account-selector-card">
        <div className="account-selector-header">
          <Image src="/pearl-emoji.png" alt="" width={32} height={32} priority />
          <h2 id="account-selector-title">Select Account</h2>
        </div>
        <p className="account-selector-subtitle">
          Choose which account to view. You can switch anytime using the dropdown in the header bar.
        </p>
        <div className="account-selector-options" role="group" aria-label="Account options">
          {ACCOUNTS.map((acct, idx) => (
            <button
              key={acct.id}
              ref={idx === 0 ? firstButtonRef : undefined}
              className="account-selector-option"
              onClick={() => {
                // Persist choice
                try {
                  localStorage.setItem(LS_KEY, acct.id)
                } catch { /* ignore */ }
                onSelect(acct.param)
              }}
              type="button"
              aria-label={`${acct.label} — ${acct.description}`}
            >
              <div className="account-selector-option-top">
                <span className="account-selector-badge" style={{ background: acct.badgeColor }}>
                  {acct.badge}
                </span>
                <span className="account-selector-label">{acct.label}</span>
              </div>
              <span className="account-selector-desc">{acct.description}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

/**
 * Check if the account selector should be shown.
 *
 * Always shows on a clean pearlalgo.io load (no ?account= param).
 * Only skips if the URL already has an explicit account selection.
 */
export function shouldShowAccountSelector(): boolean {
  if (typeof window === 'undefined') return false

  // If URL already has an account param, user already chose -- don't show
  const params = new URLSearchParams(window.location.search)
  if (params.has('account') || params.has('api_port')) return false

  // Always show the selector on a clean URL (pearlalgo.io with no params)
  return true
}

/**
 * Get the stored account preference.
 * No longer auto-applies -- always returns undefined so the selector shows.
 */
export function getStoredAccountParam(): string | null | undefined {
  // Always return undefined so the AccountGate shows the selector
  // The selector handles navigation after user picks
  return undefined
}
