'use client'

import { DataPanel } from './DataPanelsContainer'

interface PearlSuggestion {
  message: string
  action: string
}

interface PearlSuggestionsPanelProps {
  suggestion: PearlSuggestion | null
  onAccept?: () => void
  onDismiss?: () => void
}

export default function PearlSuggestionsPanel({
  suggestion,
  onAccept,
  onDismiss,
}: PearlSuggestionsPanelProps) {
  if (!suggestion) {
    return null
  }

  return (
    <DataPanel title="Pearl AI" icon="🦪" className="pearl-suggestions-panel">
      <div className="pearl-suggestion">
        <div className="pearl-message">{suggestion.message}</div>
        {suggestion.action && (
          <div className="pearl-action-hint">
            <span className="action-label">Suggested:</span>
            <span className="action-value">{suggestion.action}</span>
          </div>
        )}
        <div className="pearl-actions">
          <button
            className="pearl-btn pearl-btn-accept"
            onClick={onAccept}
          >
            Accept
          </button>
          <button
            className="pearl-btn pearl-btn-dismiss"
            onClick={onDismiss}
          >
            Dismiss
          </button>
        </div>
      </div>
    </DataPanel>
  )
}
