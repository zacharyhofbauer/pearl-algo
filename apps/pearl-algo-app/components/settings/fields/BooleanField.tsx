'use client'

import { useSettingsStore, type FieldSchema } from '@/stores/settingsStore'

interface BooleanFieldProps {
  path: string
  schema: FieldSchema
}

export default function BooleanField({ path, schema }: BooleanFieldProps) {
  const getFieldValue = useSettingsStore((s) => s.getFieldValue)
  const setField = useSettingsStore((s) => s.setField)

  const value = getFieldValue(path)
  const isActive = Boolean(value)

  return (
    <button
      type="button"
      className={`settings-toggle ${isActive ? 'settings-toggle-active' : ''}`}
      onClick={() => setField(path, !isActive)}
      role="switch"
      aria-checked={isActive}
      aria-label={schema.description}
    >
      <span className="settings-toggle-track">
        <span className="settings-toggle-thumb" />
      </span>
      <span className="settings-toggle-label">
        {isActive ? 'ON' : 'OFF'}
      </span>
    </button>
  )
}
