'use client'

import { ReactNode } from 'react'
import { InfoTooltip } from './InfoTooltip'

interface StatDisplayProps {
  label: string
  value: ReactNode
  variant?: 'default' | 'compact' | 'inline'
  colorMode?: 'default' | 'financial' | 'status'
  positive?: boolean
  negative?: boolean
  status?: 'ok' | 'warning' | 'error' | 'inactive'
  tooltip?: string
  subtext?: ReactNode
  fullWidth?: boolean
  className?: string
}

export function StatDisplay({
  label,
  value,
  variant = 'default',
  colorMode = 'default',
  positive,
  negative,
  status,
  tooltip,
  subtext,
  fullWidth = false,
  className = '',
}: StatDisplayProps) {
  // Determine value color class based on colorMode and props
  const getValueColorClass = (): string => {
    if (colorMode === 'financial') {
      if (positive) return 'stat-value-profit'
      if (negative) return 'stat-value-loss'
      return ''
    }

    if (colorMode === 'status') {
      switch (status) {
        case 'ok': return 'stat-value-ok'
        case 'warning': return 'stat-value-warning'
        case 'error': return 'stat-value-error'
        case 'inactive': return 'stat-value-inactive'
        default: return ''
      }
    }

    // Default mode - still respect positive/negative
    if (positive) return 'stat-value-positive'
    if (negative) return 'stat-value-negative'

    return ''
  }

  const containerClasses = [
    'stat-display',
    `stat-display-${variant}`,
    fullWidth ? 'stat-display-full' : '',
    className
  ].filter(Boolean).join(' ')

  const valueClasses = [
    'stat-display-value',
    getValueColorClass()
  ].filter(Boolean).join(' ')

  return (
    <div className={containerClasses}>
      <span className="stat-display-label">
        {label}
        {tooltip && <InfoTooltip text={tooltip} position="top" />}
      </span>
      <span className={valueClasses}>{value}</span>
      {subtext && <span className="stat-display-subtext">{subtext}</span>}
    </div>
  )
}

export default StatDisplay
