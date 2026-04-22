import React from 'react'
import { render, screen } from '@testing-library/react'
import DashboardLayout from '@/components/DashboardLayout'

describe('DashboardLayout', () => {
  it('renders skip link with "Skip to main content"', () => {
    render(
      <DashboardLayout
        isChartReady={false}
        pull={{ pullDistance: 0, pullRefreshing: false, pullThreshold: 80 }}
        header={<div>Header</div>}
        chart={<div>Chart</div>}
        panels={<div>Panels</div>}
        activeRightPanel={null}
        onToggleRightPanel={() => {}}
        onCloseRightPanel={() => {}}
        rightPanelContent={null}
      />
    )
    const skipLink = screen.getByRole('link', { name: /skip to main content/i })
    expect(skipLink).toHaveAttribute('href', '#main-content')
  })

  it('renders header, chart, panels as children', () => {
    render(
      <DashboardLayout
        isChartReady={false}
        pull={{ pullDistance: 0, pullRefreshing: false, pullThreshold: 80 }}
        header={<div>Header</div>}
        chart={<div>Chart</div>}
        panels={<div>Panels</div>}
        activeRightPanel={null}
        onToggleRightPanel={() => {}}
        onCloseRightPanel={() => {}}
        rightPanelContent={null}
      />
    )
    expect(screen.getByText('Header')).toBeInTheDocument()
    expect(screen.getByText('Chart')).toBeInTheDocument()
    expect(screen.getByText('Panels')).toBeInTheDocument()
  })

  it('shows pull-to-refresh text when pullDistance > 0', () => {
    render(
      <DashboardLayout
        isChartReady={false}
        pull={{ pullDistance: 40, pullRefreshing: false, pullThreshold: 80 }}
        header={<div>Header</div>}
        chart={<div>Chart</div>}
        panels={<div>Panels</div>}
        activeRightPanel={null}
        onToggleRightPanel={() => {}}
        onCloseRightPanel={() => {}}
        rightPanelContent={null}
      />
    )
    expect(screen.getByText('Pull to refresh')).toBeInTheDocument()
  })

  it('shows "Refreshing..." when pullRefreshing is true', () => {
    render(
      <DashboardLayout
        isChartReady={false}
        pull={{ pullDistance: 80, pullRefreshing: true, pullThreshold: 80 }}
        header={<div>Header</div>}
        chart={<div>Chart</div>}
        panels={<div>Panels</div>}
        activeRightPanel={null}
        onToggleRightPanel={() => {}}
        onCloseRightPanel={() => {}}
        rightPanelContent={null}
      />
    )
    expect(screen.getByText('Refreshing...')).toBeInTheDocument()
  })

  it('sets data-chart-ready attribute', () => {
    const { container } = render(
      <DashboardLayout
        isChartReady={true}
        pull={{ pullDistance: 0, pullRefreshing: false, pullThreshold: 80 }}
        header={<div>Header</div>}
        chart={<div>Chart</div>}
        panels={<div>Panels</div>}
        activeRightPanel={null}
        onToggleRightPanel={() => {}}
        onCloseRightPanel={() => {}}
        rightPanelContent={null}
      />
    )
    const dashboard = container.querySelector('[data-chart-ready]')
    expect(dashboard).toHaveAttribute('data-chart-ready', 'true')
  })

  it('sets data-chart-ready to false when chart not ready', () => {
    const { container } = render(
      <DashboardLayout
        isChartReady={false}
        pull={{ pullDistance: 0, pullRefreshing: false, pullThreshold: 80 }}
        header={<div>Header</div>}
        chart={<div>Chart</div>}
        panels={<div>Panels</div>}
        activeRightPanel={null}
        onToggleRightPanel={() => {}}
        onCloseRightPanel={() => {}}
        rightPanelContent={null}
      />
    )
    const dashboard = container.querySelector('[data-chart-ready]')
    expect(dashboard).toHaveAttribute('data-chart-ready', 'false')
  })
})
