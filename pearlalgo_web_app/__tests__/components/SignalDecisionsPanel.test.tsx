import React from 'react'
import { render, screen } from '@testing-library/react'
import SignalDecisionsPanel from '@/components/SignalDecisionsPanel'
import type { SignalRejections, LastSignalDecision } from '@/stores'

// Mock DataPanelsContainer
jest.mock('@/components/DataPanelsContainer', () => ({
  DataPanel: ({ children, title }: { children: React.ReactNode; title: string }) => (
    <div data-testid="data-panel" data-title={title}>
      {children}
    </div>
  ),
}))

// Mock formatTime
jest.mock('@/utils/formatting', () => ({
  formatTime: jest.fn((timestamp: string | null) => {
    if (!timestamp) return '—'
    const date = new Date(timestamp)
    return date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })
  }),
}))

describe('SignalDecisionsPanel', () => {
  describe('signal display', () => {
    it('should display last signal decision', () => {
      const lastDecision: LastSignalDecision = {
        signal_type: 'pearlbot_long',
        ml_probability: 0.75,
        action: 'execute',
        reason: 'High confidence',
        timestamp: '2024-01-01T12:00:00Z',
      }

      render(<SignalDecisionsPanel rejections={null} lastDecision={lastDecision} />)

      expect(screen.getByText('Last Signal')).toBeInTheDocument()
      expect(screen.getByText(/Pearlbot Long/i)).toBeInTheDocument()
      expect(screen.getByText(/75%/)).toBeInTheDocument()
      expect(screen.getByText(/Execute/i)).toBeInTheDocument()
    })

    it('should display skipped signal', () => {
      const lastDecision: LastSignalDecision = {
        signal_type: 'short',
        ml_probability: 0.3,
        action: 'skip',
        reason: 'Low confidence',
        timestamp: '2024-01-01T12:00:00Z',
      }

      render(<SignalDecisionsPanel rejections={null} lastDecision={lastDecision} />)

      expect(screen.getByText(/Skip/i)).toBeInTheDocument()
      expect(screen.getByText(/30%/)).toBeInTheDocument()
    })

    it('should format signal type correctly', () => {
      const lastDecision: LastSignalDecision = {
        signal_type: 'direction_gating_block',
        ml_probability: 0.5,
        action: 'execute',
        reason: 'Test',
        timestamp: '2024-01-01T12:00:00Z',
      }

      render(<SignalDecisionsPanel rejections={null} lastDecision={lastDecision} />)

      expect(screen.getByText(/Direction Gating Block/i)).toBeInTheDocument()
    })
  })

  describe('rejection counts', () => {
    it('should display rejection breakdown', () => {
      const rejections: SignalRejections = {
        direction_gating: 10,
        ml_filter: 5,
        circuit_breaker: 3,
        session_filter: 2,
        max_positions: 1,
      }

      render(<SignalDecisionsPanel rejections={rejections} lastDecision={null} />)

      expect(screen.getByText('Rejections (24h)')).toBeInTheDocument()
      expect(screen.getByText('21')).toBeInTheDocument() // Total
      expect(screen.getByText(/Direction Gating/i)).toBeInTheDocument()
      expect(screen.getByText(/10/)).toBeInTheDocument()
    })

    it('should calculate total rejections correctly', () => {
      const rejections: SignalRejections = {
        direction_gating: 5,
        ml_filter: 3,
        circuit_breaker: 2,
        session_filter: 1,
        max_positions: 0,
      }

      render(<SignalDecisionsPanel rejections={rejections} lastDecision={null} />)

      expect(screen.getByText('11')).toBeInTheDocument() // Total: 5+3+2+1+0
    })

    it('should highlight top blocker', () => {
      const rejections: SignalRejections = {
        direction_gating: 20,
        ml_filter: 5,
        circuit_breaker: 3,
        session_filter: 2,
        max_positions: 1,
      }

      render(<SignalDecisionsPanel rejections={rejections} lastDecision={null} />)

      const directionGating = screen.getByText(/Direction Gating.*20/i)
      expect(directionGating).toBeInTheDocument()
    })

    it('should calculate percentages correctly', () => {
      const rejections: SignalRejections = {
        direction_gating: 10,
        ml_filter: 5,
        circuit_breaker: 0,
        session_filter: 0,
        max_positions: 0,
      }

      render(<SignalDecisionsPanel rejections={rejections} lastDecision={null} />)

      // Total is 15, so direction_gating should be ~67%, ml_filter ~33%
      expect(screen.getByText(/67%|33%/)).toBeInTheDocument()
    })
  })

  describe('null data handling', () => {
    it('should handle null rejections', () => {
      render(<SignalDecisionsPanel rejections={null} lastDecision={null} />)

      expect(screen.getByText('No signal data available')).toBeInTheDocument()
    })

    it('should handle null lastDecision', () => {
      const rejections: SignalRejections = {
        direction_gating: 0,
        ml_filter: 0,
        circuit_breaker: 0,
        session_filter: 0,
        max_positions: 0,
      }

      render(<SignalDecisionsPanel rejections={rejections} lastDecision={null} />)

      expect(screen.getByText('No signal data available')).toBeInTheDocument()
    })

    it('should handle zero rejections', () => {
      const rejections: SignalRejections = {
        direction_gating: 0,
        ml_filter: 0,
        circuit_breaker: 0,
        session_filter: 0,
        max_positions: 0,
      }

      render(<SignalDecisionsPanel rejections={rejections} lastDecision={null} />)

      expect(screen.getByText('No signal data available')).toBeInTheDocument()
    })

    it('should handle null timestamp in lastDecision', () => {
      const lastDecision: LastSignalDecision = {
        signal_type: 'long',
        ml_probability: 0.5,
        action: 'execute',
        reason: 'Test',
        timestamp: null,
      }

      render(<SignalDecisionsPanel rejections={null} lastDecision={lastDecision} />)

      expect(screen.getByText('Last Signal')).toBeInTheDocument()
      expect(screen.getByText('—')).toBeInTheDocument()
    })
  })

  describe('edge cases', () => {
    it('should handle very large rejection counts', () => {
      const rejections: SignalRejections = {
        direction_gating: 1000,
        ml_filter: 500,
        circuit_breaker: 250,
        session_filter: 100,
        max_positions: 50,
      }

      render(<SignalDecisionsPanel rejections={rejections} lastDecision={null} />)

      expect(screen.getByText('1900')).toBeInTheDocument()
      expect(screen.getByText(/1000/)).toBeInTheDocument()
    })

    it('should handle single rejection type', () => {
      const rejections: SignalRejections = {
        direction_gating: 10,
        ml_filter: 0,
        circuit_breaker: 0,
        session_filter: 0,
        max_positions: 0,
      }

      render(<SignalDecisionsPanel rejections={rejections} lastDecision={null} />)

      expect(screen.getByText('10')).toBeInTheDocument()
      expect(screen.getByText(/100%/)).toBeInTheDocument() // Only one type
    })

    it('should handle empty signal type string', () => {
      const lastDecision: LastSignalDecision = {
        signal_type: '',
        ml_probability: 0.5,
        action: 'execute',
        reason: 'Test',
        timestamp: '2024-01-01T12:00:00Z',
      }

      render(<SignalDecisionsPanel rejections={null} lastDecision={lastDecision} />)

      expect(screen.getByText(/Unknown/i)).toBeInTheDocument()
    })
  })
})
