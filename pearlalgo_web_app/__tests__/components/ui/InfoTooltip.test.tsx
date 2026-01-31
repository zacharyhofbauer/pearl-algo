import { render, screen, fireEvent } from '@testing-library/react'
import { InfoTooltip } from '@/components/ui/InfoTooltip'

describe('InfoTooltip', () => {
  it('renders tooltip icon by default', () => {
    render(<InfoTooltip text="Test tooltip text" />)
    const container = document.querySelector('.info-tooltip-container')
    expect(container).toBeInTheDocument()
    expect(document.querySelector('.info-tooltip-icon')).toBeInTheDocument()
  })

  it('shows tooltip on hover', () => {
    render(<InfoTooltip text="Test tooltip text" />)
    const container = document.querySelector('.info-tooltip-container')

    // Initially tooltip should not be visible
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()

    // Hover to show tooltip
    fireEvent.mouseEnter(container!)
    expect(screen.getByRole('tooltip')).toBeInTheDocument()
    expect(screen.getByText('Test tooltip text')).toBeInTheDocument()

    // Mouse leave to hide tooltip
    fireEvent.mouseLeave(container!)
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('renders with custom children', () => {
    render(
      <InfoTooltip text="Help text">
        <span data-testid="custom-trigger">Custom Trigger</span>
      </InfoTooltip>
    )
    expect(screen.getByTestId('custom-trigger')).toBeInTheDocument()
    expect(screen.getByText('Custom Trigger')).toBeInTheDocument()
  })

  it('applies correct position class', () => {
    const { container: topContainer } = render(<InfoTooltip text="Top tooltip" position="top" />)
    fireEvent.mouseEnter(topContainer.querySelector('.info-tooltip-container')!)
    expect(document.querySelector('.info-tooltip-top')).toBeInTheDocument()
  })

  it('applies bottom position class', () => {
    const { container } = render(<InfoTooltip text="Bottom tooltip" position="bottom" />)
    fireEvent.mouseEnter(container.querySelector('.info-tooltip-container')!)
    expect(document.querySelector('.info-tooltip-bottom')).toBeInTheDocument()
  })

  it('applies left position class', () => {
    const { container } = render(<InfoTooltip text="Left tooltip" position="left" />)
    fireEvent.mouseEnter(container.querySelector('.info-tooltip-container')!)
    expect(document.querySelector('.info-tooltip-left')).toBeInTheDocument()
  })

  it('applies right position class', () => {
    const { container } = render(<InfoTooltip text="Right tooltip" position="right" />)
    fireEvent.mouseEnter(container.querySelector('.info-tooltip-container')!)
    expect(document.querySelector('.info-tooltip-right')).toBeInTheDocument()
  })

  it('defaults to top position', () => {
    const { container } = render(<InfoTooltip text="Default position" />)
    fireEvent.mouseEnter(container.querySelector('.info-tooltip-container')!)
    expect(document.querySelector('.info-tooltip-top')).toBeInTheDocument()
  })
})
