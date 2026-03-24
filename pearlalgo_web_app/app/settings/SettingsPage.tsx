'use client'

import { useEffect, useState } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import SettingsSidebar from '@/components/settings/SettingsSidebar'
import SettingsCategory from '@/components/settings/SettingsCategory'
import SettingsConfirmDialog from '@/components/settings/SettingsConfirmDialog'

export default function SettingsPage() {
  const { fetchConfig, isDirty, isLoading, isSaving, error, pendingChanges, resetAll } = useSettingsStore()
  const [showConfirm, setShowConfirm] = useState(false)

  useEffect(() => {
    fetchConfig()
  }, [fetchConfig])

  if (isLoading) {
    return (
      <div className="settings-loading">
        <div className="settings-loading-spinner" />
        <span>Loading configuration...</span>
      </div>
    )
  }

  if (error && !useSettingsStore.getState().merged) {
    return (
      <div className="settings-error">
        <span className="settings-error-icon">!</span>
        <span>{error}</span>
        <button className="settings-retry-btn" onClick={fetchConfig}>Retry</button>
      </div>
    )
  }

  return (
    <div className="settings-page">
      {isDirty && (
        <div className="settings-banner">
          <span className="settings-banner-text">
            You have {Object.keys(pendingChanges).length} unsaved change{Object.keys(pendingChanges).length !== 1 ? 's' : ''}
          </span>
          <div className="settings-banner-actions">
            <button className="settings-banner-btn settings-banner-btn-discard" onClick={resetAll}>
              Discard
            </button>
            <button
              className="settings-banner-btn settings-banner-btn-save"
              onClick={() => setShowConfirm(true)}
              disabled={isSaving}
            >
              {isSaving ? 'Saving...' : 'Review & Save'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="settings-error-inline">
          <span>{error}</span>
        </div>
      )}

      <div className="settings-layout">
        <SettingsSidebar />
        <SettingsCategory />
      </div>

      {showConfirm && (
        <SettingsConfirmDialog onClose={() => setShowConfirm(false)} />
      )}
    </div>
  )
}
