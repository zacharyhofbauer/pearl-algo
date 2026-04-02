'use client'

import { useSettingsStore } from '@/stores/settingsStore'
import SettingField from './SettingField'

const SECTION_LABELS: Record<string, string> = {
  strategy: 'Strategy Runtime',
  'strategies.composite_intraday': 'Composite Intraday',
  execution: 'Execution',
  session: 'Session',
  risk: 'Risk Management',
  guardrails: 'Guardrails',
  trailing_stop: 'Trailing Stop',
  auto_flat: 'Auto Flat',
  advanced_exits: 'Advanced Exits',
  'advanced_exits.quick_exit': 'Quick Exit',
  'advanced_exits.time_based_exit': 'Time-Based Exit',
  'advanced_exits.stop_optimization': 'Stop Optimization',
  service: 'Service',
  scan_interval: 'Scan Interval',
}

function formatSectionTitle(raw: string): string {
  return SECTION_LABELS[raw] || raw.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

export default function SettingsCategory() {
  const activeCategory = useSettingsStore((s) => s.activeCategory)
  const schema = useSettingsStore((s) => s.schema)

  const fields = Object.entries(schema)
    .filter(([, fieldSchema]) => fieldSchema.category === activeCategory)
    .sort(([a], [b]) => a.localeCompare(b))

  if (fields.length === 0) {
    return (
      <main className="settings-content">
        <div className="settings-category">
          <div className="settings-empty">
            Loading configuration...
          </div>
        </div>
      </main>
    )
  }

  // Group fields by yaml_section
  const sections = new Map<string, [string, typeof schema[string]][]>()
  for (const entry of fields) {
    const section = entry[1].yaml_section
    if (!sections.has(section)) {
      sections.set(section, [])
    }
    sections.get(section)!.push(entry)
  }

  return (
    <main className="settings-content">
      <div className="settings-category">
        {Array.from(sections.entries()).map(([sectionName, sectionFields]) => (
          <div key={sectionName} className="settings-section">
            <h3 className="settings-section-title">{formatSectionTitle(sectionName)}</h3>
            <div className="settings-fields">
              {sectionFields.map(([path, fieldSchema]) => (
                <SettingField key={path} path={path} schema={fieldSchema} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </main>
  )
}
