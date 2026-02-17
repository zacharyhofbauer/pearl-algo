'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAgentStore } from '@/stores'

/**
 * Account definition for the switcher.
 * Each account maps to a separate API server port and state directory.
 */
interface AccountDef {
  id: string
  label: string
  shortLabel: string
  /** URL param value for ?account= (null = default/ibkr_virtual) */
  accountParam: string | null
  badge?: string
  badgeColor?: string
  archived?: boolean
}

/** Fallback defaults used when the store has no accounts config yet.
 * Tradovate Paper (live) first, IBKR Virtual (archived) second. */
const ACCOUNT_DEFAULTS: AccountDef[] = [
  {
    id: 'tv_paper_eval',
    label: 'Tradovate Paper',
    shortLabel: 'TV',
    accountParam: 'tv_paper',
    badge: 'PAPER',
    badgeColor: 'var(--color-accent, #7c4dff)',
  },
  {
    id: 'ibkr_virtual',
    label: 'IBKR Virtual',
    shortLabel: 'IBKR',
    accountParam: null, // default (no ?account param)
    badge: 'ARCHIVED',
    badgeColor: 'rgba(255, 255, 255, 0.25)',
    archived: true,
  },
]

const LS_KEY = 'pearl.account.selected'

function getAccountFromUrl(): string | null {
  if (typeof window === 'undefined') return null
  const params = new URLSearchParams(window.location.search)
  return params.get('account')
}

function findAccountByParam(param: string | null, list: AccountDef[]): AccountDef {
  return list.find((a) => a.accountParam === param) || list[0]
}

export default function AccountSwitcher() {
  const [open, setOpen] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const storeAccounts = useAgentStore((s) => s.accounts)

  // Merge store config over fallback defaults (display_name, badge, etc.)
  // For archived accounts, keep frontend badge/badgeColor
  const accounts = useMemo(() => {
    if (!storeAccounts) return ACCOUNT_DEFAULTS
    return ACCOUNT_DEFAULTS.map((def) => {
      const configKey = def.accountParam || def.id
      const cfg = storeAccounts[configKey]
      if (!cfg) return def
      if (def.archived) {
        return { ...def, label: cfg.display_name ?? def.label }
      }
      return {
        ...def,
        label: cfg.display_name,
        badge: cfg.badge,
        badgeColor: cfg.badge_color,
      }
    })
  }, [storeAccounts])

  // Derive current account from URL
  const currentAccount = useMemo(() => {
    return findAccountByParam(getAccountFromUrl(), accounts)
  }, [accounts])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [open])

  const handleSelect = useCallback((account: AccountDef) => {
    setOpen(false)

    // Persist selection
    try {
      localStorage.setItem(LS_KEY, account.id)
    } catch {
      // ignore
    }

    // Build new URL with the correct account param
    const url = new URL(window.location.href)
    if (account.accountParam) {
      url.searchParams.set('account', account.accountParam)
    } else {
      url.searchParams.delete('account')
    }
    // Clean up legacy api_port param if present
    url.searchParams.delete('api_port')

    // Navigate (full reload to reset all stores/WS connections cleanly)
    window.location.href = url.toString()
  }, [])

  const handleToggle = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    setOpen((v) => !v)
  }, [])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      e.stopPropagation()
      setOpen((v) => !v)
    }
  }, [])

  return (
    <div
      ref={containerRef}
      className="account-switcher"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <button
        className={`account-switcher-trigger${currentAccount.archived ? ' archived' : ''}`}
        onClick={handleToggle}
        onKeyDown={handleKeyDown}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={`Current account: ${currentAccount.label}`}
        type="button"
      >
        <span className="account-switcher-badge" style={{
          background: currentAccount.badgeColor,
        }}>
          {currentAccount.badge}
        </span>
        <span className="account-switcher-name">{currentAccount.shortLabel}</span>
        <svg
          className={`account-switcher-chevron ${open ? 'open' : ''}`}
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M2 3.5L5 6.5L8 3.5"
            stroke="currentColor"
            strokeWidth="1.2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {open && (
        <div className="account-switcher-dropdown" role="listbox">
          {accounts.map((account) => (
            <button
              key={account.id}
              className={`account-switcher-option ${account.id === currentAccount.id ? 'active' : ''}${account.archived ? ' archived' : ''}`}
              onClick={() => handleSelect(account)}
              role="option"
              aria-selected={account.id === currentAccount.id}
              type="button"
            >
              <span className="account-option-badge" style={{
                background: account.badgeColor,
              }}>
                {account.badge}
              </span>
              <span className="account-option-label">
                {account.label}{account.archived ? ' (archived)' : ''}
              </span>
              {account.id === currentAccount.id && (
                <span className="account-option-check" aria-hidden="true">&#10003;</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
