'use client'

import { DataPanel } from './DataPanelsContainer'
import PearlDropdownPanel from './PearlDropdownPanel'
import { usePearlStore, selectIsHeaderExpanded } from '@/stores'
import type { PearlInsights, PearlSuggestion, AIStatus, ShadowCounters, MLFilterPerformance } from '@/stores'

interface PearlInsightsPanelProps {
  insights: PearlInsights | null
  suggestion: PearlSuggestion | null
  aiStatus?: AIStatus | null
  shadowCounters?: ShadowCounters | null
  mlFilterPerformance?: MLFilterPerformance | null
  onAccept?: () => void
  onDismiss?: () => void
}

export default function PearlInsightsPanel({
  insights,
  suggestion,
  aiStatus,
  shadowCounters,
  mlFilterPerformance,
  onAccept,
  onDismiss,
}: PearlInsightsPanelProps) {
  // Check if header dropdown is expanded - hide in-page panel to avoid duplication
  const isHeaderExpanded = usePearlStore(selectIsHeaderExpanded)

  // Check if any component is in shadow mode for badge
  const mlMode = aiStatus?.ml_filter.enabled
    ? (aiStatus.ml_filter.mode === 'live' ? 'live' : 'shadow')
    : 'off'

  const hasShadowMode = aiStatus && (
    aiStatus.bandit_mode === 'shadow' ||
    aiStatus.contextual_mode === 'shadow' ||
    mlMode === 'shadow'
  )

  const metrics = insights?.shadow_metrics

  // Hide when header dropdown is expanded to avoid showing duplicate content
  if (isHeaderExpanded) {
    return null
  }

  return (
    <DataPanel
      title="Pearl AI"
      iconSrc="/pearl-emoji.png"
      className="pearl-insights-panel"
      badge={hasShadowMode || metrics?.mode === 'shadow' ? 'SHADOW' : undefined}
      badgeColor="var(--color-warning)"
    >
      <div className="pearl-insights">
        <PearlDropdownPanel
          insights={insights}
          suggestion={suggestion}
          aiStatus={aiStatus}
          shadowCounters={shadowCounters}
          mlFilterPerformance={mlFilterPerformance}
          onAccept={onAccept}
          onDismiss={onDismiss}
        />
      </div>
    </DataPanel>
  )
}
