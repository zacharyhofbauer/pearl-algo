'use client'

import { useSettingsStore, type FieldSchema } from '@/stores/settingsStore'
import NumberField from './fields/NumberField'
import BooleanField from './fields/BooleanField'
import SelectField from './fields/SelectField'
import TextField from './fields/TextField'

interface SettingFieldProps {
  path: string
  schema: FieldSchema
}

export default function SettingField({ path, schema }: SettingFieldProps) {
  const overrideKeys = useSettingsStore((s) => s.overrideKeys)
  const pendingChanges = useSettingsStore((s) => s.pendingChanges)
  const resetField = useSettingsStore((s) => s.resetField)

  const isOverridden = overrideKeys.includes(path)
  const isModified = path in pendingChanges
  const isDangerous = schema.dangerous === true

  const renderField = () => {
    switch (schema.type) {
      case 'number':
        return <NumberField path={path} schema={schema} />
      case 'boolean':
        return <BooleanField path={path} schema={schema} />
      case 'select':
        return <SelectField path={path} schema={schema} />
      case 'text':
        return <TextField path={path} schema={schema} />
      default:
        return <TextField path={path} schema={schema} />
    }
  }

  return (
    <div className={`settings-field ${isDangerous ? 'settings-field-dangerous' : ''}`}>
      <div className="settings-field-header">
        <label className="settings-field-label">
          {schema.description}
        </label>
        <div className="settings-field-badges">
          {isOverridden && (
            <span className="settings-badge settings-badge-override">OVERRIDE</span>
          )}
          {isModified && (
            <span className="settings-badge settings-badge-modified">MODIFIED</span>
          )}
          {isDangerous && (
            <span className="settings-badge settings-badge-dangerous">CRITICAL</span>
          )}
        </div>
      </div>
      <div className="settings-field-control">
        {renderField()}
        {(isOverridden || isModified) && (
          <button
            className="settings-field-reset"
            onClick={() => resetField(path)}
            title="Reset to default"
          >
            Reset
          </button>
        )}
      </div>
    </div>
  )
}
