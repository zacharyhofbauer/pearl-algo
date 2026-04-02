'use client'

import { useSettingsStore, type FieldSchema } from '@/stores/settingsStore'

interface SelectFieldProps {
  path: string
  schema: FieldSchema
}

export default function SelectField({ path, schema }: SelectFieldProps) {
  const getFieldValue = useSettingsStore((s) => s.getFieldValue)
  const setField = useSettingsStore((s) => s.setField)

  const value = getFieldValue(path)
  const options = schema.options || []

  return (
    <select
      className="settings-select"
      value={value ?? ''}
      onChange={(e) => setField(path, e.target.value)}
    >
      {!options.includes(value) && value != null && (
        <option value={value}>{String(value)}</option>
      )}
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  )
}
