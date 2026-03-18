/**
 * Tests for useAIStatus hook
 */

import { renderHook } from '@testing-library/react'
import { useAIStatus } from '@/hooks/useAIStatus'
import type { AIStatus } from '@/stores'

describe('useAIStatus', () => {
  it('should return live mode when any component is live', () => {
    const aiStatus: AIStatus = {
      bandit_mode: 'live',
      contextual_mode: 'off',
      ml_filter: {
        enabled: false,
        mode: 'off',
        lift: {},
      },
      direction_gating: {
        enabled: false,
        blocks: 0,
        shadow_regime: 0,
        shadow_trigger: 0,
      },
    }

    const { result } = renderHook(() => useAIStatus(aiStatus))

    expect(result.current.aiMode).toBe('live')
    expect(result.current.isLive).toBe(true)
    expect(result.current.isShadow).toBe(false)
    expect(result.current.isOff).toBe(false)
    expect(result.current.badge).toEqual({ mode: 'live', label: 'AI LIVE' })
  })

  it('should return shadow mode when any component is shadow', () => {
    const aiStatus: AIStatus = {
      bandit_mode: 'off',
      contextual_mode: 'shadow',
      ml_filter: {
        enabled: false,
        mode: 'off',
        lift: {},
      },
      direction_gating: {
        enabled: false,
        blocks: 0,
        shadow_regime: 0,
        shadow_trigger: 0,
      },
    }

    const { result } = renderHook(() => useAIStatus(aiStatus))

    expect(result.current.aiMode).toBe('shadow')
    expect(result.current.isLive).toBe(false)
    expect(result.current.isShadow).toBe(true)
    expect(result.current.isOff).toBe(false)
    expect(result.current.badge).toEqual({ mode: 'shadow', label: 'AI SHADOW' })
  })

  it('should return off mode when all components are off', () => {
    const aiStatus: AIStatus = {
      bandit_mode: 'off',
      contextual_mode: 'off',
      ml_filter: {
        enabled: false,
        mode: 'off',
        lift: {},
      },
      direction_gating: {
        enabled: false,
        blocks: 0,
        shadow_regime: 0,
        shadow_trigger: 0,
      },
    }

    const { result } = renderHook(() => useAIStatus(aiStatus))

    expect(result.current.aiMode).toBe('off')
    expect(result.current.isLive).toBe(false)
    expect(result.current.isShadow).toBe(false)
    expect(result.current.isOff).toBe(true)
    expect(result.current.badge).toEqual({ mode: 'off', label: 'AI OFF' })
  })

  it('should prioritize live over shadow', () => {
    const aiStatus: AIStatus = {
      bandit_mode: 'live',
      contextual_mode: 'shadow',
      ml_filter: {
        enabled: true,
        mode: 'shadow',
        lift: {},
      },
      direction_gating: {
        enabled: false,
        blocks: 0,
        shadow_regime: 0,
        shadow_trigger: 0,
      },
    }

    const { result } = renderHook(() => useAIStatus(aiStatus))

    expect(result.current.aiMode).toBe('live')
    expect(result.current.isLive).toBe(true)
  })

  it('should handle null/undefined aiStatus', () => {
    const { result: resultNull } = renderHook(() => useAIStatus(null))
    expect(resultNull.current.aiMode).toBeNull()
    expect(resultNull.current.badge).toBeNull()
    expect(resultNull.current.isOff).toBe(true)

    const { result: resultUndefined } = renderHook(() => useAIStatus(undefined))
    expect(resultUndefined.current.aiMode).toBeNull()
    expect(resultUndefined.current.badge).toBeNull()
    expect(resultUndefined.current.isOff).toBe(true)
  })

  it('should detect live mode from ML filter', () => {
    const aiStatus: AIStatus = {
      bandit_mode: 'off',
      contextual_mode: 'off',
      ml_filter: {
        enabled: true,
        mode: 'live',
        lift: {},
      },
      direction_gating: {
        enabled: false,
        blocks: 0,
        shadow_regime: 0,
        shadow_trigger: 0,
      },
    }

    const { result } = renderHook(() => useAIStatus(aiStatus))

    expect(result.current.aiMode).toBe('live')
    expect(result.current.isLive).toBe(true)
  })
})
