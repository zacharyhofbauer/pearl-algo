'use client'

import { useState, useEffect } from 'react'

export type ViewportType = 'mobile' | 'tablet' | 'desktop' | 'ultrawide'

interface ViewportConfig {
  type: ViewportType
  isUltrawide: boolean
  isTouch: boolean
  width: number
  height: number
  aspectRatio: number
}

/**
 * Detects viewport type with special handling for ultrawide displays
 * Xeneon Edge: 2560x720, 32:9 aspect ratio (3.56:1)
 */
export function useViewportType(): ViewportConfig {
  const [config, setConfig] = useState<ViewportConfig>({
    type: 'desktop',
    isUltrawide: false,
    isTouch: false,
    width: 1920,
    height: 1080,
    aspectRatio: 1.78,
  })

  useEffect(() => {
    // Cache URL params and touch detection (they don't change during resize)
    const urlParams = new URLSearchParams(window.location.search)
    const forceUltrawide = urlParams.get('ultrawide') === 'true'
    const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0

    const detectViewport = () => {
      const width = window.innerWidth
      const height = window.innerHeight
      const aspectRatio = width / height

      // Ultrawide detection: min 2400px width, max 800px height, aspect ratio 3:1+
      // OR forced via URL parameter for testing
      const isUltrawide = forceUltrawide || (width >= 2400 && height <= 800 && aspectRatio >= 3)

      let type: ViewportType
      if (isUltrawide) {
        type = 'ultrawide'
      } else if (width < 480) {
        type = 'mobile'
      } else if (width < 1024) {
        type = 'tablet'
      } else {
        type = 'desktop'
      }

      setConfig({
        type,
        isUltrawide,
        isTouch,
        width,
        height,
        aspectRatio,
      })
    }

    // Initial detection
    detectViewport()

    // Debounced resize handler (150ms delay)
    let resizeTimeout: NodeJS.Timeout | null = null
    const handleResize = () => {
      if (resizeTimeout) {
        clearTimeout(resizeTimeout)
      }
      resizeTimeout = setTimeout(() => {
        detectViewport()
      }, 150)
    }

    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      if (resizeTimeout) {
        clearTimeout(resizeTimeout)
      }
    }
  }, [])

  return config
}

/**
 * Returns true if the current viewport matches the Xeneon Edge display
 * (or similar ultrawide displays)
 */
export function useIsXeneonEdge(): boolean {
  const { isUltrawide } = useViewportType()
  return isUltrawide
}
