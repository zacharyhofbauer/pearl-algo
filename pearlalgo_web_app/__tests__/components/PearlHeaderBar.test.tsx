import React from 'react'
import { render, screen } from '@testing-library/react'
import PearlHeaderBar from '@/components/PearlHeaderBar'
import { useAgentStore, useOperatorStore } from '@/stores'

jest.mock('next/image', () => ({
  __esModule: true,
  default: ({ src, alt, width, height }: { src: string; alt: string; width: number; height: number }) => (
    <img src={src} alt={alt} width={width} height={height} />
  ),
}))

jest.mock('@/components/AccountSwitcher', () => ({
  __esModule: true,
  default: () => <div data-testid="account-switcher">Account Switcher</div>,
}))

const mockAgentState = {
  agentState: {
    running: true,
    futures_market_open: true,
    ai_status: {
      bandit_mode: 'live',
      contextual_mode: 'live',
      ml_filter: { enabled: true, mode: 'live', lift: {} },
      direction_gating: { enabled: true, blocks: 0, shadow_regime: 0, shadow_trigger: 0 },
    },
    pearl_insights: null,
    pearl_feed: [],
    pearl_suggestion: null,
    accounts: {
      ibkr_virtual: { display_name: 'IBKR Virtual', badge: 'VIRTUAL', badge_color: '#00d4ff', telegram_prefix: '', description: '' },
    },
  },
  accounts: {
    ibkr_virtual: { display_name: 'IBKR Virtual', badge: 'VIRTUAL', badge_color: '#00d4ff', telegram_prefix: '', description: '' },
  },
}

jest.mock('@/stores', () => ({
  useAgentStore: jest.fn((selector: (s: typeof mockAgentState) => unknown) => selector(mockAgentState)),
  useOperatorStore: jest.fn(() => ({
    tick: jest.fn(),
  })),
}))

jest.mock('@/types/pearl', () => ({
  derivePearlMode: jest.fn(() => 'live'),
  deriveHeadline: jest.fn(() => ({ text: 'Test headline', priority: 'normal' })),
}))

describe('PearlHeaderBar', () => {
  beforeEach(() => {
    history.pushState({}, '', '/')
    jest.mocked(useAgentStore).mockImplementation((selector: any) => selector(mockAgentState))
  })

  it('should render as a status banner', () => {
    render(<PearlHeaderBar />)
    const header = screen.getByRole('banner', { name: /Pearl AI status/i })
    expect(header).toBeInTheDocument()
  })

  it('should include the account switcher', () => {
    render(<PearlHeaderBar />)
    expect(screen.getByTestId('account-switcher')).toBeInTheDocument()
  })

  describe('AI mode display', () => {
    it('should display AI mode in status dot', () => {
      render(<PearlHeaderBar />)
      const statusDot = screen.getByRole('status')
      expect(statusDot).toHaveAttribute('aria-label', expect.stringContaining('live'))
    })

    it('should show shadow mode', () => {
      const { derivePearlMode } = require('@/types/pearl')
      derivePearlMode.mockReturnValue('shadow')
      render(<PearlHeaderBar />)
      const statusDot = screen.getByRole('status')
      expect(statusDot).toHaveAttribute('aria-label', expect.stringContaining('shadow'))
    })

    it('should show disconnected state when AI not available', () => {
      const disconnectedState = {
        ...mockAgentState,
        agentState: { ...mockAgentState.agentState, ai_status: null },
      }
      jest.mocked(useAgentStore).mockImplementation((selector: any) => selector(disconnectedState))
      const { derivePearlMode } = require('@/types/pearl')
      derivePearlMode.mockReturnValue('off')
      render(<PearlHeaderBar />)
      const statusDot = screen.getByRole('status')
      expect(statusDot).toHaveAttribute('aria-label', expect.stringContaining('disconnected'))
    })
  })

  describe('market closed state', () => {
    it('should show Market Closed text', () => {
      const closedState = {
        ...mockAgentState,
        agentState: { ...mockAgentState.agentState, futures_market_open: false },
      }
      jest.mocked(useAgentStore).mockImplementation((selector: any) => selector(closedState))
      render(<PearlHeaderBar />)
      expect(screen.getByText('Market Closed')).toBeInTheDocument()
    })

    it('should update status dot for market closed', () => {
      const closedState = {
        ...mockAgentState,
        agentState: { ...mockAgentState.agentState, futures_market_open: false },
      }
      jest.mocked(useAgentStore).mockImplementation((selector: any) => selector(closedState))
      render(<PearlHeaderBar />)
      const statusDot = screen.getByRole('status')
      expect(statusDot).toHaveAttribute('aria-label', 'Market closed')
    })
  })

  describe('edge cases', () => {
    it('should handle null agent state', () => {
      const nullState = { agentState: null, accounts: null }
      jest.mocked(useAgentStore).mockImplementation((selector: any) => selector(nullState))
      render(<PearlHeaderBar />)
      expect(screen.getByRole('banner')).toBeInTheDocument()
    })

    it('should call operator tick periodically', () => {
      jest.useFakeTimers()
      const mockTick = jest.fn()
      jest.mocked(useOperatorStore).mockImplementation((selector: any) => selector({ tick: mockTick }))
      render(<PearlHeaderBar />)
      jest.advanceTimersByTime(2000)
      expect(mockTick).toHaveBeenCalled()
      jest.useRealTimers()
    })
  })
})
