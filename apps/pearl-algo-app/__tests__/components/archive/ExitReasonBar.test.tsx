import React from 'react'
import { render, screen } from '@testing-library/react'
import ExitReasonBar from '@/components/archive/ExitReasonBar'

describe('ExitReasonBar', () => {
  it('renders exit reason labels from data', () => {
    render(
      <ExitReasonBar
        reasons={[
          { reason: 'take_profit', count: 30 },
          { reason: 'stop_loss', count: 20 },
        ]}
        total={50}
      />
    )
    expect(screen.getByText('Take Profit')).toBeInTheDocument()
    expect(screen.getByText('Stop Loss')).toBeInTheDocument()
  })

  it('shows percentage for each reason', () => {
    render(
      <ExitReasonBar
        reasons={[
          { reason: 'take_profit', count: 25 },
          { reason: 'stop_loss', count: 75 },
        ]}
        total={100}
      />
    )
    const segments = document.querySelectorAll('.exit-reason-segment')
    expect(segments.length).toBe(2)
    expect(segments[0]).toHaveAttribute(
      'title',
      expect.stringContaining('25.0%')
    )
    expect(segments[1]).toHaveAttribute(
      'title',
      expect.stringContaining('75.0%')
    )
  })

  it('returns null when reasons empty or total is 0', () => {
    const { container: c1 } = render(
      <ExitReasonBar reasons={[]} total={100} />
    )
    expect(c1.firstChild).toBeNull()

    const { container: c2 } = render(
      <ExitReasonBar
        reasons={[{ reason: 'take_profit', count: 10 }]}
        total={0}
      />
    )
    expect(c2.firstChild).toBeNull()
  })
})
