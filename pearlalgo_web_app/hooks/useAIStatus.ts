'use client'

import { useMemo } from 'react'
import type { AIStatus } from '@/stores'

export interface AIModeBadge {
  mode: 'live' | 'shadow' | 'off'
  label: string
}

/**
 * Hook to derive AI mode from agent status.
 * Consolidates the duplicate getAgentModeBadge/getAIMode logic.
 */
export function useAIStatus(aiStatus: AIStatus | null | undefined) {
  const aiMode = useMemo<'live' | 'shadow' | 'off' | null>(() => {
    if (!aiStatus) return null

    // Check if any AI component is in live mode
    const hasLive = aiStatus.bandit_mode === 'live' ||
      aiStatus.contextual_mode === 'live' ||
      (aiStatus.ml_filter?.enabled && aiStatus.ml_filter?.mode === 'live')

    // Check if any AI component is in shadow mode
    const hasShadow = aiStatus.bandit_mode === 'shadow' ||
      aiStatus.contextual_mode === 'shadow' ||
      (aiStatus.ml_filter?.enabled && aiStatus.ml_filter?.mode === 'shadow')

    if (hasLive) return 'live'
    if (hasShadow) return 'shadow'
    return 'off'
  }, [aiStatus])

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
