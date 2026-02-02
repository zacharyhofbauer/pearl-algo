'use client'

import { useCallback, useRef, KeyboardEvent, ReactNode } from 'react'

export interface Tab<T extends string = string> {
  id: T
  label: string
  badge?: string | number
  icon?: ReactNode
  disabled?: boolean
}

export type TabVariant = 'default' | 'compact' | 'pill'

interface TabsProps<T extends string = string> {
  tabs: Tab<T>[]
  activeTab: T
  onTabChange: (tab: T) => void
  variant?: TabVariant
  className?: string
  fullWidth?: boolean
  'aria-label'?: string
}

const variantClasses: Record<TabVariant, { container: string; tab: string }> = {
  default: {
    container: 'tabs-container tabs-default',
    tab: 'tab tab-default',
  },
  compact: {
    container: 'tabs-container tabs-compact',
    tab: 'tab tab-compact',
  },
  pill: {
    container: 'tabs-container tabs-pill',
    tab: 'tab tab-pill',
  },
}

export function Tabs<T extends string = string>({
  tabs,
  activeTab,
  onTabChange,
  variant = 'default',
  className = '',
  fullWidth = true,
  'aria-label': ariaLabel = 'Tab navigation',
}: TabsProps<T>) {
  const tabsRef = useRef<HTMLDivElement>(null)
  const classes = variantClasses[variant]

  const handleKeyDown = useCallback(
    (event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
      const enabledTabs = tabs.filter((t) => !t.disabled)
      const currentEnabledIndex = enabledTabs.findIndex(
        (t) => t.id === tabs[currentIndex].id
      )

      let newIndex = currentEnabledIndex

      switch (event.key) {
        case 'ArrowLeft':
          event.preventDefault()
          newIndex =
            currentEnabledIndex > 0
              ? currentEnabledIndex - 1
              : enabledTabs.length - 1
          break
        case 'ArrowRight':
          event.preventDefault()
          newIndex =
            currentEnabledIndex < enabledTabs.length - 1
              ? currentEnabledIndex + 1
              : 0
          break
        case 'Home':
          event.preventDefault()
          newIndex = 0
          break
        case 'End':
          event.preventDefault()
          newIndex = enabledTabs.length - 1
          break
        default:
          return
      }

      const newTab = enabledTabs[newIndex]
      if (newTab) {
        onTabChange(newTab.id)
        // Focus the new tab button
        const tabButton = tabsRef.current?.querySelector(
          `[data-tab-id="${newTab.id}"]`
        ) as HTMLButtonElement | null
        tabButton?.focus()
      }
    },
    [tabs, onTabChange]
  )

  return (
    <div
      ref={tabsRef}
      className={`${classes.container} ${className}`}
      role="tablist"
      aria-label={ariaLabel}
      style={fullWidth ? { width: '100%' } : undefined}
    >
      {tabs.map((tab, index) => {
        const isActive = tab.id === activeTab
        const isDisabled = tab.disabled

        return (
          <button
            key={tab.id}
            data-tab-id={tab.id}
            role="tab"
            aria-selected={isActive}
            aria-controls={`tabpanel-${tab.id}`}
            aria-disabled={isDisabled}
            tabIndex={isActive ? 0 : -1}
            className={`${classes.tab} ${isActive ? 'active' : ''} ${
              isDisabled ? 'disabled' : ''
            }`}
            onClick={() => !isDisabled && onTabChange(tab.id)}
            onKeyDown={(e) => handleKeyDown(e, index)}
            disabled={isDisabled}
            style={fullWidth ? { flex: 1 } : undefined}
          >
            {tab.icon && <span className="tab-icon">{tab.icon}</span>}
            <span className="tab-label">{tab.label}</span>
            {tab.badge !== undefined && (
              <span className="tab-badge">{tab.badge}</span>
            )}
          </button>
        )
      })}
    </div>
  )
}

export default Tabs
