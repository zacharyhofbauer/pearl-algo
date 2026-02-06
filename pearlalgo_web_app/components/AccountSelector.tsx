'use client'

/**
 * Full-screen account selection prompt.
 *
 * Shown on initial load when no ?account= param is present and no
 * stored preference exists. Lets the user pick which account to view.
 * Remembers the choice in localStorage so it doesn't ask again until
 * the user explicitly clears it or switches via the header dropdown.
 */

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
  return (
    <div className="account-selector-overlay">
      <div className="account-selector-card">
        <div className="account-selector-header">
          <Image src="/pearl-emoji.png" alt="" width={32} height={32} priority />
          <h2>Select Account</h2>
        </div>
        <p className="account-selector-subtitle">
          Choose which account to view. You can switch anytime using the dropdown in the header bar.
        </p>
        <div className="account-selector-options">
          {ACCOUNTS.map((acct) => (
            <button
              key={acct.id}
              className="account-selector-option"
              onClick={() => {
                // Persist choice
                try {
                  localStorage.setItem(LS_KEY, acct.id)
                } catch { /* ignore */ }
                onSelect(acct.param)
              }}
              type="button"
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
 * Returns true when:
 * - No ?account= param in URL
 * - No stored preference in localStorage
 */
export function shouldShowAccountSelector(): boolean {
  if (typeof window === 'undefined') return false

  // If URL already has an account param, don't show
  const params = new URLSearchParams(window.location.search)
  if (params.has('account') || params.has('api_port')) return false

  // If there's a stored preference, auto-apply it instead of prompting
  try {
    const stored = localStorage.getItem(LS_KEY)
    if (stored) return false
  } catch { /* ignore */ }

  return true
}

/**
 * Get the stored account preference and return its URL param.
 * Returns undefined if no stored preference (show selector instead).
 * Returns null if inception (no param needed).
 * Returns "mffu" if MFFU account.
 */
export function getStoredAccountParam(): string | null | undefined {
  if (typeof window === 'undefined') return undefined

  const params = new URLSearchParams(window.location.search)
  if (params.has('account') || params.has('api_port')) return undefined

  try {
    const stored = localStorage.getItem(LS_KEY)
    if (stored === 'inception') return null
    if (stored === 'mffu_eval') return 'mffu'
  } catch { /* ignore */ }

  return undefined
}
