import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import TradeDockPanel from '@/components/TradeDockPanel'
import type { Position } from '@/stores'
import type { RecentTradeRow } from '@/components/TradeDockPanel'

// Mock DataPanelsContainer – render children with title for assertions
jest.mock('@/components/DataPanelsContainer', () => ({
  DataPanel: ({ children, title }: { children: React.ReactNode; title: string }) => (
    <div data-testid="data-panel" data-title={title}>
      {children}
    </div>
  ),
}))

// Mock apiFetch so network calls are captured
jest.mock('@/lib/api', () => ({
  apiFetch: jest.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ message: 'ok' }) }),
  ),
}))

// Mock useOperatorStore – default to unlocked so action buttons are enabled
const mockOperatorState = { isUnlocked: true }
jest.mock('@/stores', () => ({
  useOperatorStore: jest.fn((selector: (s: typeof mockOperatorState) => unknown) =>
    selector(mockOperatorState),
  ),
}))

// ---------------------------------------------------------------------------
// Helpers – reusable mock data
// ---------------------------------------------------------------------------

const makePosition = (overrides: Partial<Position> = {}): Position => ({
  signal_id: 'sig-001',
  direction: 'long',
  entry_price: 18000,
  entry_time: '2025-06-01T14:30:00Z',
  symbol: 'MNQ',
  position_size: 1,
  ...overrides,
})

const makeRecentTrade = (overrides: Partial<RecentTradeRow> = {}): RecentTradeRow => ({
  signal_id: 'sig-100',
  symbol: 'MNQ',
  direction: 'long',
  position_size: 1,
  entry_time: '2025-06-01T14:30:00Z',
  entry_price: 18000,
  exit_time: '2025-06-01T15:00:00Z',
  exit_price: 18050,
  pnl: 100,
  exit_reason: 'target_hit',
  ...overrides,
})

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('TradeDockPanel', () => {
  describe('empty state', () => {
    it('renders without crashing with empty trades data', () => {
      const { container } = render(
        <TradeDockPanel positions={[]} recentTrades={[]} />
      )
      expect(container).toBeTruthy()
    })

    it('shows "No open positions" when there are no open trades', () => {
      render(<TradeDockPanel positions={[]} recentTrades={[]} />)
      expect(screen.getByText('No open positions')).toBeInTheDocument()
    })

    it('shows "No recent trades" when switching to Recent tab with empty data', () => {
      render(<TradeDockPanel positions={[]} recentTrades={[]} />)

      const recentTab = screen.getByRole('tab', { name: /recent/i })
      fireEvent.click(recentTab)

      expect(screen.getByText('No recent trades')).toBeInTheDocument()
    })
  })

  describe('with active trades', () => {
    const twoPositions: Position[] = [
      makePosition({ signal_id: 'sig-001', direction: 'long', entry_price: 18000 }),
      makePosition({ signal_id: 'sig-002', direction: 'short', entry_price: 18100 }),
    ]

    it('renders two open positions', () => {
      render(
        <TradeDockPanel
          positions={twoPositions}
          recentTrades={[]}
          symbol="MNQ"
          currentPrice={18050}
        />
      )

      // Both direction badges should appear
      expect(screen.getByText('LONG')).toBeInTheDocument()
      expect(screen.getByText('SHORT')).toBeInTheDocument()
    })

    it('shows the open position count', () => {
      render(
        <TradeDockPanel
          positions={twoPositions}
          recentTrades={[]}
          symbol="MNQ"
          currentPrice={18050}
        />
      )

      // The "Open" tab badge shows "2"
      const openTab = screen.getByRole('tab', { name: /open/i })
      expect(openTab).toHaveTextContent('2')
    })
  })

  describe('trade direction display', () => {
    it('displays LONG direction correctly', () => {
      render(
        <TradeDockPanel
          positions={[makePosition({ direction: 'long' })]}
          recentTrades={[]}
          symbol="MNQ"
          currentPrice={18050}
        />
      )

      expect(screen.getByText('LONG')).toBeInTheDocument()
    })

    it('displays SHORT direction correctly', () => {
      render(
        <TradeDockPanel
          positions={[makePosition({ direction: 'short', signal_id: 'sig-short' })]}
          recentTrades={[]}
          symbol="MNQ"
          currentPrice={17950}
        />
      )

      expect(screen.getByText('SHORT')).toBeInTheDocument()
    })

    it('displays direction in recent trades tab', () => {
      const recentTrades: RecentTradeRow[] = [
        makeRecentTrade({ direction: 'long', signal_id: 'r-1' }),
        makeRecentTrade({ direction: 'short', signal_id: 'r-2' }),
      ]

      render(
        <TradeDockPanel positions={[]} recentTrades={recentTrades} />
      )

      // Switch to Recent tab
      fireEvent.click(screen.getByRole('tab', { name: /recent/i }))

      expect(screen.getByText('LONG')).toBeInTheDocument()
      expect(screen.getByText('SHORT')).toBeInTheDocument()
    })
  })

  describe('P&L display', () => {
    it('shows unrealized P&L for open positions', () => {
      // MNQ = $2/point, long 1 contract, entry=18000, current=18050
      // Unrealized = (18050 - 18000) * 1 * 1 * 2 = $100
      render(
        <TradeDockPanel
          positions={[makePosition({ direction: 'long', entry_price: 18000, position_size: 1 })]}
          recentTrades={[]}
          symbol="MNQ"
          currentPrice={18050}
        />
      )

      expect(screen.getByText('+$100.00')).toBeInTheDocument()
    })

    it('shows realized P&L for recent trades', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[makeRecentTrade({ pnl: 250.5 })]}
        />
      )

      fireEvent.click(screen.getByRole('tab', { name: /recent/i }))

      expect(screen.getByText('+$250.50')).toBeInTheDocument()
    })

    it('displays negative P&L for losing trades', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[makeRecentTrade({ pnl: -75.25 })]}
        />
      )

      fireEvent.click(screen.getByRole('tab', { name: /recent/i }))

      // formatPnL produces "$-75.25" (sign comes from toFixed, not prefix)
      expect(screen.getByText('$-75.25')).toBeInTheDocument()
    })

    it('shows dash when P&L is null', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[makeRecentTrade({ pnl: null })]}
        />
      )

      fireEvent.click(screen.getByRole('tab', { name: /recent/i }))

      // The "—" dash is used for null P&L
      const pnlElements = screen.getAllByText('—')
      expect(pnlElements.length).toBeGreaterThan(0)
    })
  })

  describe('Close Trade button', () => {
    it('shows "Close All" button when positions exist and operator is unlocked', () => {
      render(
        <TradeDockPanel
          positions={[makePosition()]}
          recentTrades={[]}
          symbol="MNQ"
          currentPrice={18050}
        />
      )

      const closeAllBtn = screen.getByRole('button', { name: /close all/i })
      expect(closeAllBtn).toBeInTheDocument()
      expect(closeAllBtn).not.toBeDisabled()
    })

    it('shows "Close Trade" button in expanded position detail', () => {
      render(
        <TradeDockPanel
          positions={[makePosition()]}
          recentTrades={[]}
          symbol="MNQ"
          currentPrice={18050}
        />
      )

      // Expand the position by clicking on it
      const positionRow = screen.getByRole('button', { name: /long.*mnq/i })
      fireEvent.click(positionRow)

      const closeTradeBtn = screen.getByRole('button', { name: /close trade/i })
      expect(closeTradeBtn).toBeInTheDocument()
      expect(closeTradeBtn).not.toBeDisabled()
    })

    it('shows confirmation flow when "Close All" is clicked', () => {
      render(
        <TradeDockPanel
          positions={[makePosition()]}
          recentTrades={[]}
          symbol="MNQ"
          currentPrice={18050}
        />
      )

      fireEvent.click(screen.getByRole('button', { name: /close all/i }))

      // Confirm and Cancel buttons should appear
      expect(screen.getByRole('button', { name: /confirm/i })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument()
    })
  })

  describe('handles empty state gracefully', () => {
    it('renders with all optional props undefined', () => {
      const { container } = render(
        <TradeDockPanel positions={[]} recentTrades={[]} />
      )

      expect(container).toBeTruthy()
      expect(screen.getByText('No open positions')).toBeInTheDocument()
    })

    it('renders positions without currentPrice gracefully', () => {
      render(
        <TradeDockPanel
          positions={[makePosition()]}
          recentTrades={[]}
          symbol="MNQ"
        />
      )

      // Unrealized P&L is "—" when currentPrice is not available
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThan(0)
    })

    it('renders with null pnl and null prices in recent trades', () => {
      render(
        <TradeDockPanel
          positions={[]}
          recentTrades={[
            makeRecentTrade({
              pnl: null,
              entry_price: null,
              exit_price: null,
              entry_time: null,
              exit_time: null,
            }),
          ]}
        />
      )

      fireEvent.click(screen.getByRole('tab', { name: /recent/i }))

      // Should not crash, dashes should be present
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThan(0)
    })
  })
})
