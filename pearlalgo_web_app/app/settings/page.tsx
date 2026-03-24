'use client'

import { Suspense } from 'react'
import SettingsPage from './SettingsPage'

export default function Settings() {
  return (
    <Suspense fallback={<div className="settings-loading">Loading settings...</div>}>
      <SettingsPage />
    </Suspense>
  )
}
