'use client'

import { ReactNode } from 'react'
import { ErrorBoundary } from './ErrorBoundary'

interface DataPanelsContainerProps {
  children: ReactNode
}

export default function DataPanelsContainer({ children }: DataPanelsContainerProps) {
  return (
    <div className="data-panels">
      <div className="data-panels-grid">
        {children}
      </div>
    </div>
  )
}

interface DataPanelProps {
  title: string
  icon?: string
  children: ReactNode
  className?: string
  /** Padding variant for panel content */
  padding?: 'none' | 'compact' | 'default' | 'spacious'
  /** Visual variant for different panel types */
  variant?: 'default' | 'feature' | 'status' | 'config'
  /** Disable error boundary for this panel (default: false) */
  noErrorBoundary?: boolean
  /** Optional badge text to display next to title */
  badge?: string
  /** Badge background color (CSS value) */
  badgeColor?: string
}

export function DataPanel({
  title,
  icon,
  children,
  className = '',
  padding = 'default',
  variant = 'default',
  noErrorBoundary = false,
  badge,
  badgeColor
}: DataPanelProps) {
  const panelClasses = [
    'data-panel',
    `data-panel-padding-${padding}`,
    `data-panel-variant-${variant}`,
    className
  ].filter(Boolean).join(' ')

  const panelContent = (
    <div className={panelClasses}>
      <div className="data-panel-header">
        {icon && <span className="data-panel-icon">{icon}</span>}
        <span className="data-panel-title">{title}</span>
        {badge && (
          <span
            className="data-panel-badge"
            style={badgeColor ? { backgroundColor: badgeColor } : undefined}
          >
            {badge}
          </span>
        )}
      </div>
      <div className="data-panel-content">
        {children}
      </div>
    </div>
  )

  // Wrap with error boundary unless disabled
  if (noErrorBoundary) {
    return panelContent
  }

  return (
    <ErrorBoundary
      panelName={title}
      fallback={
        <div className={`data-panel error-panel ${className}`}>
          <div className="data-panel-header">
            {icon && <span className="data-panel-icon">{icon}</span>}
            <span className="data-panel-title">{title}</span>
          </div>
          <div className="data-panel-content">
            <div className="error-boundary-fallback compact">
              <span className="error-boundary-icon">⚠️</span>
              <span className="error-boundary-message">Failed to load panel</span>
            </div>
          </div>
        </div>
      }
    >
      {panelContent}
    </ErrorBoundary>
  )
}
