'use client'

import { ReactNode } from 'react'

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
}

export function DataPanel({ title, icon, children, className = '' }: DataPanelProps) {
  return (
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
}
