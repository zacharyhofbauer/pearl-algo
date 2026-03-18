// Export all stores
export { useAgentStore, type AgentState } from './agentStore'
export { useOperatorStore } from './operatorStore'
export type {
  AIStatus,
  RiskMetrics,
  MarketRegime,
  SignalRejections,
  LastSignalDecision,
  ShadowCounters,
  ErrorSummary,
  DirectionBreakdown,
  StatusBreakdown,
  PearlSuggestion,
  PearlInsights,
  PearlFeedMessage,
  PearlAIDebugInfo,
  PearlAIHeartbeat,
  ExecutionState,
  CircuitBreakerStatus,
  MLFilterPerformance,
  SessionContext,
  TradovateAccount,
  TradovateWorkingOrder,
  TradovateOrderStats,
} from './agentStore'

// Export selectors
export {
  selectIsRunning,
  selectDailyPnL,
  selectActiveTradesCount,
  selectPerformance,
  selectChallenge,
  selectAIStatus,
  selectCadenceMetrics,
  selectGatewayStatus,
  selectAnalytics,
  selectRecentExits,
  selectRiskMetrics,
  selectEquityCurve,
  selectMarketRegime,
  selectBuySellPressure,
  selectConfig,
  // New selectors for enhanced transparency
  selectExecutionState,
  selectCircuitBreaker,
  selectMLFilterPerformance,
  selectSessionContext,
  selectSignalActivity,
  selectTradovateAccount,
  selectAccounts,
} from './agentStore'

export { useChartStore, type Timeframe } from './chartStore'
export type {
  CandleData,
  IndicatorData,
  Indicators,
  MarkerData,
  MarketStatus,
  BollingerBandsData,
  ATRBandsData,
  VolumeProfile,
  Position,
  PositionLine,
} from './chartStore'
export {
  selectCurrentPrice,
  selectPriceChange,
  selectIsMarketOpen,
} from './chartStore'

export { useUIStore, type DataSource } from './uiStore'
export {
  selectWsStatus,
  selectIsConnected,
  selectTheme,
  selectNotifications,
  selectDataSource,
  selectIsFetching,
  selectLastFetchDuration,
  selectFetchCount,
} from './uiStore'

export { useAnnotationStore, type ChartAnnotation } from './annotationStore'

export {
  useChartSettingsStore,
  type ChartTheme,
  type IndicatorVisibility,
  type ChartThemeColors,
  selectThemeColors,
  selectIndicatorVisibility,
  getThemePreset,
} from './chartSettingsStore'
