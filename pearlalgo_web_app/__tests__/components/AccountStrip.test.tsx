import React from 'react'
import { render, screen } from '@testing-library/react'
import AccountStrip from '@/components/AccountStrip'

describe('AccountStrip', () => {
  it('renders all 5 stat labels (Equity, Today, Total P&L, Trades, Win Rate)', () => {
    render(
      <AccountStrip
        balance={52856.7}
        totalPnl={1000}
        dailyPnl={50}
        trades={42}
        winRate={65.5}
      />
    )
    expect(screen.getByText('Equity')).toBeInTheDocument()
    expect(screen.getByText('Today')).toBeInTheDocument()
    expect(screen.getByText('Total P&L')).toBeInTheDocument()
    expect(screen.getByText('Trades')).toBeInTheDocument()
    expect(screen.getByText('Win Rate')).toBeInTheDocument()
  })

  it('formats positive balance correctly ($52,856.70)', () => {
    render(
      <AccountStrip
        balance={52856.7}
        totalPnl={0}
        dailyPnl={0}
        trades={0}
        winRate={0}
      />
    )
    expect(screen.getByText('$52,856.70')).toBeInTheDocument()
  })

  it('formats negative daily P&L with sign (-$645.91)', () => {
    render(
      <AccountStrip
        balance={10000}
        totalPnl={0}
        dailyPnl={-645.91}
        trades={0}
        winRate={0}
      />
    )
    expect(screen.getByText('-$645.91')).toBeInTheDocument()
  })

  it('shows em-dash when values are null', () => {
    render(
      <AccountStrip
        balance={null}
        totalPnl={null}
        dailyPnl={null}
        trades={null}
        winRate={null}
      />
    )
    const dashes = screen.getAllByText('\u2014')
    expect(dashes.length).toBeGreaterThanOrEqual(5)
  })

  it('adds tint-positive class when dailyPnl >= 0', () => {
    const { container } = render(
      <AccountStrip
        balance={10000}
        totalPnl={0}
        dailyPnl={100}
        trades={0}
        winRate={0}
      />
    )
    const strip = container.querySelector('.account-strip')
    expect(strip).toHaveClass('tint-positive')
  })

  it('adds tint-negative class when dailyPnl < 0', () => {
    const { container } = render(
      <AccountStrip
        balance={10000}
        totalPnl={0}
        dailyPnl={-50}
        trades={0}
        winRate={0}
      />
    )
    const strip = container.querySelector('.account-strip')
    expect(strip).toHaveClass('tint-negative')
  })
})
