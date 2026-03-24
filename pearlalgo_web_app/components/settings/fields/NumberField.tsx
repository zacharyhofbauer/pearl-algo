'use client'

import { useSettingsStore, type FieldSchema } from '@/stores/settingsStore'

interface NumberFieldProps {
  path: string
  schema: FieldSchema
}

export default function NumberField({ path, schema }: NumberFieldProps) {
  const getFieldValue = useSettingsStore((s) => s.getFieldValue)
  const setField = useSettingsStore((s) => s.setField)

  const value = getFieldValue(path)
  const displayValue = value ?? ''

  return (
    <input
      type="number"
      className="settings-number-input"
      value={displayValue}
      min={schema.min}
      max={schema.max}
      step={schema.step || 0.1}
      onChange={(e) => {
        const raw = e.target.value
        if (raw === '') return
        const parsed = parseFloat(raw)
        if (!isNaN(parsed)) {
          setField(path, parsed)
        }
      }}
    />
  )
}
