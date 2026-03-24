'use client'

import { useState } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'

interface SettingsConfirmDialogProps {
  onClose: () => void
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

export default function SettingsConfirmDialog({ onClose }: SettingsConfirmDialogProps) {
  const pendingChanges = useSettingsStore((s) => s.pendingChanges)
  const merged = useSettingsStore((s) => s.merged)
  const schema = useSettingsStore((s) => s.schema)
  const saveChanges = useSettingsStore((s) => s.saveChanges)
  const isSaving = useSettingsStore((s) => s.isSaving)

  const [confirmText, setConfirmText] = useState('')

  const changes = Object.entries(pendingChanges)
  const hasDangerous = changes.some(([path]) => schema[path]?.dangerous === true)
  const canConfirm = hasDangerous ? confirmText === 'CONFIRM' : true

  const handleSave = async () => {
    if (!canConfirm) return
    await saveChanges(true)
    onClose()
  }

  return (
    <div className="settings-confirm-overlay" onClick={onClose}>
      <div className="settings-confirm-dialog" onClick={(e) => e.stopPropagation()}>
        <h2 className="settings-confirm-title">Review Changes</h2>
        <p className="settings-confirm-subtitle">
          The following {changes.length} change{changes.length !== 1 ? 's' : ''} will be applied and the service will restart.
        </p>

        <div className="settings-confirm-changes">
          {changes.map(([path, newValue]) => {
            const oldValue = getNestedValue(merged, path)
            const fieldSchema = schema[path]
            const isDangerous = fieldSchema?.dangerous === true

            return (
              <div
                key={path}
                className={`settings-confirm-change ${isDangerous ? 'settings-confirm-change-dangerous' : ''}`}
              >
                <div className="settings-confirm-change-path">
                  {fieldSchema?.description || path}
                  {isDangerous && (
                    <span className="settings-badge settings-badge-dangerous">{'\u26A0\uFE0F'} DANGEROUS</span>
                  )}
                </div>
                <div className="settings-confirm-change-values">
                  <span className="settings-confirm-old">{formatValue(oldValue)}</span>
                  <span className="settings-confirm-arrow">{'\u2192'}</span>
                  <span className="settings-confirm-new">{formatValue(newValue)}</span>
                </div>
              </div>
            )
          })}
        </div>

        {hasDangerous && (
          <div className="settings-confirm-warning">
            <p className="settings-confirm-warning-text">
              {'\u26A0\uFE0F'} This includes dangerous changes that could affect live trading.
              Type <strong>CONFIRM</strong> to proceed.
            </p>
            <input
              type="text"
              className="settings-text-input settings-confirm-input"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              placeholder="Type CONFIRM"
              autoFocus
            />
          </div>
        )}

        <div className="settings-confirm-actions">
          <button
            className="settings-confirm-btn settings-confirm-btn-cancel"
            onClick={onClose}
            disabled={isSaving}
          >
            Cancel
          </button>
          <button
            className="settings-confirm-btn settings-confirm-btn-save"
            onClick={handleSave}
            disabled={!canConfirm || isSaving}
          >
            {isSaving ? 'Saving & Restarting...' : 'Save & Restart'}
          </button>
        </div>
      </div>
    </div>
  )
}

function formatValue(value: any): string {
  if (value === null || value === undefined) return 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}
