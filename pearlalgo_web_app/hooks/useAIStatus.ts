'use client'

import { useMemo } from 'react'
import type { AIStatus, PearlInsights } from '@/stores'
import { derivePearlMode } from '@/types/pearl'

export interface AIModeBadge {
  mode: 'live' | 'shadow' | 'off'
  label: string
}

/**
 * Hook to derive AI mode from agent status.
 * Uses derivePearlMode() as the single source of truth for mode detection.
 */
export function useAIStatus(
  aiStatus: AIStatus | null | undefined,
  pearlInsights: PearlInsights | null | undefined = undefined
) {
  const aiMode = useMemo<'live' | 'shadow' | 'off' | null>(() => {
    if (!aiStatus) return null
    return derivePearlMode(aiStatus, pearlInsights || null)
  }, [aiStatus, pearlInsights])

  const badge = useMemo<AIModeBadge | null>(() => {
    if (!aiMode) return null

    const labels: Record<string, string> = {
      live: 'AI LIVE',
      shadow: 'AI SHADOW',
      off: 'AI OFF',
    }

    return {
      mode: aiMode,
      label: labels[aiMode] || 'AI OFF',
    }
  }, [aiMode])

  return {
    aiMode,
    badge,
    isLive: aiMode === 'live',
    isShadow: aiMode === 'shadow',
    isOff: aiMode === 'off' || aiMode === null,
  }
}

export default useAIStatus
