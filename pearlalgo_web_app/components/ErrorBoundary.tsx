'use client'

import React, { Component, ReactNode } from 'react'

interface ErrorBoundaryProps {
  children: ReactNode
  fallback?: ReactNode
  onError?: (error: Error, errorInfo: React.ErrorInfo) => void
  panelName?: string
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
  errorInfo: React.ErrorInfo | null
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    }
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo): void {
    this.setState({ errorInfo })

    // Log error for debugging
    console.error(`[ErrorBoundary${this.props.panelName ? ` - ${this.props.panelName}` : ''}]`, error, errorInfo)

    // Call optional error handler
    this.props.onError?.(error, errorInfo)
  }

  handleRetry = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    })
  }

  render(): ReactNode {
    if (this.state.hasError) {
      // Custom fallback provided
      if (this.props.fallback) {
        return this.props.fallback
      }

      // Default error UI
      return (
        <div className="error-boundary-fallback">
          <div className="error-boundary-icon">⚠️</div>
          <div className="error-boundary-title">
            {this.props.panelName ? `${this.props.panelName} Error` : 'Something went wrong'}
          </div>
          <div className="error-boundary-message">
            {this.state.error?.message || 'An unexpected error occurred'}
          </div>
          <button
            className="error-boundary-retry"
            onClick={this.handleRetry}
          >
            Try Again
          </button>
        </div>
      )
    }

    return this.props.children
  }
}

// HOC for wrapping components with error boundary
export function withErrorBoundary<P extends object>(
  WrappedComponent: React.ComponentType<P>,
  panelName?: string
): React.FC<P> {
  const WithErrorBoundary: React.FC<P> = (props) => (
    <ErrorBoundary panelName={panelName}>
      <WrappedComponent {...props} />
    </ErrorBoundary>
  )

  WithErrorBoundary.displayName = `withErrorBoundary(${WrappedComponent.displayName || WrappedComponent.name || 'Component'})`

  return WithErrorBoundary
}

// Panel-specific error boundary with consistent styling
interface PanelErrorBoundaryProps {
  children: ReactNode
  title: string
}

export function PanelErrorBoundary({ children, title }: PanelErrorBoundaryProps): JSX.Element {
  return (
    <ErrorBoundary
      panelName={title}
      fallback={
        <div className="data-panel error-panel">
          <div className="panel-header">
            <span className="panel-title">{title}</span>
          </div>
          <div className="panel-content">
            <div className="error-boundary-fallback compact">
              <span className="error-boundary-icon">⚠️</span>
              <span className="error-boundary-message">Failed to load</span>
            </div>
          </div>
        </div>
      }
    >
      {children}
    </ErrorBoundary>
  )
}

export default ErrorBoundary
