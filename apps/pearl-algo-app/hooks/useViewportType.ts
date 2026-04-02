'use client'

import { useState, useEffect } from 'react'

export type ViewportType = 'mobile' | 'tablet' | 'desktop'

interface ViewportConfig {
  type: ViewportType
  isTouch: boolean
  width: number
  height: number
  aspectRatio: number
}

/**
 * Detects viewport type for responsive layout.
 */
export function useViewportType(): ViewportConfig {
  const [config, setConfig] = useState<ViewportConfig>({
    type: 'desktop',
    isTouch: false,
    width: 1920,
    height: 1080,
    aspectRatio: 1.78,
  })

  useEffect(() => {
    const isTouch = 'ontouchstart' in window || navigator.maxTouchPoints > 0

    const detectViewport = () => {
      const width = window.innerWidth
      const height = window.innerHeight
      const aspectRatio = width / height

      let type: ViewportType
      if (width < 480) {
        type = 'mobile'
      } else if (width < 1024) {
        type = 'tablet'
      } else {
        type = 'desktop'
      }

      setConfig({
        type,
        isTouch,
        width,
        height,
        aspectRatio,
      })
    }

    detectViewport()

    let resizeTimeout: ReturnType<typeof setTimeout> | null = null
    const handleResize = () => {
      if (resizeTimeout) clearTimeout(resizeTimeout)
      resizeTimeout = setTimeout(detectViewport, 150)
    }

    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      if (resizeTimeout) clearTimeout(resizeTimeout)
    }
  }, [])

  return config
}
