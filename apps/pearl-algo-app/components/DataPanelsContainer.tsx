'use client'

import { ReactNode } from 'react'
import Image from 'next/image'
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
  /** Optional image path for a small header icon */
  iconSrc?: string
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
  /** Optional right-side header content (e.g., summary chips) */
  headerRight?: ReactNode
  /** Semantic heading level for accessibility (default: 2) */
  headingLevel?: 2 | 3 | 4
}

export function DataPanel({
  title,
  iconSrc,
  children,
  className = '',
  padding = 'default',
  variant = 'default',
  noErrorBoundary = false,
  badge,
  badgeColor,
  headerRight,
  headingLevel = 2
}: DataPanelProps) {
  const panelClasses = [
    'data-panel',
    `data-panel-padding-${padding}`,
    `data-panel-variant-${variant}`,
    className
  ].filter(Boolean).join(' ')

  // Render icon (image only; no emoji in panel titles)
  const renderIcon = () => {
    if (iconSrc) {
      return <Image src={iconSrc} alt="" width={18} height={18} className="data-panel-icon-img" />
    }
    return null
  }

  // Semantic heading element for accessibility
  const HeadingTag = `h${headingLevel}` as keyof JSX.IntrinsicElements

  const panelContent = (
    <section className={panelClasses} aria-labelledby={`panel-${title.toLowerCase().replace(/\s+/g, '-')}`}>
      <div className="data-panel-header">
        {renderIcon()}
        <HeadingTag id={`panel-${title.toLowerCase().replace(/\s+/g, '-')}`} className="data-panel-title">{title}</HeadingTag>
        {(headerRight || badge) && (
          <div className="data-panel-header-right">
            {headerRight}
            {badge && (
              <span
                className="data-panel-badge"
                style={badgeColor ? { backgroundColor: badgeColor } : undefined}
              >
                {badge}
              </span>
            )}
          </div>
        )}
      </div>
      <div className="data-panel-content">
        {children}
      </div>
    </section>
  )

  // Wrap with error boundary unless disabled
  if (noErrorBoundary) {
    return panelContent
  }

  return (
    <ErrorBoundary
      panelName={title}
      fallback={
        <section className={`data-panel error-panel ${className}`} aria-labelledby={`panel-${title.toLowerCase().replace(/\s+/g, '-')}-error`}>
          <div className="data-panel-header">
            {renderIcon()}
            <HeadingTag id={`panel-${title.toLowerCase().replace(/\s+/g, '-')}-error`} className="data-panel-title">{title}</HeadingTag>
          </div>
          <div className="data-panel-content">
            <div className="error-boundary-fallback compact">
              <span className="error-boundary-icon">⚠️</span>
              <span className="error-boundary-message">Failed to load panel</span>
            </div>
          </div>
        </section>
      }
    >
      {panelContent}
    </ErrorBoundary>
  )
}
