import React from 'react'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import PearlHeaderBar from '@/components/PearlHeaderBar'
import { useAgentStore, useOperatorStore } from '@/stores'

// Mock Next.js Image
jest.mock('next/image', () => ({
  __esModule: true,
  default: ({ src, alt, width, height }: { src: string; alt: string; width: number; height: number }) => (
    <img src={src} alt={alt} width={width} height={height} />
  ),
}))

// Mock PearlInsightsPanel
jest.mock('@/components/PearlInsightsPanel', () => ({
  __esModule: true,
  default: ({ layout }: { layout: string }) => <div data-testid="pearl-insights-panel">Pearl Insights ({layout})</div>,
}))

// Mock AccountSwitcher
jest.mock('@/components/AccountSwitcher', () => ({
  __esModule: true,
  default: () => <div data-testid="account-switcher">Account Switcher</div>,
}))

// Mock stores
const mockAgentState = {
  agentState: {
    running: true,
    futures_market_open: true,
    pearl_ai_available: true,
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

// Mock derivePearlMode and deriveHeadline
jest.mock('@/types/pearl', () => ({
  derivePearlMode: jest.fn(() => 'live'),
  deriveHeadline: jest.fn(() => ({ text: 'Test headline', priority: 'normal' })),
}))

describe('PearlHeaderBar', () => {
  beforeEach(() => {
    // Reset window.location.search
    delete (window as any).location
    window.location = { ...window.location, search: '' }
  })

  describe('expanded/collapsed state', () => {
    it('should render collapsed by default', () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toHaveAttribute('aria-expanded', 'false')
    })

    it('should expand on click', () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      fireEvent.click(header)

      expect(header).toHaveAttribute('aria-expanded', 'true')
    })

    it('should collapse when clicking again', () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      fireEvent.click(header)
      expect(header).toHaveAttribute('aria-expanded', 'true')

      fireEvent.click(header)
      expect(header).toHaveAttribute('aria-expanded', 'false')
    })

    it('should collapse on outside click', async () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      fireEvent.click(header)
      expect(header).toHaveAttribute('aria-expanded', 'true')

      fireEvent.mouseDown(document.body)

      await waitFor(() => {
        expect(header).toHaveAttribute('aria-expanded', 'false')
      })
    })

    it('should collapse on Escape key', () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      fireEvent.click(header)
      expect(header).toHaveAttribute('aria-expanded', 'true')

      fireEvent.keyDown(document, { key: 'Escape' })

      expect(header).toHaveAttribute('aria-expanded', 'false')
    })
  })

  describe('AI mode display', () => {
    it('should display AI mode in status dot', () => {
      render(<PearlHeaderBar />)

      const statusDot = screen.getByRole('status')
      expect(statusDot).toHaveAttribute('aria-label', expect.stringContaining('live'))
    })

    it('should show shadow mode', () => {
      const shadowState = {
        ...mockAgentState,
        agentState: {
          ...mockAgentState.agentState,
          ai_status: {
            ...mockAgentState.agentState.ai_status!,
            bandit_mode: 'shadow',
            contextual_mode: 'shadow',
          },
        },
      }

      jest.mocked(useAgentStore).mockImplementation((selector) => selector(shadowState as any))

      const { derivePearlMode } = require('@/types/pearl')
      derivePearlMode.mockReturnValue('shadow')

      render(<PearlHeaderBar />)

      const statusDot = screen.getByRole('status')
      expect(statusDot).toHaveAttribute('aria-label', expect.stringContaining('shadow'))
    })

    it('should show disconnected state when AI not available', () => {
      const disconnectedState = {
        ...mockAgentState,
        agentState: {
          ...mockAgentState.agentState,
          pearl_ai_available: false,
          ai_status: null,
        },
      }

      jest.mocked(useAgentStore).mockImplementation((selector) => selector(disconnectedState as any))

      const { derivePearlMode } = require('@/types/pearl')
      derivePearlMode.mockReturnValue('off')

      render(<PearlHeaderBar />)

      const statusDot = screen.getByRole('status')
      expect(statusDot).toHaveAttribute('aria-label', expect.stringContaining('disconnected'))
    })
  })

  describe('keyboard navigation', () => {
    it('should toggle on Enter key', () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toHaveAttribute('aria-expanded', 'false')

      fireEvent.keyDown(header, { key: 'Enter' })

      expect(header).toHaveAttribute('aria-expanded', 'true')
    })

    it('should toggle on Space key', () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toHaveAttribute('aria-expanded', 'false')

      fireEvent.keyDown(header, { key: ' ' })

      expect(header).toHaveAttribute('aria-expanded', 'true')
    })

    it('should have correct tabIndex for keyboard access', () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toHaveAttribute('tabIndex', '0')
    })
  })

  describe('account name display', () => {
    it('should display default account name', () => {
      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toHaveAttribute('aria-label', expect.stringContaining('IBKR Virtual'))
    })

    it('should display account name from URL parameter', () => {
      window.location.search = '?account=tv_paper'

      const tvPaperState = {
        ...mockAgentState,
        accounts: {
          ...mockAgentState.accounts,
          tv_paper: { display_name: 'TV Paper', badge: 'PAPER', badge_color: '#ffc107', telegram_prefix: '', description: '' },
        },
      }

      jest.mocked(useAgentStore).mockImplementation((selector) => selector(tvPaperState as any))

      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toHaveAttribute('aria-label', expect.stringContaining('TV Paper'))
    })

    it('should fallback to Pearl AI when account not found', () => {
      window.location.search = '?account=unknown'

      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toHaveAttribute('aria-label', expect.stringContaining('Pearl AI'))
    })
  })

  describe('market closed state', () => {
    it('should show Market Closed when market is closed', () => {
      const closedState = {
        ...mockAgentState,
        agentState: {
          ...mockAgentState.agentState,
          futures_market_open: false,
        },
      }

      jest.mocked(useAgentStore).mockImplementation((selector) => selector(closedState as any))

      render(<PearlHeaderBar />)

      expect(screen.getByText('Market Closed')).toBeInTheDocument()
    })

    it('should update status dot for market closed', () => {
      const closedState = {
        ...mockAgentState,
        agentState: {
          ...mockAgentState.agentState,
          futures_market_open: false,
        },
      }

      jest.mocked(useAgentStore).mockImplementation((selector) => selector(closedState as any))

      render(<PearlHeaderBar />)

      const statusDot = screen.getByRole('status')
      expect(statusDot).toHaveAttribute('aria-label', 'Market closed')
    })
  })

  describe('edge cases', () => {
    it('should handle null agent state', () => {
      const nullState = {
        agentState: null,
        accounts: null,
      }

      jest.mocked(useAgentStore).mockImplementation((selector) => selector(nullState as any))

      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toBeInTheDocument()
    })

    it('should handle empty pearl feed', () => {
      const emptyFeedState = {
        ...mockAgentState,
        agentState: {
          ...mockAgentState.agentState,
          pearl_feed: [],
        },
      }

      jest.mocked(useAgentStore).mockImplementation((selector) => selector(emptyFeedState as any))

      render(<PearlHeaderBar />)

      const header = screen.getByRole('button')
      expect(header).toBeInTheDocument()
    })

    it('should call operator tick periodically', () => {
      jest.useFakeTimers()
      const mockTick = jest.fn()

      jest.mocked(useOperatorStore).mockReturnValue({
        tick: mockTick,
      } as any)

      render(<PearlHeaderBar />)

      jest.advanceTimersByTime(2000)

      expect(mockTick).toHaveBeenCalled()

      jest.useRealTimers()
    })
  })
})
