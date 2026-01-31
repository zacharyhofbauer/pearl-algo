import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import { ErrorBoundary, PanelErrorBoundary, withErrorBoundary } from '@/components/ErrorBoundary'

// Component that throws an error
const ThrowError = ({ shouldThrow }: { shouldThrow: boolean }) => {
  if (shouldThrow) {
    throw new Error('Test error')
  }
  return <div>No error</div>
}

// Suppress console.error for cleaner test output
const originalError = console.error
beforeAll(() => {
  console.error = jest.fn()
})
afterAll(() => {
  console.error = originalError
})

describe('ErrorBoundary', () => {
  it('should render children when no error', () => {
    render(
      <ErrorBoundary panelName="Test">
        <div>Child content</div>
      </ErrorBoundary>
    )

    expect(screen.getByText('Child content')).toBeInTheDocument()
  })

  it('should render fallback when error occurs', () => {
    render(
      <ErrorBoundary panelName="Test Panel">
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(screen.getByText('Test Panel Error')).toBeInTheDocument()
    expect(screen.getByText('Test error')).toBeInTheDocument()
  })

  it('should render custom fallback when provided', () => {
    render(
      <ErrorBoundary
        panelName="Test"
        fallback={<div>Custom error message</div>}
      >
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(screen.getByText('Custom error message')).toBeInTheDocument()
  })

  it('should have a Try Again button', () => {
    render(
      <ErrorBoundary panelName="Test">
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    )

    // Error should be shown
    expect(screen.getByText('Test Error')).toBeInTheDocument()

    // Try Again button should be present
    const retryButton = screen.getByText('Try Again')
    expect(retryButton).toBeInTheDocument()
  })

  it('should call onError handler when error occurs', () => {
    const onError = jest.fn()

    render(
      <ErrorBoundary panelName="Test" onError={onError}>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(onError).toHaveBeenCalledTimes(1)
    expect(onError).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        componentStack: expect.any(String),
      })
    )
  })

  it('should show "Something went wrong" when no panelName', () => {
    render(
      <ErrorBoundary>
        <ThrowError shouldThrow={true} />
      </ErrorBoundary>
    )

    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
  })
})

describe('PanelErrorBoundary', () => {
  it('should render children when no error', () => {
    render(
      <PanelErrorBoundary title="Performance" icon="📊">
        <div>Panel content</div>
      </PanelErrorBoundary>
    )

    expect(screen.getByText('Panel content')).toBeInTheDocument()
  })

  it('should show error state when error occurs', () => {
    render(
      <PanelErrorBoundary title="Analytics" icon="📈">
        <ThrowError shouldThrow={true} />
      </PanelErrorBoundary>
    )

    expect(screen.getByText('Analytics')).toBeInTheDocument()
    expect(screen.getByText('Failed to load')).toBeInTheDocument()
  })

  it('should render panel with icon when provided', () => {
    render(
      <PanelErrorBoundary title="Test Panel" icon="🎯">
        <ThrowError shouldThrow={true} />
      </PanelErrorBoundary>
    )

    expect(screen.getByText('🎯')).toBeInTheDocument()
  })
})

describe('withErrorBoundary HOC', () => {
  it('should wrap component with error boundary', () => {
    const TestComponent = () => <div>Test component</div>
    const WrappedComponent = withErrorBoundary(TestComponent, 'Test')

    render(<WrappedComponent />)

    expect(screen.getByText('Test component')).toBeInTheDocument()
  })

  it('should catch errors in wrapped component', () => {
    const ErrorComponent = () => {
      throw new Error('HOC error test')
    }
    const WrappedComponent = withErrorBoundary(ErrorComponent, 'HOC Test')

    render(<WrappedComponent />)

    expect(screen.getByText('HOC Test Error')).toBeInTheDocument()
  })

  it('should pass props to wrapped component', () => {
    const TestComponent = ({ message }: { message: string }) => <div>{message}</div>
    const WrappedComponent = withErrorBoundary(TestComponent, 'Props Test')

    render(<WrappedComponent message="Hello from props" />)

    expect(screen.getByText('Hello from props')).toBeInTheDocument()
  })

  it('should set displayName on wrapped component', () => {
    const TestComponent = () => <div>Test</div>
    TestComponent.displayName = 'MyTestComponent'

    const WrappedComponent = withErrorBoundary(TestComponent, 'Test')

    expect(WrappedComponent.displayName).toBe('withErrorBoundary(MyTestComponent)')
  })
})
