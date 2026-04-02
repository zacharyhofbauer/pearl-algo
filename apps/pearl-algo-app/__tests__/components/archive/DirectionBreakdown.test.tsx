import React from 'react'
import { render, screen } from '@testing-library/react'
import DirectionBreakdown from '@/components/archive/DirectionBreakdown'

describe('DirectionBreakdown', () => {
  it('renders "Long" and "Short" labels', () => {
    render(
      <DirectionBreakdown
        directions={{
          long: {
            trades: 10,
            wins: 6,
            total_pnl: 500,
            avg_pnl: 50,
            avg_hold: 30,
            win_rate: 60,
          },
          short: {
            trades: 8,
            wins: 4,
            total_pnl: -200,
            avg_pnl: -25,
            avg_hold: 45,
            win_rate: 50,
          },
        }}
      />
    )
    expect(screen.getByText('Long')).toBeInTheDocument()
    expect(screen.getByText('Short')).toBeInTheDocument()
  })

  it('shows trade counts', () => {
    render(
      <DirectionBreakdown
        directions={{
          long: {
            trades: 15,
            wins: 9,
            total_pnl: 1000,
            avg_pnl: 66,
            avg_hold: 20,
            win_rate: 60,
          },
          short: {
            trades: 12,
            wins: 5,
            total_pnl: -300,
            avg_pnl: -25,
            avg_hold: 35,
            win_rate: 41.7,
          },
        }}
      />
    )
    expect(screen.getByText('15 trades')).toBeInTheDocument()
    expect(screen.getByText('12 trades')).toBeInTheDocument()
  })

  it('shows win rates', () => {
    render(
      <DirectionBreakdown
        directions={{
          long: {
            trades: 10,
            wins: 7,
            total_pnl: 500,
            avg_pnl: 50,
            avg_hold: 30,
            win_rate: 70,
          },
          short: {
            trades: 8,
            wins: 3,
            total_pnl: -100,
            avg_pnl: -12,
            avg_hold: 25,
            win_rate: 37.5,
          },
        }}
      />
    )
    expect(screen.getByText('70% WR')).toBeInTheDocument()
    expect(screen.getByText('37.5% WR')).toBeInTheDocument()
  })

  it('returns null when no directions', () => {
    const { container } = render(
      <DirectionBreakdown directions={{}} />
    )
    expect(container.firstChild).toBeNull()
  })
})
