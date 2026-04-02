export type SettingsObject = Record<string, unknown>

export function getNestedValue(obj: SettingsObject | null, path: string): unknown {
  if (!obj) return undefined

  const keys = path.split('.')
  let current: unknown = obj

  for (const key of keys) {
    if (current == null || typeof current !== 'object') {
      return undefined
    }
    current = (current as SettingsObject)[key]
  }

  return current
}

export function formatSettingsValue(value: unknown): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}
