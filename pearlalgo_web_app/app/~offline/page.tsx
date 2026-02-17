'use client'

import Link from 'next/link'

/**
 * Offline fallback page shown when the user has no network connection
 * and the requested page is not in cache.
 */
export default function OfflinePage() {
  return (
    <main
      className="offline-page"
      role="main"
      aria-live="polite"
      aria-label="Offline"
    >
      <div className="offline-content">
        <h1>You are offline</h1>
        <p>Connect to the internet to view live data.</p>
        <Link href="/" className="offline-link">
          Try again
        </Link>
      </div>
    </main>
  )
}
