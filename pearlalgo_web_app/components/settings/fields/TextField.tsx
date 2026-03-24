'use client'

import { useSettingsStore, type FieldSchema } from '@/stores/settingsStore'

interface TextFieldProps {
  path: string
  schema: FieldSchema
}

export default function TextField({ path, schema }: TextFieldProps) {
  const getFieldValue = useSettingsStore((s) => s.getFieldValue)
  const setField = useSettingsStore((s) => s.setField)

  const value = getFieldValue(path)

  return (
    <input
      type="text"
      className="settings-text-input"
      value={value ?? ''}
      placeholder={schema.description}
      onChange={(e) => setField(path, e.target.value)}
    />
  )
}
