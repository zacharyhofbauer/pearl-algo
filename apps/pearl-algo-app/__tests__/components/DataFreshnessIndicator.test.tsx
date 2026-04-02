import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import DataFreshnessIndicator from '@/components/DataFreshnessIndicator'
import type { WebSocketStatus } from '@/hooks/useWebSocket'

// Mock formatTimeAgo
jest.mock('@/utils/formatting', () => ({
  formatTimeAgo: jest.fn((seconds: number) => {
    if (seconds < 60) return `${seconds}s`
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m`
    return `${Math.floor(seconds / 3600)}h`
  }),
}))

describe('DataFreshnessIndicator', () => {
  beforeEach(() => {
    jest.useFakeTimers()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  describe('freshness calculation', () => {
    it('should calculate seconds ago correctly', () => {
      const now = Date.now()
      const fiveSecondsAgo = new Date(now - 5000)
      jest.setSystemTime(now)

      render(
        <DataFreshnessIndicator
          lastUpdate={fiveSecondsAgo}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
        />
      )

      jest.advanceTimersByTime(1000)
      expect(screen.getByText(/5s/)).toBeInTheDocument()
    })

    it('should update every second', async () => {
      const now = Date.now()
      const tenSecondsAgo = new Date(now - 10000)
      jest.setSystemTime(now)

      render(
        <DataFreshnessIndicator
          lastUpdate={tenSecondsAgo}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
        />
      )

      expect(screen.getByText(/10s/)).toBeInTheDocument()

      jest.advanceTimersByTime(1000)
      await waitFor(() => {
        expect(screen.getByText(/11s/)).toBeInTheDocument()
      })
    })

    it('should handle null lastUpdate', () => {
      render(
        <DataFreshnessIndicator
          lastUpdate={null}
          wsStatus="disconnected"
          dataSource="unknown"
          isLoading={false}
          variant="full"
        />
      )

      expect(screen.getByText(/never/)).toBeInTheDocument()
    })
  })

  describe('stale threshold', () => {
    it('should mark as stale when exceeding threshold', () => {
      const now = Date.now()
      const staleTime = new Date(now - 120000) // 2 minutes ago
      jest.setSystemTime(now)

      render(
        <DataFreshnessIndicator
          lastUpdate={staleTime}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          staleThresholdSeconds={60}
        />
      )

      const indicator = screen.getByRole('status')
      expect(indicator).toHaveAttribute('aria-label', expect.stringContaining('stale'))
    })

    it('should mark as warning when approaching threshold', () => {
      const now = Date.now()
      const warningTime = new Date(now - 45000) // 45 seconds ago
      jest.setSystemTime(now)

      render(
        <DataFreshnessIndicator
          lastUpdate={warningTime}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          staleThresholdSeconds={60}
        />
      )

      const indicator = screen.getByRole('status')
      expect(indicator).toHaveAttribute('aria-label', expect.stringContaining('warning'))
    })

    it('should mark as fresh when well below threshold', () => {
      const now = Date.now()
      const freshTime = new Date(now - 10000) // 10 seconds ago
      jest.setSystemTime(now)

      render(
        <DataFreshnessIndicator
          lastUpdate={freshTime}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          staleThresholdSeconds={60}
        />
      )

      const indicator = screen.getByRole('status')
      expect(indicator).toHaveAttribute('aria-label', expect.stringContaining('fresh'))
    })

    it('should use custom stale threshold', () => {
      const now = Date.now()
      const staleTime = new Date(now - 120000) // 2 minutes ago
      jest.setSystemTime(now)

      render(
        <DataFreshnessIndicator
          lastUpdate={staleTime}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          staleThresholdSeconds={180} // 3 minutes
        />
      )

      const indicator = screen.getByRole('status')
      expect(indicator).toHaveAttribute('aria-label', expect.stringContaining('warning'))
    })
  })

  describe('display formatting (full variant)', () => {
    it('should display WebSocket status correctly', () => {
      render(
        <DataFreshnessIndicator
          lastUpdate={new Date()}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          variant="full"
        />
      )

      expect(screen.getByText('WS')).toBeInTheDocument()
    })

    it('should display data source correctly', () => {
      render(
        <DataFreshnessIndicator
          lastUpdate={new Date()}
          wsStatus="disconnected"
          dataSource="cached"
          isLoading={false}
          variant="full"
        />
      )

      expect(screen.getByText('CACHE')).toBeInTheDocument()
    })

    it('should show loading state', () => {
      const { container } = render(
        <DataFreshnessIndicator
          lastUpdate={new Date()}
          wsStatus="connecting"
          dataSource="live"
          isLoading={true}
          variant="full"
        />
      )

      // Full variant shows a loading overlay with spinner
      expect(container.querySelector('.freshness-loading-overlay')).toBeInTheDocument()
      expect(container.querySelector('.loading-spinner')).toBeInTheDocument()
    })
  })

  describe('compact variant', () => {
    it('should render compact variant', () => {
      render(
        <DataFreshnessIndicator
          lastUpdate={new Date()}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          variant="compact"
        />
      )

      expect(screen.getByRole('status')).toBeInTheDocument()
    })

    it('should expand on click in compact variant', () => {
      render(
        <DataFreshnessIndicator
          lastUpdate={new Date()}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          variant="compact"
        />
      )

      const container = screen.getByRole('status').closest('div')
      expect(container).toHaveAttribute('aria-expanded', 'false')

      fireEvent.click(container!)

      expect(container).toHaveAttribute('aria-expanded', 'true')
      expect(screen.getByText('Status')).toBeInTheDocument()
    })

    it('should call onRefresh when refresh button clicked', () => {
      const onRefresh = jest.fn()
      render(
        <DataFreshnessIndicator
          lastUpdate={new Date()}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          variant="compact"
          onRefresh={onRefresh}
        />
      )

      const container = screen.getByRole('status').closest('div')
      fireEvent.click(container!)

      const refreshButton = screen.getByText(/refresh/i)
      fireEvent.click(refreshButton)

      expect(onRefresh).toHaveBeenCalledTimes(1)
    })
  })

  describe('floating variant', () => {
    it('should render floating variant', () => {
      render(
        <DataFreshnessIndicator
          lastUpdate={new Date()}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          variant="floating"
        />
      )

      expect(screen.getByText('LIVE')).toBeInTheDocument()
    })

    it('should expand and show details in floating variant', () => {
      render(
        <DataFreshnessIndicator
          lastUpdate={new Date()}
          wsStatus="connected"
          dataSource="live"
          isLoading={false}
          variant="floating"
        />
      )

      const header = screen.getByText('LIVE').closest('.freshness-floating-header')
      expect(header).toHaveAttribute('aria-expanded', 'false')

      fireEvent.click(header!)

      expect(header).toHaveAttribute('aria-expanded', 'true')
      expect(screen.getByText('Last Update')).toBeInTheDocument()
    })
  })

  describe('edge cases', () => {
    it('should handle all WebSocket statuses in full variant', () => {
      const statuses: WebSocketStatus[] = ['connected', 'connecting', 'disconnected', 'error']

      statuses.forEach((status) => {
        const { unmount } = render(
          <DataFreshnessIndicator
            lastUpdate={new Date()}
            wsStatus={status}
            dataSource="live"
            isLoading={false}
            variant="full"
          />
        )
        expect(screen.getByText(/WS|POLL|ERR/)).toBeInTheDocument()
        unmount()
      })
    })

    it('should handle all data sources in full variant', () => {
      const sources: Array<'live' | 'cached' | 'unknown'> = ['live', 'cached', 'unknown']

      sources.forEach((source) => {
        const { unmount } = render(
          <DataFreshnessIndicator
            lastUpdate={new Date()}
            wsStatus="connected"
            dataSource={source}
            isLoading={false}
            variant="full"
          />
        )
        expect(screen.getByText(/LIVE|CACHE|\?/)).toBeInTheDocument()
        unmount()
      })
    })
  })
})
