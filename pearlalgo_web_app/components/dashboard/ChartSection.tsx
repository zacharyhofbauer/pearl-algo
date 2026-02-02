'use client'

import Image from 'next/image'
import CandlestickChart from '@/components/CandlestickChart'
import DataFreshnessIndicator from '@/components/DataFreshnessIndicator'
import { RSIPanel, MACDPanel, VolumeProfilePanel } from '@/components/indicators'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { useChartStore, useChartSettingsStore, useUIStore, type PositionLine, type Timeframe } from '@/stores'
import type { IChartApi } from 'lightweight-charts'

// Stale threshold in seconds
const STALE_THRESHOLD_SECONDS = 60

interface ChartSectionProps {
  mainChartApi: IChartApi | null
  positionLines: PositionLine[]
  onChartReady: (api: IChartApi | null) => void
  onForceRefresh: () => void
}

export function ChartSection({
  mainChartApi,
  positionLines,
  onChartReady,
  onForceRefresh,
}: ChartSectionProps) {
  // Chart store
  const candles = useChartStore((s) => s.candles)
  const indicators = useChartStore((s) => s.indicators)
  const markers = useChartStore((s) => s.markers)
  const timeframe = useChartStore((s) => s.timeframe)
  const barSpacing = useChartStore((s) => s.barSpacing)
  const chartLoading = useChartStore((s) => s.isLoading)
  const chartError = useChartStore((s) => s.error)

  // UI store
  const wsStatus = useUIStore((s) => s.wsStatus)
  const lastUpdate = useUIStore((s) => s.lastUpdate)
  const dataSource = useUIStore((s) => s.dataSource)
  const isFetching = useUIStore((s) => s.isFetching)

  // Chart settings store for indicator visibility
  const showRSIPanel = useChartSettingsStore((s) => s.showRSIPanel)
  const showMACDPanel = useChartSettingsStore((s) => s.showMACDPanel)
  const showVolumeProfilePanel = useChartSettingsStore((s) => s.showVolumeProfilePanel)

  return (
    <>
      {/* Main Chart */}
      <div className="chart-wrapper">
        <div className="chart-actions">
          <DataFreshnessIndicator
            lastUpdate={lastUpdate}
            wsStatus={wsStatus}
            dataSource={dataSource}
            isLoading={isFetching}
            staleThresholdSeconds={STALE_THRESHOLD_SECONDS}
            onRefresh={onForceRefresh}
            onFitAll={() => mainChartApi?.timeScale().fitContent()}
            onGoLive={() => mainChartApi?.timeScale().scrollToRealTime()}
            variant="floating"
          />
        </div>
        <div className="chart-container">
          {chartLoading && (
            <div className="loading-screen">
              <Image src="/pearl-emoji.png" alt="PEARL" className="loading-logo" width={64} height={64} priority />
              <div className="loading-text">Loading Live Data...</div>
              <div className="loading-spinner"></div>
            </div>
          )}
          {chartError && !chartLoading && (
            <div className="no-data-container">
              <Image src="/pearl-emoji.png" alt="PEARL" className="no-data-logo" width={64} height={64} />
              <div className="no-data-title">No Live Data</div>
              <div className="no-data-message">{chartError}</div>
              <div className="no-data-hint">
                Start the Market Agent to see real-time data
              </div>
            </div>
          )}
          {!chartLoading && !chartError && candles.length > 0 && (
            <ErrorBoundary
              panelName="Chart"
              fallback={
                <div className="chart-error-fallback">
                  <div className="error-boundary-icon">⚠️</div>
                  <div className="error-boundary-title">Chart Error</div>
                  <div className="error-boundary-message">Failed to render chart</div>
                  <button className="error-boundary-retry" onClick={() => window.location.reload()}>
                    Reload Page
                  </button>
                </div>
              }
            >
              <CandlestickChart
                data={candles}
                indicators={indicators}
                markers={markers}
                barSpacing={barSpacing}
                timeframe={timeframe}
                onChartReady={onChartReady}
                positionLines={positionLines}
              />
            </ErrorBoundary>
          )}
        </div>
      </div>

      {/* RSI Panel */}
      {showRSIPanel && indicators.rsi && indicators.rsi.length > 0 && (
        <RSIPanel
          data={indicators.rsi}
          barSpacing={barSpacing}
          mainChart={mainChartApi}
          height={100}
        />
      )}

      {/* MACD Panel */}
      {showMACDPanel && indicators.macd && indicators.macd.length > 0 && (
        <MACDPanel
          data={indicators.macd}
          barSpacing={barSpacing}
          mainChart={mainChartApi}
          height={120}
        />
      )}

      {/* Volume Profile Panel */}
      {showVolumeProfilePanel && indicators.volumeProfile && (
        <VolumeProfilePanel
          data={indicators.volumeProfile}
          currentPrice={candles.length > 0 ? candles[candles.length - 1].close : undefined}
          height={300}
        />
      )}
    </>
  )
}

export default ChartSection
