'use client'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="en">
      <body style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 16,
        background: '#0a0a0f',
        color: '#f0eeeb',
        fontFamily: 'system-ui, sans-serif',
        textAlign: 'center',
        padding: 24,
      }}>
        <h1 style={{ fontSize: 24, fontWeight: 700 }}>Something went wrong</h1>
        <p style={{ color: '#8a92a0', fontSize: 14 }}>
          {error.message || 'An unexpected error occurred.'}
        </p>
        <button
          onClick={reset}
          style={{
            marginTop: 8,
            padding: '8px 24px',
            background: 'transparent',
            border: '1px solid rgba(0,212,255,0.3)',
            borderRadius: 6,
            color: '#00d4ff',
            fontSize: 14,
            fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          Try Again
        </button>
      </body>
    </html>
  )
}
