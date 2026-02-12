'use client'

import { useEffect, useRef, useState } from 'react'

const PULL_THRESHOLD = 70

interface UsePullToRefreshOptions {
  onRefresh: () => Promise<void> | void
}

interface UsePullToRefreshReturn {
  pullDistance: number
  pullRefreshing: boolean
  pullDistanceRef: React.MutableRefObject<number>
}

/**
 * Hook for pull-to-refresh gesture handling on mobile devices.
 * Detects touch gestures when user is at the top of the page and pulls down.
 */
export function usePullToRefresh({ onRefresh }: UsePullToRefreshOptions): UsePullToRefreshReturn {
  const pullStartY = useRef(0)
  const pullActive = useRef(false)
  const pullDistanceRef = useRef(0)
  const [pullDistance, setPullDistance] = useState(0)
  const [pullRefreshing, setPullRefreshing] = useState(false)

  // Keep ref in sync with state for use in touchend
  useEffect(() => {
    pullDistanceRef.current = pullDistance
  }, [pullDistance])

  useEffect(() => {
    let refreshingRef = false

    const onTouchStart = (e: TouchEvent) => {
      if (refreshingRef) return
      // Check both window scroll and document scroll (cross-browser)
      const scrollTop = window.scrollY || document.documentElement.scrollTop || 0
      if (scrollTop <= 5) {
        pullStartY.current = e.touches[0].clientY
        pullActive.current = false
      } else {
        pullStartY.current = 0
      }
    }

    const onTouchMove = (e: TouchEvent) => {
      if (pullStartY.current === 0 || refreshingRef) return
      const scrollTop = window.scrollY || document.documentElement.scrollTop || 0
      const diff = e.touches[0].clientY - pullStartY.current

      if (diff > 10 && scrollTop <= 5) {
        // Pulling down from top - activate
        pullActive.current = true
        e.preventDefault()
        const distance = Math.min(diff * 0.4, 100)
        setPullDistance(distance)
      } else if (diff < -5 && !pullActive.current) {
        // Scrolling up - cancel pull tracking
        pullStartY.current = 0
      }
    }

    const onTouchEnd = () => {
      if (!pullActive.current || refreshingRef) {
        if (!refreshingRef) setPullDistance(0)
        pullStartY.current = 0
        pullActive.current = false
        return
      }

      if (pullDistanceRef.current >= PULL_THRESHOLD * 0.4) {
        refreshingRef = true
        setPullRefreshing(true)
        setPullDistance(40)
        
        Promise.resolve(onRefresh()).finally(() => {
          refreshingRef = false
          setPullRefreshing(false)
          setPullDistance(0)
        })
      } else {
        setPullDistance(0)
      }
      pullStartY.current = 0
      pullActive.current = false
    }

    // Cancel pull if user scrolls via momentum after lifting finger
    const onScroll = () => {
      if (pullActive.current && !refreshingRef) {
        pullActive.current = false
        setPullDistance(0)
      }
    }

    document.addEventListener('touchstart', onTouchStart, { passive: true })
    document.addEventListener('touchmove', onTouchMove, { passive: false })
    document.addEventListener('touchend', onTouchEnd, { passive: true })
    document.addEventListener('touchcancel', onTouchEnd, { passive: true })
    window.addEventListener('scroll', onScroll, { passive: true })

    return () => {
      document.removeEventListener('touchstart', onTouchStart)
      document.removeEventListener('touchmove', onTouchMove)
      document.removeEventListener('touchend', onTouchEnd)
      document.removeEventListener('touchcancel', onTouchEnd)
      window.removeEventListener('scroll', onScroll)
    }
  }, [onRefresh])

  return {
    pullDistance,
    pullRefreshing,
    pullDistanceRef,
  }
}
