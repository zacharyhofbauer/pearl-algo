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
    const detectViewport = () => {
      const width = window.innerWidth
      const height = window.innerHeight
      const aspectRatio = width / height
      const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0

      // Check for URL parameter override: ?ultrawide=true
      const urlParams = new URLSearchParams(window.location.search)
      const forceUltrawide = urlParams.get('ultrawide') === 'true'

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

    detectViewport()
    window.addEventListener('resize', detectViewport)
    return () => window.removeEventListener('resize', detectViewport)
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
