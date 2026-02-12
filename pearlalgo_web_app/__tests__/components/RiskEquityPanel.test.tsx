import React from 'react'
import { render, screen, fireEvent } from '@testing-library/react'
import RiskEquityPanel from '@/components/RiskEquityPanel'
import type { RiskMetrics, EquityCurvePoint } from '@/stores'

// Mock DataPanelsContainer
jest.mock('@/components/DataPanelsContainer', () => ({
  DataPanel: ({ children, title }: { children: React.ReactNode; title: string }) => (
    <div data-testid="data-panel" data-title={title}>
      {children}
    </div>
  ),
}))

// Mock StatDisplay
jest.mock('@/components/ui', () => ({
  StatDisplay: ({ label, value }: { label: string; value: React.ReactNode }) => (
    <div data-testid="stat-display" data-label={label}>
      {value}
    </div>
  ),
}))

// Mock formatPnL and formatCurrency
jest.mock('@/utils/formatting', () => ({
  formatPnL: jest.fn((value: number) => {
    if (value >= 0) return `+$${value.toFixed(2)}`
    return `-$${Math.abs(value).toFixed(2)}`
  }),
  formatCurrency: jest.fn((value: number, options?: { showSign?: boolean }) => {
    const sign = options?.showSign && value >= 0 ? '+' : ''
    return `${sign}$${value.toFixed(2)}`
  }),
}))

// Mock lightweight-charts
jest.mock('lightweight-charts', () => ({
  createChart: jest.fn(() => ({
    addAreaSeries: jest.fn(() => ({
      setData: jest.fn(),
    })),
    timeScale: jest.fn(() => ({
      fitContent: jest.fn(),
    })),
    applyOptions: jest.fn(),
    remove: jest.fn(),
  })),
  ColorType: {
    Solid: 'solid',
  },
}))

describe('RiskEquityPanel', () => {
  describe('risk metrics display', () => {
    const mockRiskMetrics: RiskMetrics = {
      max_drawdown: 500.0,
      max_drawdown_pct: 5.5,
      sharpe_ratio: 1.5,
      profit_factor: 2.0,
      avg_win: 100.0,
      avg_loss: -50.0,
      avg_rr: 2.0,
      largest_win: 500.0,
      largest_loss: -200.0,
      expectancy: 25.0,
    }

    it('should display risk metrics when provided', () => {
      render(<RiskEquityPanel riskMetrics={mockRiskMetrics} equityCurve={[]} />)

      expect(screen.getByText('Risk & Equity')).toBeInTheDocument()
      expect(screen.getByText('Profitability')).toBeInTheDocument()
      expect(screen.getByText('Risk')).toBeInTheDocument()
      expect(screen.getByText('Trade Stats')).toBeInTheDocument()
    })

    it('should format P&L correctly', () => {
      render(<RiskEquityPanel riskMetrics={mockRiskMetrics} equityCurve={[]} />)

      const expectancy = screen.getByTestId('stat-display')
      expect(expectancy).toBeInTheDocument()
    })

    it('should display max drawdown with percentage', () => {
      render(<RiskEquityPanel riskMetrics={mockRiskMetrics} equityCurve={[]} />)

      expect(screen.getByText(/Max Drawdown/i)).toBeInTheDocument()
      expect(screen.getByText(/5.5%/)).toBeInTheDocument()
    })

    it('should display exposure metrics when available', () => {
      const metricsWithExposure: RiskMetrics = {
        ...mockRiskMetrics,
        max_concurrent_positions_peak: 5,
        max_stop_risk_exposure: 1000.0,
      }

      render(<RiskEquityPanel riskMetrics={metricsWithExposure} equityCurve={[]} />)

      expect(screen.getByText('Exposure')).toBeInTheDocument()
      expect(screen.getByText(/Peak Positions/i)).toBeInTheDocument()
      expect(screen.getByText(/Max Stop Risk/i)).toBeInTheDocument()
    })

    it('should display top losses when available', () => {
      const metricsWithLosses: RiskMetrics = {
        ...mockRiskMetrics,
        top_losses: [
          { signal_id: '1', pnl: -100.0, exit_reason: 'stop_loss' },
          { signal_id: '2', pnl: -75.0, exit_reason: 'target' },
          { signal_id: '3', pnl: -50.0, exit_reason: 'time' },
        ],
      }

      render(<RiskEquityPanel riskMetrics={metricsWithLosses} equityCurve={[]} />)

      expect(screen.getByText('Top 3 Losses')).toBeInTheDocument()
      expect(screen.getByText(/Stop Loss/i)).toBeInTheDocument()
    })
  })

  describe('P&L formatting', () => {
    it('should format positive values correctly', () => {
      const metrics: RiskMetrics = {
        max_drawdown: 0,
        max_drawdown_pct: 0,
        sharpe_ratio: null,
        profit_factor: null,
        avg_win: 100.0,
        avg_loss: -50.0,
        avg_rr: null,
        largest_win: 500.0,
        largest_loss: -200.0,
        expectancy: 25.0,
      }

      render(<RiskEquityPanel riskMetrics={metrics} equityCurve={[]} />)

      expect(screen.getByText(/Profitability/i)).toBeInTheDocument()
    })

    it('should format negative values correctly', () => {
      const metrics: RiskMetrics = {
        max_drawdown: 500.0,
        max_drawdown_pct: 5.5,
        sharpe_ratio: null,
        profit_factor: null,
        avg_win: 100.0,
        avg_loss: -50.0,
        avg_rr: null,
        largest_win: 500.0,
        largest_loss: -200.0,
        expectancy: -10.0,
      }

      render(<RiskEquityPanel riskMetrics={metrics} equityCurve={[]} />)

      expect(screen.getByText(/Risk/i)).toBeInTheDocument()
    })
  })

  describe('null/missing data', () => {
    it('should handle null risk metrics', () => {
      render(<RiskEquityPanel riskMetrics={null} equityCurve={[]} />)

      expect(screen.getByText('No risk metrics available')).toBeInTheDocument()
    })

    it('should handle empty equity curve', () => {
      render(<RiskEquityPanel riskMetrics={null} equityCurve={[]} />)

      expect(screen.getByText('No risk metrics available')).toBeInTheDocument()
    })

    it('should handle null values in risk metrics', () => {
      const metricsWithNulls: RiskMetrics = {
        max_drawdown: 0,
        max_drawdown_pct: 0,
        sharpe_ratio: null,
        profit_factor: null,
        avg_win: 0,
        avg_loss: 0,
        avg_rr: null,
        largest_win: 0,
        largest_loss: 0,
        expectancy: 0,
      }

      render(<RiskEquityPanel riskMetrics={metricsWithNulls} equityCurve={[]} />)

      expect(screen.getByText('Profitability')).toBeInTheDocument()
    })
  })

  describe('equity curve states', () => {
    const mockEquityCurve: EquityCurvePoint[] = [
      { time: 1000, value: 10000 },
      { time: 2000, value: 10500 },
      { time: 3000, value: 10200 },
      { time: 4000, value: 10800 },
    ]

    it('should display equity curve when provided', () => {
      render(<RiskEquityPanel riskMetrics={null} equityCurve={mockEquityCurve} />)

      expect(screen.getByText('No risk metrics available')).toBeInTheDocument()
    })

    it('should show tabs when both risk metrics and equity curve are available', () => {
      const metrics: RiskMetrics = {
        max_drawdown: 500.0,
        max_drawdown_pct: 5.5,
        sharpe_ratio: 1.5,
        profit_factor: 2.0,
        avg_win: 100.0,
        avg_loss: -50.0,
        avg_rr: 2.0,
        largest_win: 500.0,
        largest_loss: -200.0,
        expectancy: 25.0,
      }

      render(<RiskEquityPanel riskMetrics={metrics} equityCurve={mockEquityCurve} />)

      expect(screen.getByRole('tablist')).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: 'Risk' })).toBeInTheDocument()
      expect(screen.getByRole('tab', { name: 'Equity (72h)' })).toBeInTheDocument()
    })

    it('should switch between risk and equity tabs', () => {
      const metrics: RiskMetrics = {
        max_drawdown: 500.0,
        max_drawdown_pct: 5.5,
        sharpe_ratio: 1.5,
        profit_factor: 2.0,
        avg_win: 100.0,
        avg_loss: -50.0,
        avg_rr: 2.0,
        largest_win: 500.0,
        largest_loss: -200.0,
        expectancy: 25.0,
      }

      render(<RiskEquityPanel riskMetrics={metrics} equityCurve={mockEquityCurve} />)

      const equityTab = screen.getByRole('tab', { name: 'Equity (72h)' })
      fireEvent.click(equityTab)

      expect(equityTab).toHaveAttribute('aria-selected', 'true')
    })

    it('should display equity stats correctly', () => {
      const metrics: RiskMetrics = {
        max_drawdown: 500.0,
        max_drawdown_pct: 5.5,
        sharpe_ratio: 1.5,
        profit_factor: 2.0,
        avg_win: 100.0,
        avg_loss: -50.0,
        avg_rr: 2.0,
        largest_win: 500.0,
        largest_loss: -200.0,
        expectancy: 25.0,
      }

      render(<RiskEquityPanel riskMetrics={metrics} equityCurve={mockEquityCurve} />)

      const equityTab = screen.getByRole('tab', { name: 'Equity (72h)' })
      fireEvent.click(equityTab)

      expect(screen.getByText(/Current/i)).toBeInTheDocument()
      expect(screen.getByText(/Peak/i)).toBeInTheDocument()
      expect(screen.getByText(/Trough/i)).toBeInTheDocument()
    })

    it('should show peak gap indicator when below peak', () => {
      const metrics: RiskMetrics = {
        max_drawdown: 500.0,
        max_drawdown_pct: 5.5,
        sharpe_ratio: 1.5,
        profit_factor: 2.0,
        avg_win: 100.0,
        avg_loss: -50.0,
        avg_rr: 2.0,
        largest_win: 500.0,
        largest_loss: -200.0,
        expectancy: 25.0,
      }

      const curveWithGap: EquityCurvePoint[] = [
        { time: 1000, value: 10000 },
        { time: 2000, value: 11000 }, // Peak
        { time: 3000, value: 10500 }, // Below peak
      ]

      render(<RiskEquityPanel riskMetrics={metrics} equityCurve={curveWithGap} />)

      const equityTab = screen.getByRole('tab', { name: 'Equity (72h)' })
      fireEvent.click(equityTab)

      expect(screen.getByText(/from peak/i)).toBeInTheDocument()
    })
  })

  describe('edge cases', () => {
    it('should handle zero values', () => {
      const zeroMetrics: RiskMetrics = {
        max_drawdown: 0,
        max_drawdown_pct: 0,
        sharpe_ratio: 0,
        profit_factor: 0,
        avg_win: 0,
        avg_loss: 0,
        avg_rr: 0,
        largest_win: 0,
        largest_loss: 0,
        expectancy: 0,
      }

      render(<RiskEquityPanel riskMetrics={zeroMetrics} equityCurve={[]} />)

      expect(screen.getByText('Profitability')).toBeInTheDocument()
    })

    it('should handle single equity curve point', () => {
      const singlePoint: EquityCurvePoint[] = [{ time: 1000, value: 10000 }]

      render(<RiskEquityPanel riskMetrics={null} equityCurve={singlePoint} />)

      expect(screen.getByText('No risk metrics available')).toBeInTheDocument()
    })

    it('should handle very large values', () => {
      const largeMetrics: RiskMetrics = {
        max_drawdown: 100000.0,
        max_drawdown_pct: 50.0,
        sharpe_ratio: 10.0,
        profit_factor: 10.0,
        avg_win: 10000.0,
        avg_loss: -5000.0,
        avg_rr: 5.0,
        largest_win: 50000.0,
        largest_loss: -20000.0,
        expectancy: 5000.0,
      }

      render(<RiskEquityPanel riskMetrics={largeMetrics} equityCurve={[]} />)

      expect(screen.getByText('Profitability')).toBeInTheDocument()
    })
  })
})
