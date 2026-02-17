'use client'

/**
 * Full-screen account selection prompt.
 *
 * Shown on initial load when no ?account= param is present and no
 * stored preference exists. Lets the user pick which account to view.
 * Remembers the choice in localStorage so it doesn't ask again until
 * the user explicitly clears it or switches via the header dropdown.
 */

import { useEffect, useRef, useCallback, useMemo } from 'react'
import Image from 'next/image'
import { useAgentStore } from '@/stores'

interface AccountOption {
  id: string
  label: string
  description: string
  param: string | null  // URL ?account= value (null = default/ibkr_virtual)
  badge: string
  badgeColor: string
  archived?: boolean
}

/** Fallback defaults used when the store has no accounts config yet.
 * Tradovate Paper (live) first, IBKR Virtual (archived) second. */
const ACCOUNT_DEFAULTS: AccountOption[] = [
  {
    id: 'tv_paper_eval',
    label: 'Tradovate Paper',
    description: 'Live paper trading on Tradovate (demo)',
    param: 'tv_paper',
    badge: 'PAPER',
    badgeColor: 'var(--accent-purple, #7c4dff)',
  },
  {
    id: 'ibkr_virtual',
    label: 'IBKR Virtual',
    description: 'Archived — full history since inception',
    param: null,
    badge: 'ARCHIVED',
    badgeColor: 'rgba(255, 255, 255, 0.25)',
    archived: true,
  },
]

const LS_KEY = 'pearl.account.selected'

interface AccountSelectorProps {
  onSelect: (accountParam: string | null) => void
}

export default function AccountSelector({ onSelect }: AccountSelectorProps) {
  const dialogRef = useRef<HTMLDivElement>(null)
  const firstButtonRef = useRef<HTMLButtonElement>(null)
  const storeAccounts = useAgentStore((s) => s.accounts)

  // Merge store config over fallback defaults (display_name, badge, etc.)
  // For archived accounts, keep frontend badge/description/badgeColor
  const accounts = useMemo(() => {
    if (!storeAccounts) return ACCOUNT_DEFAULTS
    return ACCOUNT_DEFAULTS.map((def) => {
      const configKey = def.param || def.id
      const cfg = storeAccounts[configKey]
      if (!cfg) return def
      if (def.archived) {
        return { ...def, label: cfg.display_name ?? def.label }
      }
      return {
        ...def,
        label: cfg.display_name,
        description: cfg.description,
        badge: cfg.badge,
        badgeColor: cfg.badge_color,
      }
    })
  }, [storeAccounts])

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
          {accounts.map((acct, idx) => (
            <button
              key={acct.id}
              ref={idx === 0 ? firstButtonRef : undefined}
              className={`account-selector-option${acct.archived ? ' archived' : ''}`}
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
              {acct.archived && (
                <span className="account-selector-view-history">View history</span>
              )}
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
