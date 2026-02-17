import React from 'react'
import { render, screen } from '@testing-library/react'
import StatsCards from '@/components/archive/StatsCards'

describe('StatsCards', () => {
  it('renders P&L stat (formatted as dollar)', () => {
    render(
      <StatsCards
        totalPnl={12500}
        totalTrades={100}
        winRate={62.5}
      />
    )
    expect(screen.getByText('Total P&L')).toBeInTheDocument()
    expect(screen.getByText('+$12,500')).toBeInTheDocument()
  })

  it('renders total trades count', () => {
    render(
      <StatsCards
        totalPnl={0}
        totalTrades={250}
        winRate={50}
      />
    )
    expect(screen.getByText('Trades')).toBeInTheDocument()
    expect(screen.getByText('250')).toBeInTheDocument()
  })

  it('renders win rate as percentage', () => {
    render(
      <StatsCards
        totalPnl={0}
        totalTrades={0}
        winRate={68.3}
      />
    )
    expect(screen.getByText('Win Rate')).toBeInTheDocument()
    expect(screen.getByText('68.3%')).toBeInTheDocument()
  })

  it('shows em-dash for null values', () => {
    render(
      <StatsCards
        totalPnl={0}
        totalTrades={0}
        winRate={0}
        profitFactor={undefined}
        expectancy={undefined}
        avgHoldMinutes={undefined}
      />
    )
    const dashes = screen.getAllByText('—')
    expect(dashes.length).toBeGreaterThanOrEqual(3)
  })
})
