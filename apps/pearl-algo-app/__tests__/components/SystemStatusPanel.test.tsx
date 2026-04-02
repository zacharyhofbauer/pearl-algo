import React from 'react'
import { render, screen } from '@testing-library/react'
import SystemStatusPanel from '@/components/SystemStatusPanel'
import type {
  ExecutionState,
  CircuitBreakerStatus,
  MarketRegime,
  SessionContext,
  ErrorSummary,
} from '@/stores'

// Mock DataPanelsContainer – render children with title for assertions
jest.mock('@/components/DataPanelsContainer', () => ({
  DataPanel: ({ children, title }: { children: React.ReactNode; title: string }) => (
    <div data-testid="data-panel" data-title={title}>
      {children}
    </div>
  ),
}))

// Mock InfoTooltip – render the text for assertions
jest.mock('@/components/ui', () => ({
  InfoTooltip: ({ text }: { text: string }) => (
    <span data-testid="info-tooltip">{text}</span>
  ),
}))

// Mock apiFetch for kill-switch requests
jest.mock('@/lib/api', () => ({
  apiFetch: jest.fn(() =>
    Promise.resolve({ ok: true, text: () => Promise.resolve('{"message":"ok"}') }),
  ),
}))

// Mock useOperatorStore – default to locked
const mockOperatorState = { isUnlocked: false }
jest.mock('@/stores', () => ({
  useOperatorStore: jest.fn((selector: (s: typeof mockOperatorState) => unknown) =>
    selector(mockOperatorState),
  ),
}))

// ---------------------------------------------------------------------------
// Helper – default props factory
// ---------------------------------------------------------------------------

interface PanelProps {
  executionState: ExecutionState | null
  circuitBreaker: CircuitBreakerStatus | null
  marketRegime: MarketRegime | null
  sessionContext: SessionContext | null
  errorSummary: ErrorSummary | null
  isRunning: boolean
  isPaused: boolean
}

const defaultProps: PanelProps = {
  executionState: null,
  circuitBreaker: null,
  marketRegime: null,
  sessionContext: null,
  errorSummary: null,
  isRunning: false,
  isPaused: false,
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('SystemStatusPanel', () => {
  describe('renders without crashing', () => {
    it('renders with all-null / default state', () => {
      const { container } = render(<SystemStatusPanel {...defaultProps} />)
      expect(container).toBeTruthy()
    })

    it('wraps content in the System Status DataPanel', () => {
      render(<SystemStatusPanel {...defaultProps} />)
      const panel = screen.getByTestId('data-panel')
      expect(panel).toHaveAttribute('data-title', 'System Status')
    })
  })

  describe('agent running status', () => {
    it('shows "Offline" when agent is not running', () => {
      render(<SystemStatusPanel {...defaultProps} isRunning={false} />)
      expect(screen.getByText('Offline')).toBeInTheDocument()
    })

    it('shows "Ready" when agent is running with no execution state', () => {
      render(<SystemStatusPanel {...defaultProps} isRunning={true} />)
      expect(screen.getByText('Ready')).toBeInTheDocument()
    })

    it('shows "Paused" when agent is paused', () => {
      render(<SystemStatusPanel {...defaultProps} isRunning={true} isPaused={true} />)
      expect(screen.getByText('Paused')).toBeInTheDocument()
    })

    it('shows "Armed" when execution state is armed', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          executionState={{ enabled: true, armed: true, mode: 'live' }}
        />
      )
      expect(screen.getByText('Armed')).toBeInTheDocument()
    })

    it('shows "Disarmed" when execution state is not armed', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          executionState={{ enabled: true, armed: false, mode: 'live', disarm_reason: 'manual' }}
        />
      )
      expect(screen.getByText('Disarmed')).toBeInTheDocument()
    })
  })

  describe('circuit breaker status', () => {
    it('shows active circuit breaker', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          circuitBreaker={{
            active: true,
            in_cooldown: false,
            trips_today: 0,
          }}
        />
      )
      expect(screen.getByText(/Active/)).toBeInTheDocument()
    })

    it('shows cooldown state with remaining time', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          circuitBreaker={{
            active: true,
            in_cooldown: true,
            cooldown_remaining_seconds: 120,
            trips_today: 1,
          }}
        />
      )
      // "Cooldown" appears in both the readiness badge and circuit breaker chip
      const cooldownMatches = screen.getAllByText(/Cooldown/)
      expect(cooldownMatches.length).toBeGreaterThanOrEqual(1)
      expect(screen.getByText('2m 0s')).toBeInTheDocument()
      expect(screen.getByText('1 trips')).toBeInTheDocument()
    })

    it('shows inactive circuit breaker', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          circuitBreaker={{
            active: false,
            in_cooldown: false,
            trips_today: 0,
          }}
        />
      )
      expect(screen.getByText('Off')).toBeInTheDocument()
    })

    it('shows dash when circuit breaker data is null', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          circuitBreaker={null}
        />
      )

      // The row for "Circuit Breaker" should show "—"
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThanOrEqual(1)
    })
  })

  describe('gateway / execution connection status', () => {
    it('shows execution armed status chip', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          executionState={{ enabled: true, armed: true, mode: 'live' }}
        />
      )
      // "Armed" appears in both the readiness badge and the execution chip
      const armedMatches = screen.getAllByText(/Armed/)
      expect(armedMatches.length).toBeGreaterThanOrEqual(2)
      // The execution chip specifically shows "✓ Armed"
      expect(screen.getByText(/✓ Armed/)).toBeInTheDocument()
    })

    it('shows execution disarmed with disarm reason tooltip', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          executionState={{
            enabled: true,
            armed: false,
            mode: 'live',
            disarm_reason: 'Max loss exceeded',
          }}
        />
      )

      // "Disarmed" appears in both readiness badge and execution chip
      const disarmedMatches = screen.getAllByText(/Disarmed/)
      expect(disarmedMatches.length).toBeGreaterThanOrEqual(2)
      expect(screen.getByText('Max loss exceeded')).toBeInTheDocument()
    })

    it('shows dash when execution state is null', () => {
      render(<SystemStatusPanel {...defaultProps} isRunning={true} />)

      // The "Execution" row should have a "—" chip
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThanOrEqual(1)
    })

    it('shows mode badge for non-live modes', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          executionState={{ enabled: true, armed: true, mode: 'paper' }}
        />
      )
      expect(screen.getByText('PAPER')).toBeInTheDocument()
    })
  })

  describe('handles missing/null data gracefully', () => {
    it('renders all rows with dashes when all data is null', () => {
      render(<SystemStatusPanel {...defaultProps} isRunning={true} />)

      // Multiple "—" chips should be rendered (Execution, Circuit Breaker, Direction)
      const dashes = screen.getAllByText('—')
      expect(dashes.length).toBeGreaterThanOrEqual(3)
    })

    it('shows "None" for errors when errorSummary is null', () => {
      render(<SystemStatusPanel {...defaultProps} isRunning={true} />)

      // Error row falls back to "✓ None"
      expect(screen.getByText(/None/)).toBeInTheDocument()
    })

    it('shows error count when errors are present', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          errorSummary={{
            session_error_count: 3,
            last_error: 'Connection timeout',
            last_error_time: '2025-06-01T12:00:00Z',
          }}
        />
      )

      expect(screen.getByText(/3 Errors/)).toBeInTheDocument()
    })

    it('shows session label when session context is provided', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          sessionContext={{
            current_session: 'morning',
            session_pnl: 0,
            session_trades: 0,
            session_wins: 0,
          }}
        />
      )

      expect(screen.getByText('Morning')).toBeInTheDocument()
    })

    it('shows direction restriction when market regime is provided', () => {
      render(
        <SystemStatusPanel
          {...defaultProps}
          isRunning={true}
          marketRegime={{
            regime: 'bullish',
            confidence: 0.8,
            allowed_direction: 'long',
          }}
        />
      )

      expect(screen.getByText(/Long Only/)).toBeInTheDocument()
    })
  })
})
