'use client'

import { useEffect, useRef, useState } from 'react'

/** easeOutCubic for smooth deceleration at end */
function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

interface Options {
  duration?: number
  /** Only animate when true (e.g. when data has loaded) */
  enabled?: boolean
}

/**
 * Animates from 0 to target over duration using requestAnimationFrame.
 * Triggers on target change when enabled — use for post-load number reveals.
 */
const isTest = typeof process !== 'undefined' && process.env?.NODE_ENV === 'test'

export function useCountUp(target: number | null | undefined, options: Options = {}): number {
  const { duration = isTest ? 0 : 1500, enabled = true } = options
  const [value, setValue] = useState(0)
  const rafRef = useRef<number | null>(null)
  const startValRef = useRef<number>(0)

  useEffect(() => {
    if (target == null || !enabled || typeof target !== 'number') {
      setValue(target ?? 0)
      return
    }

    const startVal = startValRef.current
    const delta = target - startVal
    const startTime = performance.now()

    const tick = (now: number) => {
      const elapsed = now - startTime
      const progress = Math.min(elapsed / duration, 1)
      const eased = easeOutCubic(progress)
      const current = startVal + delta * eased
      setValue(current)

      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick)
      } else {
        startValRef.current = target
      }
    }

    rafRef.current = requestAnimationFrame(tick)
    return () => {
      if (rafRef.current != null) {
        cancelAnimationFrame(rafRef.current)
      }
    }
  }, [target, duration, enabled])

  if (target == null || !enabled) {
    return target ?? 0
  }

  return value
}
