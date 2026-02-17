import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import LandingPage from '@/app/page'

const mockFetch = global.fetch as jest.Mock

jest.mock('next/image', () => ({
  __esModule: true,
  default: (props: { src: string; alt: string; className?: string }) => (
    <img src={props.src} alt={props.alt} className={props.className} data-testid="hero-image" />
  ),
}))

describe('LandingPage', () => {
  beforeEach(() => {
    mockFetch.mockReset()
  })

  it('renders hero with PEARL Algo heading', () => {
    mockFetch.mockImplementation(() => Promise.reject(new Error('Network error')))
    render(<LandingPage />)
    expect(screen.getByRole('heading', { level: 1, name: /PEARL Algo/i })).toBeInTheDocument()
    expect(screen.getByText('Trading Dashboard')).toBeInTheDocument()
  })

  it('renders both cards with correct hrefs', () => {
    mockFetch.mockImplementation(() => Promise.reject(new Error('Network error')))
    render(<LandingPage />)

    const tvLink = screen.getByRole('link', {
      name: /Tradovate Paper/i,
    })
    expect(tvLink).toHaveAttribute('href', '/dashboard?account=tv_paper')

    const ibkrLink = screen.getByRole('link', {
      name: /IBKR Virtual/i,
    })
    expect(ibkrLink).toHaveAttribute('href', '/archive/ibkr')
  })

  it('renders timeline milestones in order', () => {
    mockFetch.mockImplementation(() => Promise.reject(new Error('Network error')))
    render(<LandingPage />)

    const track = screen.getByRole('list')
    expect(track).toHaveClass('landing-journey-track')

    expect(screen.getByText('Dec 30')).toBeInTheDocument()
    expect(screen.getByText('IBKR inception')).toBeInTheDocument()
    expect(screen.getByText('Feb 3')).toBeInTheDocument()
    expect(screen.getByText('Peak day +$9.5K')).toBeInTheDocument()
    expect(screen.getByText('Feb 12')).toBeInTheDocument()
    expect(screen.getByText('IBKR archived')).toBeInTheDocument()
    expect(screen.getByText('Now')).toBeInTheDocument()
    expect(screen.getByText('TV Paper eval')).toBeInTheDocument()
  })

  it('shows fallback stats when fetch fails', async () => {
    mockFetch.mockImplementation(() => Promise.reject(new Error('Network error')))
    render(<LandingPage />)

    await waitFor(() => {
      expect(screen.getByText('1,573 trades')).toBeInTheDocument()
      expect(screen.getByText('$23,248 P&L')).toBeInTheDocument()
      expect(screen.getByText('15 days')).toBeInTheDocument()
      expect(screen.getByText('EVAL #1')).toBeInTheDocument()
      expect(screen.getByText('50K balance')).toBeInTheDocument()
    })
  })

  it('shows live Tradovate stats when API succeeds', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/state')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              challenge: {
                current_balance: 50123,
                attempt_number: 2,
              },
            }),
        } as Response)
      }
      return Promise.reject(new Error('Not found'))
    })

    render(<LandingPage />)

    await waitFor(() => {
      expect(screen.getByText('EVAL #2')).toBeInTheDocument()
      expect(screen.getByText('50,123 balance')).toBeInTheDocument()
    })
  })

  it('shows live IBKR stats when archive API succeeds', async () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/api/archive/ibkr')) {
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              total_trades: 2000,
              total_pnl: 25000,
              first_trade: '2024-12-30T00:00:00Z',
              last_trade: '2025-02-12T00:00:00Z',
            }),
        } as Response)
      }
      return Promise.reject(new Error('Not found'))
    })

    render(<LandingPage />)

    await waitFor(() => {
      expect(screen.getByText('2,000 trades')).toBeInTheDocument()
      expect(screen.getByText('$25,000 P&L')).toBeInTheDocument()
    })
  })
})
