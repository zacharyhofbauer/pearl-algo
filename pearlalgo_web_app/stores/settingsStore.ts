import { create } from 'zustand'
import { apiFetchJson } from '@/lib/api'

export interface FieldSchema {
  type: 'number' | 'boolean' | 'select' | 'text'
  min?: number
  max?: number
  step?: number
  options?: string[]
  dangerous?: boolean
  description: string
  category: string
  yaml_section: string
}

interface SettingsState {
  merged: Record<string, any> | null
  overrides: Record<string, any> | null
  overrideKeys: string[]
  schema: Record<string, FieldSchema>
  configHash: string | null
  activeCategory: string
  pendingChanges: Record<string, any>
  isDirty: boolean
  isLoading: boolean
  isSaving: boolean
  error: string | null
  lastSavedAt: number | null

  fetchConfig: () => Promise<void>
  setField: (path: string, value: any) => void
  resetField: (path: string) => void
  resetAll: () => void
  saveChanges: (restart: boolean) => Promise<void>
  setActiveCategory: (cat: string) => void
  getFieldValue: (path: string) => any
}

function getNestedValue(obj: Record<string, any> | null, path: string): any {
  if (!obj) return undefined
  const keys = path.split('.')
  let current: any = obj
  for (const key of keys) {
    if (current == null || typeof current !== 'object') return undefined
    current = current[key]
  }
  return current
}

export const useSettingsStore = create<SettingsState>((set, get) => ({
  merged: null,
  overrides: null,
  overrideKeys: [],
  schema: {},
  configHash: null,
  activeCategory: 'Trading',
  pendingChanges: {},
  isDirty: false,
  isLoading: false,
  isSaving: false,
  error: null,
  lastSavedAt: null,

  fetchConfig: async () => {
    set({ isLoading: true, error: null })
    try {
      const data = await apiFetchJson<{
        merged: Record<string, any>
        overrides: Record<string, any>
        override_keys: string[]
        schema: Record<string, FieldSchema>
        config_hash: string
      }>('/api/config')

      set({
        merged: data.merged,
        overrides: data.overrides,
        overrideKeys: data.override_keys,
        schema: data.schema,
        configHash: data.config_hash,
        isLoading: false,
        error: null,
      })
    } catch (err: any) {
      set({
        isLoading: false,
        error: err?.message || 'Failed to fetch config',
      })
    }
  },

  setField: (path: string, value: any) => {
    set((state) => {
      const next = { ...state.pendingChanges, [path]: value }
      return { pendingChanges: next, isDirty: Object.keys(next).length > 0 }
    })
  },

  resetField: (path: string) => {
    set((state) => {
      const next = { ...state.pendingChanges }
      delete next[path]
      return { pendingChanges: next, isDirty: Object.keys(next).length > 0 }
    })
  },

  resetAll: () => {
    set({ pendingChanges: {}, isDirty: false })
  },

  saveChanges: async (restart: boolean) => {
    const { pendingChanges, configHash } = get()
    if (Object.keys(pendingChanges).length === 0) return

    set({ isSaving: true, error: null })
    try {
      await apiFetchJson('/api/config', {
        method: 'POST',
        body: JSON.stringify({
          changes: pendingChanges,
          config_hash: configHash,
          restart,
        }),
      })

      set({
        isSaving: false,
        pendingChanges: {},
        isDirty: false,
        lastSavedAt: Date.now(),
      })

      // Re-fetch to get updated merged config and new hash
      await get().fetchConfig()
    } catch (err: any) {
      set({
        isSaving: false,
        error: err?.message || 'Failed to save config',
      })
    }
  },

  setActiveCategory: (cat: string) => {
    set({ activeCategory: cat })
  },

  getFieldValue: (path: string) => {
    const { pendingChanges, merged } = get()
    if (path in pendingChanges) return pendingChanges[path]
    return getNestedValue(merged, path)
  },
}))
