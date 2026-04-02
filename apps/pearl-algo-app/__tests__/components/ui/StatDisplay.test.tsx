import { render, screen } from '@testing-library/react'
import { StatDisplay } from '@/components/ui/StatDisplay'

describe('StatDisplay', () => {
  it('renders label and value', () => {
    render(<StatDisplay label="P&L" value="$100.00" />)
    expect(screen.getByText('P&L')).toBeInTheDocument()
    expect(screen.getByText('$100.00')).toBeInTheDocument()
  })

  it('renders with default variant class', () => {
    const { container } = render(<StatDisplay label="Test" value="Value" />)
    expect(container.querySelector('.stat-display-default')).toBeInTheDocument()
  })

  it('renders compact variant', () => {
    const { container } = render(<StatDisplay label="Test" value="Value" variant="compact" />)
    expect(container.querySelector('.stat-display-compact')).toBeInTheDocument()
  })

  it('renders inline variant', () => {
    const { container } = render(<StatDisplay label="Test" value="Value" variant="inline" />)
    expect(container.querySelector('.stat-display-inline')).toBeInTheDocument()
  })

  it('applies fullWidth class', () => {
    const { container } = render(<StatDisplay label="Test" value="Value" fullWidth />)
    expect(container.querySelector('.stat-display-full')).toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<StatDisplay label="Test" value="Value" className="custom-class" />)
    expect(container.querySelector('.custom-class')).toBeInTheDocument()
  })

  describe('colorMode: financial', () => {
    it('applies profit class when positive', () => {
      const { container } = render(
        <StatDisplay label="P&L" value="$100" colorMode="financial" positive />
      )
      expect(container.querySelector('.stat-value-profit')).toBeInTheDocument()
    })

    it('applies loss class when negative', () => {
      const { container } = render(
        <StatDisplay label="P&L" value="-$50" colorMode="financial" negative />
      )
      expect(container.querySelector('.stat-value-loss')).toBeInTheDocument()
    })
  })

  describe('colorMode: status', () => {
    it('applies ok class', () => {
      const { container } = render(
        <StatDisplay label="Status" value="Online" colorMode="status" status="ok" />
      )
      expect(container.querySelector('.stat-value-ok')).toBeInTheDocument()
    })

    it('applies warning class', () => {
      const { container } = render(
        <StatDisplay label="Status" value="Degraded" colorMode="status" status="warning" />
      )
      expect(container.querySelector('.stat-value-warning')).toBeInTheDocument()
    })

    it('applies error class', () => {
      const { container } = render(
        <StatDisplay label="Status" value="Offline" colorMode="status" status="error" />
      )
      expect(container.querySelector('.stat-value-error')).toBeInTheDocument()
    })

    it('applies inactive class', () => {
      const { container } = render(
        <StatDisplay label="Status" value="N/A" colorMode="status" status="inactive" />
      )
      expect(container.querySelector('.stat-value-inactive')).toBeInTheDocument()
    })
  })

  describe('colorMode: default', () => {
    it('applies positive class when positive', () => {
      const { container } = render(
        <StatDisplay label="Score" value="100" positive />
      )
      expect(container.querySelector('.stat-value-positive')).toBeInTheDocument()
    })

    it('applies negative class when negative', () => {
      const { container } = render(
        <StatDisplay label="Score" value="-50" negative />
      )
      expect(container.querySelector('.stat-value-negative')).toBeInTheDocument()
    })
  })

  it('renders tooltip when provided', () => {
    render(<StatDisplay label="Metric" value="100" tooltip="Help text" />)
    expect(document.querySelector('.info-tooltip-container')).toBeInTheDocument()
  })

  it('does not render tooltip when not provided', () => {
    render(<StatDisplay label="Metric" value="100" />)
    expect(document.querySelector('.info-tooltip-container')).not.toBeInTheDocument()
  })

  it('renders subtext when provided', () => {
    render(<StatDisplay label="Balance" value="$1000" subtext="Updated 5m ago" />)
    expect(screen.getByText('Updated 5m ago')).toBeInTheDocument()
    expect(document.querySelector('.stat-display-subtext')).toBeInTheDocument()
  })

  it('renders ReactNode as value', () => {
    render(
      <StatDisplay
        label="W/L"
        value={<><span className="wins">5</span>/<span className="losses">2</span></>}
      />
    )
    expect(document.querySelector('.wins')).toBeInTheDocument()
    expect(document.querySelector('.losses')).toBeInTheDocument()
  })
})
