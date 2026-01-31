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
  /** Disable error boundary for this panel (default: false) */
  noErrorBoundary?: boolean
}

export function DataPanel({ title, icon, children, className = '', noErrorBoundary = false }: DataPanelProps) {
  const panelContent = (
    <div className={`data-panel ${className}`}>
      <div className="data-panel-header">
        {icon && <span className="data-panel-icon">{icon}</span>}
        <span className="data-panel-title">{title}</span>
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
