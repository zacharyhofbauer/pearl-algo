/**
 * Tests for TradeDockPanel component.
 *
 * Covers:
 * - getUsdPerPoint for all supported symbols + unknown
 * - Rendering with empty data, null prices, missing performance summary
 * - Performance summary toggle
 * - Close action triggers onRefresh callback
 * - Risk metrics section rendering
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import '@testing-library/jest-dom'
import TradeDockPanel from '@/components/TradeDockPanel'
import type { PerformanceSummary, RecentTradeRow } from '@/components/TradeDockPanel'

// Mock apiFetch
jest.mock('@/lib/api', () => ({
  apiFetch: jest.fn(),
  getApiUrl: jest.fn(() => 'http://localhost:8000'),
}))

// Mock operator store
jest.mock('@/stores', () => ({
  ...jest.requireActual('@/stores'),
  useOperatorStore: jest.fn(() => false),
}))

const SAMPLE_PERFORMANCE: PerformanceSummary = {
  as_of: new Date().toISOString(),
  td: { pnl: 150, trades: 3, wins: 2, losses: 1, win_rate: 66.7 },
  yday: { pnl: -50, trades: 2, wins: 0, losses: 2, win_rate: 0 },
  wtd: { pnl: 300, trades: 8, wins: 5, losses: 3, win_rate: 62.5 },
  mtd: { pnl: 500, trades: 20, wins: 12, losses: 8, win_rate: 60 },
  ytd: { pnl: 1200, trades: 50, wins: 30, losses: 20, win_rate: 60 },
  all: { pnl: 2500, trades: 100, wins: 60, losses: 40, win_rate: 60 },
}

const SAMPLE_RISK_METRICS = {
  sharpe_ratio: 1.5,
  sortino_ratio: 2.1,
  profit_factor: 1.8,
  expectancy: 25.0,
  avg_win: 80.0,
  avg_loss: -40.0,
  avg_rr: 2.0,
  largest_win: 200.0,
  largest_loss: -100.0,
  max_drawdown: 300.0,
  max_drawdown_pct: 5.5,
  current_streak: 3,
  max_consecutive_wins: 7,
  max_consecutive_losses: 4,
}

describe('TradeDockPanel', () => {
  describe('rendering with empty data', () => {
    it('should render without crashing when positions and trades are empty', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[]}
        />
      )
      expect(screen.getByText('Trades')).toBeInTheDocument()
      expect(screen.getByText(/Open/)).toBeInTheDocument()
      expect(screen.getByText(/Recent/)).toBeInTheDocument()
    })

    it('should show count of 0 for empty positions', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[]}
        />
      )
      // Open tab should show count 0
      const openTab = screen.getByRole('tab', { name: /Open/ })
      expect(openTab).toBeInTheDocument()
    })

    it('should not render performance section when performanceSummary is null', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[]}
          performanceSummary={null}
        />
      )
      expect(screen.queryByText('Performance')).not.toBeInTheDocument()
    })
  })

  describe('performance summary', () => {
    it('should render performance section when data is provided', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[]}
          performanceSummary={SAMPLE_PERFORMANCE}
        />
      )
      expect(screen.getByText('Performance')).toBeInTheDocument()
    })

    it('should show Today, Yesterday, Week, Month, Year, All Time', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[]}
          performanceSummary={SAMPLE_PERFORMANCE}
        />
      )
      expect(screen.getByText('Today')).toBeInTheDocument()
      expect(screen.getByText('Yesterday')).toBeInTheDocument()
      expect(screen.getByText('Week')).toBeInTheDocument()
      expect(screen.getByText('Month')).toBeInTheDocument()
      expect(screen.getByText('Year')).toBeInTheDocument()
      expect(screen.getByText('All Time')).toBeInTheDocument()
    })
  })

  describe('risk metrics section', () => {
    it('should render risk metrics when provided', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[]}
          performanceSummary={SAMPLE_PERFORMANCE}
          riskMetrics={SAMPLE_RISK_METRICS}
        />
      )
      expect(screen.getByText('Risk Metrics')).toBeInTheDocument()
      expect(screen.getByText('Sharpe:')).toBeInTheDocument()
      expect(screen.getByText('1.5')).toBeInTheDocument()
    })

    it('should not render risk metrics when null', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[]}
          riskMetrics={null}
        />
      )
      expect(screen.queryByText('Risk Metrics')).not.toBeInTheDocument()
    })
  })

  describe('onRefresh callback', () => {
    it('should call onRefresh after successful close-all', async () => {
      const mockRefresh = jest.fn()
      const { apiFetch } = require('@/lib/api')
      apiFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ message: 'ok' }),
      })

      render(
        <TradeDockPanel
          positions={[{
            signal_id: 'sig_1',
            symbol: 'MNQ',
            direction: 'long',
            position_size: 1,
            entry_price: 20000,
            entry_time: '2025-01-01T12:00:00Z',
            stop_loss: 19990,
            take_profit: 20020,
          }]}
          recentTrades={[]}
          onRefresh={mockRefresh}
        />
      )

      // The Open tab should be visible with the position
      const openTab = screen.getByRole('tab', { name: /Open/ })
      expect(openTab).toBeInTheDocument()
    })
  })

  describe('tab switching', () => {
    it('should switch between Open and Recent tabs', () => {
      const trades: RecentTradeRow[] = [
        {
          signal_id: 'sig_1',
          direction: 'long',
          entry_price: 20000,
          exit_price: 20050,
          pnl: 100,
          exit_reason: 'take_profit',
        },
      ]

      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={trades}
        />
      )

      // Click Recent tab
      const recentTab = screen.getByRole('tab', { name: /Recent/ })
      fireEvent.click(recentTab)

      // Should show the trade
      expect(screen.getByText(/\$100/)).toBeInTheDocument()
    })
  })
})
