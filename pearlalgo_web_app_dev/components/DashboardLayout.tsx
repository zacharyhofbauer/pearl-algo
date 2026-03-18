'use client'

import React from 'react'

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
}

const DashboardLayout = React.memo(function DashboardLayout({
  isChartReady,
  pull,
  header,
  chart,
  panels,
}: DashboardLayoutProps) {
  return (
    <>
      <a href="#main-content" className="skip-link">Skip to main content</a>
      <main className="main-content" id="main-content">
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
        <div className="dashboard-outer">
          <div className="dashboard" data-chart-ready={isChartReady ? 'true' : 'false'}>
            {header}
            {chart}
            {panels}
          </div>
        </div>
      </main>
    </>
  )
})

export default DashboardLayout
