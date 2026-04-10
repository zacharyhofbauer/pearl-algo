'use client'

import React, { useEffect } from 'react'
import { useUIStore, selectNotifications } from '@/stores'

const DEFAULT_DURATION_MS = 4500
const PER_WORD_MS = 60
const MIN_DURATION_MS = 2500

function computeDuration(words: number, override?: number): number {
  if (typeof override === 'number') return override
  if (words <= 0) return DEFAULT_DURATION_MS
  return Math.max(MIN_DURATION_MS, DEFAULT_DURATION_MS + words * PER_WORD_MS)
}

function ToastContainer() {
  const notifications = useUIStore(selectNotifications)
  const removeNotification = useUIStore((s) => s.removeNotification)

  // Auto-dismiss timers — one per active notification.
  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = []
    for (const n of notifications) {
      const wordCount = (n.title || '').split(/\s+/).filter(Boolean).length
      const duration = computeDuration(wordCount, n.duration)
      if (duration <= 0) continue
      timers.push(setTimeout(() => removeNotification(n.id), duration))
    }
    return () => {
      for (const t of timers) clearTimeout(t)
    }
  }, [notifications, removeNotification])

  if (notifications.length === 0) return null

  return (
    <div className="toast-container" role="region" aria-live="polite" aria-label="Notifications">
      {notifications.map((n) => (
        <div
          key={n.id}
          className={`toast toast-${n.type}`}
          role={n.type === 'error' || n.type === 'warning' ? 'alert' : 'status'}
        >
          <div className="toast-body">
            <div className="toast-title">{n.title}</div>
            {n.message && <div className="toast-message">{n.message}</div>}
          </div>
          <button
            type="button"
            className="toast-dismiss"
            aria-label="Dismiss notification"
            onClick={() => removeNotification(n.id)}
          >
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round">
              <line x1="2" y1="2" x2="10" y2="10" />
              <line x1="10" y1="2" x2="2" y2="10" />
            </svg>
          </button>
        </div>
      ))}
    </div>
  )
}

export default React.memo(ToastContainer)
