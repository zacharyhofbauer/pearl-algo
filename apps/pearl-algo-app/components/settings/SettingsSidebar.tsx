'use client'

import { useSettingsStore } from '@/stores/settingsStore'

const CATEGORIES = [
  { id: 'Trading', label: 'Trading' },
  { id: 'Execution', label: 'Execution' },
  { id: 'Session', label: 'Session' },
  { id: 'Risk', label: 'Risk' },
  { id: 'Guardrails', label: 'Guardrails' },
  { id: 'Trailing Stop', label: 'Trailing Stop' },
  { id: 'Auto Flat', label: 'Auto Flat' },
  { id: 'Advanced Exits', label: 'Advanced Exits' },
  { id: 'Service', label: 'Service' },
  { id: 'Contract Scaling', label: 'Contract Scaling' },  // ADDED 2026-03-25: confidence scaling
]

export default function SettingsSidebar() {
  const activeCategory = useSettingsStore((s) => s.activeCategory)
  const setActiveCategory = useSettingsStore((s) => s.setActiveCategory)
  const pendingChanges = useSettingsStore((s) => s.pendingChanges)
  const schema = useSettingsStore((s) => s.schema)

  const categoriesWithChanges = new Set<string>()
  for (const path of Object.keys(pendingChanges)) {
    const fieldSchema = schema[path]
    if (fieldSchema) {
      categoriesWithChanges.add(fieldSchema.category)
    }
  }

  return (
    <aside className="settings-sidebar">
      <div className="settings-sidebar-header">
        <span className="settings-sidebar-title">Configuration</span>
      </div>
      <nav className="settings-sidebar-nav">
        {CATEGORIES.map((cat) => (
          <button
            key={cat.id}
            className={`settings-sidebar-tab ${activeCategory === cat.id ? 'settings-sidebar-tab-active' : ''}`}
            onClick={() => setActiveCategory(cat.id)}
          >
            <span className="settings-sidebar-tab-label">{cat.label}</span>
            {categoriesWithChanges.has(cat.id) && (
              <span className="settings-sidebar-tab-dot" />
            )}
          </button>
        ))}
      </nav>
    </aside>
  )
}
