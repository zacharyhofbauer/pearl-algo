'use client'

import Link from 'next/link'

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <main className="not-found-page">
      <h1 style={{ fontSize: 24, fontWeight: 700, color: 'var(--text-primary)' }}>
        Dashboard Error
      </h1>
      <p style={{ color: 'var(--text-secondary)', fontSize: 14 }}>
        {error.message || 'Something went wrong loading the dashboard.'}
      </p>
      <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
        <button
          onClick={reset}
          className="not-found-link"
        >
          Try Again
        </button>
        <Link href="/" className="not-found-link">
          Back to Home
        </Link>
      </div>
    </main>
  )
}
