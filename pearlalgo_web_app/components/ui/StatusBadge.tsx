'use client'

import { CSSProperties } from 'react'

export type StatusType =
  | 'online'
  | 'offline'
  | 'warning'
  | 'active'
  | 'inactive'
  | 'live'
  | 'shadow'
  | 'paused'
  | 'error'
  | 'cooldown'

export type BadgeVariant = 'dot' | 'pill' | 'minimal' | 'chip'

interface StatusBadgeProps {
  status: StatusType
  label?: string
  variant?: BadgeVariant
  pulse?: boolean
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const statusConfig: Record<
  StatusType,
  { color: string; bgColor: string; dotColor: string; defaultLabel: string }
> = {
  online: {
    color: 'var(--accent-green)',
    bgColor: 'rgba(var(--accent-green-rgb), 0.12)',
    dotColor: 'var(--accent-green)',
    defaultLabel: 'Online',
  },
  offline: {
    color: 'var(--accent-red)',
    bgColor: 'rgba(var(--accent-red-rgb), 0.12)',
    dotColor: 'var(--accent-red)',
    defaultLabel: 'Offline',
  },
  warning: {
    color: 'var(--accent-yellow)',
    bgColor: 'rgba(var(--accent-yellow-rgb), 0.12)',
    dotColor: 'var(--accent-yellow)',
    defaultLabel: 'Warning',
  },
  active: {
    color: 'var(--accent-green)',
    bgColor: 'rgba(var(--accent-green-rgb), 0.12)',
    dotColor: 'var(--accent-green)',
    defaultLabel: 'Active',
  },
  inactive: {
    color: 'var(--text-tertiary)',
    bgColor: 'var(--bg-elevated)',
    dotColor: 'var(--text-tertiary)',
    defaultLabel: 'Inactive',
  },
  live: {
    color: 'var(--accent-green)',
    bgColor: 'rgba(var(--accent-green-rgb), 0.12)',
    dotColor: 'var(--accent-green)',
    defaultLabel: 'LIVE',
  },
  shadow: {
    color: 'var(--accent-yellow)',
    bgColor: 'rgba(var(--accent-yellow-rgb), 0.12)',
    dotColor: 'var(--accent-yellow)',
    defaultLabel: 'SHADOW',
  },
  paused: {
    color: 'var(--accent-yellow)',
    bgColor: 'rgba(var(--accent-yellow-rgb), 0.12)',
    dotColor: 'var(--accent-yellow)',
    defaultLabel: 'Paused',
  },
  error: {
    color: 'var(--accent-red)',
    bgColor: 'rgba(var(--accent-red-rgb), 0.12)',
    dotColor: 'var(--accent-red)',
    defaultLabel: 'Error',
  },
  cooldown: {
    color: 'var(--accent-yellow)',
    bgColor: 'rgba(var(--accent-yellow-rgb), 0.12)',
    dotColor: 'var(--accent-yellow)',
    defaultLabel: 'Cooldown',
  },
}

const sizeConfig = {
  sm: {
    dotSize: 6,
    fontSize: 'var(--font-size-xs)',
    padding: '2px 6px',
    gap: 'var(--space-2)',
  },
  md: {
    dotSize: 8,
    fontSize: 'var(--font-size-sm)',
    padding: '3px 8px',
    gap: 'var(--space-3)',
  },
  lg: {
    dotSize: 10,
    fontSize: 'var(--font-size-md)',
    padding: '4px 10px',
    gap: 'var(--space-3)',
  },
}

export function StatusBadge({
  status,
  label,
  variant = 'pill',
  pulse = false,
  size = 'md',
  className = '',
}: StatusBadgeProps) {
  const config = statusConfig[status]
  const sizeStyles = sizeConfig[size]
  const displayLabel = label ?? config.defaultLabel

  // Auto-pulse for active statuses
  const shouldPulse =
    pulse || (status === 'live' || status === 'online' || status === 'active')

  const baseStyles: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: sizeStyles.gap,
    color: config.color,
    fontWeight: 500,
    fontSize: sizeStyles.fontSize,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.5px',
  }

  const dotStyles: CSSProperties = {
    width: sizeStyles.dotSize,
    height: sizeStyles.dotSize,
    borderRadius: '50%',
    backgroundColor: config.dotColor,
    flexShrink: 0,
    ...(shouldPulse && {
      animation: 'pulse-dot 2s infinite',
    }),
  }

  if (variant === 'dot') {
    return (
      <span
        className={`status-badge status-badge-dot ${className}`}
        style={baseStyles}
      >
        <span style={dotStyles} />
        {displayLabel && <span>{displayLabel}</span>}
      </span>
    )
  }

  if (variant === 'minimal') {
    return (
      <span
        className={`status-badge status-badge-minimal ${className}`}
        style={{
          ...baseStyles,
          opacity: status === 'inactive' ? 0.6 : 1,
        }}
      >
        <span style={dotStyles} />
      </span>
    )
  }

  if (variant === 'chip') {
    return (
      <span
        className={`status-badge status-badge-chip status-chip ${status} ${className}`}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: sizeStyles.gap,
          padding: sizeStyles.padding,
          borderRadius: '4px',
          fontSize: sizeStyles.fontSize,
          fontWeight: 500,
          background: config.bgColor,
          color: config.color,
        }}
      >
        {displayLabel}
      </span>
    )
  }

  // Default: pill variant
  return (
    <span
      className={`status-badge status-badge-pill ${className}`}
      style={{
        ...baseStyles,
        padding: sizeStyles.padding,
        borderRadius: '8px',
        background: config.bgColor,
        border: `1px solid ${config.bgColor}`,
      }}
    >
      <span style={dotStyles} />
      <span>{displayLabel}</span>
    </span>
  )
}

export default StatusBadge
