'use client'

import React, { useState, useCallback, useRef } from 'react'
import type { RightPanelTab } from '@/stores/uiStore'
import PaneDivider from '@/components/chart/PaneDivider'

interface PullToRefreshProps {
  pullDistance: number
  pullRefreshing: boolean
  pullThreshold: number
}

interface DashboardLayoutProps {
  isChartReady: boolean
  pull: PullToRefreshProps
  header: React.ReactNode
  chart: React.ReactNode
  panels: React.ReactNode
  activeRightPanel: RightPanelTab
  onToggleRightPanel: (panel: 'watchlist' | 'logs' | 'activity') => void
  onCloseRightPanel: () => void
  rightPanelContent: React.ReactNode
}

const DashboardLayout = React.memo(function DashboardLayout({
  isChartReady,
  pull,
  header,
  chart,
  panels,
  activeRightPanel,
  onToggleRightPanel,
  onCloseRightPanel,
  rightPanelContent,
}: DashboardLayoutProps) {
  const DEFAULT_PANEL_HEIGHT = 280
  const [panelHeight, setPanelHeight] = useState(DEFAULT_PANEL_HEIGHT)
  const mainRef = useRef<HTMLDivElement>(null)

  const handlePaneResize = useCallback((deltaY: number) => {
    setPanelHeight(prev => {
      const next = prev - deltaY
      return Math.max(60, Math.min(next, 600))
    })
  }, [])

  const handlePaneReset = useCallback(() => {
    setPanelHeight(DEFAULT_PANEL_HEIGHT)
  }, [])

  return (
    <>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <main className="tv-layout" id="main-content">
        {/* Pull to refresh — mobile only */}
        <div
          className={`pull-to-refresh ${pull.pullRefreshing ? 'refreshing' : ''} ${pull.pullDistance > 0 ? 'visible' : ''}`}
          style={{
            height: pull.pullDistance > 0 ? pull.pullDistance : 0,
            opacity: pull.pullDistance > 0 ? Math.min(pull.pullDistance / pull.pullThreshold, 1) : 0,
          }}
        >
          <div
            className={`pull-icon ${pull.pullRefreshing ? 'spinning' : ''}`}
            style={{
              transform: pull.pullRefreshing
                ? 'none'
                : `rotate(${Math.min(pull.pullDistance / pull.pullThreshold, 1) * 180}deg)`,
            }}
          >
            {pull.pullRefreshing ? '\u21BB' : '\u2193'}
          </div>
          <div className="pull-text">
            {pull.pullRefreshing
              ? 'Refreshing...'
              : pull.pullDistance >= pull.pullThreshold
                ? 'Release to refresh'
                : 'Pull to refresh'}
          </div>
        </div>

        {/* Top toolbar — full width */}
        {header}

        {/* Body — left sidebar (tools) + main + right panel + right sidebar (widgets) */}
        <div className="tv-body" data-chart-ready={isChartReady ? 'true' : 'false'}>
          {/* Left sidebar — drawing tools */}
          <aside className="tv-sidebar tv-sidebar-left" aria-label="Tools">
            <button className="tv-sidebar-icon" title="Crosshair">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <line x1="9" y1="1" x2="9" y2="17"/><line x1="1" y1="9" x2="17" y2="9"/>
              </svg>
            </button>
            <button className="tv-sidebar-icon" title="Horizontal line">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <line x1="1" y1="9" x2="17" y2="9"/>
              </svg>
            </button>
            <button className="tv-sidebar-icon" title="Fibonacci">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <line x1="1" y1="3" x2="17" y2="3"/><line x1="1" y1="7.5" x2="17" y2="7.5"/><line x1="1" y1="11" x2="17" y2="11"/><line x1="1" y1="15" x2="17" y2="15"/>
              </svg>
            </button>
            <button className="tv-sidebar-icon" title="Measure">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <rect x="2" y="7" width="14" height="4" rx="1"/><line x1="5" y1="7" x2="5" y2="11"/><line x1="9" y1="7" x2="9" y2="11"/><line x1="13" y1="7" x2="13" y2="11"/>
              </svg>
            </button>
            <button className="tv-sidebar-icon" title="Zoom">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <circle cx="8" cy="8" r="5"/><line x1="12" y1="12" x2="16" y2="16"/><line x1="6" y1="8" x2="10" y2="8"/><line x1="8" y1="6" x2="8" y2="10"/>
              </svg>
            </button>
          </aside>

          <div className="tv-main" ref={mainRef}>
            <div className="tv-chart-area">
              {chart}
            </div>
            <PaneDivider onResize={handlePaneResize} onDoubleClick={handlePaneReset} />
            <div
              className="tv-panel-area"
              style={{ flex: `0 0 ${panelHeight}px`, maxHeight: `${panelHeight}px` }}
            >
              {panels}
            </div>
          </div>

          {/* Right panel — slides open when active */}
          <div
            className="tv-right-panel"
            data-state={activeRightPanel ? 'open' : 'closed'}
          >
            <div className="tv-right-panel-header">
              <span className="tv-right-panel-title">
                {activeRightPanel === 'watchlist' ? 'Watchlist' : activeRightPanel === 'activity' ? 'Activity Log' : activeRightPanel === 'logs' ? 'System Status' : ''}
              </span>
              <button className="tv-right-panel-close" onClick={onCloseRightPanel} title="Close panel">
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                  <line x1="2" y1="2" x2="12" y2="12"/><line x1="12" y1="2" x2="2" y2="12"/>
                </svg>
              </button>
            </div>
            <div className="tv-right-panel-body">
              {rightPanelContent}
            </div>
          </div>

          {/* Right sidebar — widget toggles */}
          <aside className="tv-sidebar tv-sidebar-right" aria-label="Widgets">
            <button
              className={`tv-sidebar-icon ${activeRightPanel === 'watchlist' ? 'active' : ''}`}
              title="Watchlist"
              onClick={() => onToggleRightPanel('watchlist')}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <rect x="3" y="2" width="12" height="14" rx="2"/><line x1="6" y1="6" x2="12" y2="6"/><line x1="6" y1="9" x2="12" y2="9"/><line x1="6" y1="12" x2="10" y2="12"/>
              </svg>
            </button>
            <button
              className={`tv-sidebar-icon ${activeRightPanel === 'activity' ? 'active' : ''}`}
              title="Activity Log"
              onClick={() => onToggleRightPanel('activity')}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <path d="M3 4h12M3 8h8M3 12h10M3 16h6"/>
              </svg>
            </button>
            <button
              className={`tv-sidebar-icon ${activeRightPanel === 'logs' ? 'active' : ''}`}
              title="System Status"
              onClick={() => onToggleRightPanel('logs')}
            >
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <circle cx="9" cy="9" r="7"/><line x1="9" y1="5" x2="9" y2="9"/><line x1="9" y1="9" x2="12" y2="11"/>
              </svg>
            </button>
            <button className="tv-sidebar-icon" title="Calendar">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <rect x="2" y="3" width="14" height="13" rx="2"/><line x1="2" y1="7" x2="16" y2="7"/><line x1="6" y1="1" x2="6" y2="4"/><line x1="12" y1="1" x2="12" y2="4"/>
              </svg>
            </button>
            <button className="tv-sidebar-icon" title="Settings">
              <svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <circle cx="9" cy="9" r="2.5"/><path d="M9 1.5v2M9 14.5v2M1.5 9h2M14.5 9h2M3.1 3.1l1.4 1.4M13.5 13.5l1.4 1.4M3.1 14.9l1.4-1.4M13.5 4.5l1.4-1.4"/>
              </svg>
            </button>
          </aside>
        </div>
      </main>
    </>
  )
})

export default DashboardLayout
