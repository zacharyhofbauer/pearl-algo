// Export all stores
export { useAgentStore, type AgentState } from './agentStore'
export type {
  AIStatus,
  ChallengeStatus,
  PeriodStats,
  PerformanceStats,
  RecentExit,
  TopLoss,
  RiskMetrics,
  BuySellPressure,
  CadenceMetrics,
  MarketRegime,
  SignalRejections,
  LastSignalDecision,
  ShadowCounters,
  GatewayStatus,
  ConnectionHealth,
  ErrorSummary,
  Config,
  DataQuality,
  EquityCurvePoint,
  SessionPerformance,
  HourStats,
  DurationStats,
  DirectionBreakdown,
  StatusBreakdown,
  AnalyticsData,
  PearlSuggestion,
  PearlShadowMetrics,
  PearlInsights,
  // New types for enhanced transparency
  ExecutionState,
  CircuitBreakerStatus,
  MLFilterPerformance,
  SessionContext,
  SignalActivity,
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
  // AI mode selectors (consolidated from page.tsx)
  selectAIMode,
  selectAgentModeBadge,
  selectRegimeBadge,
  type AIMode,
  type AgentModeBadge,
  type RegimeBadge,
} from './agentStore'

export { useChartStore, type Timeframe } from './chartStore'

export {
  usePearlStore,
  type PearlMessage,
  type TradingContext,
  type PearlTab,
  selectMessages,
  selectIsConnected as selectPearlIsConnected,
  selectIsHeaderExpanded,
  selectActiveTab,
  selectTradingContext,
  selectInputValue,
  selectIsLoading as selectPearlIsLoading,
  selectShowContext,
  selectUnreadCount,
} from './pearlStore'
export type {
  CandleData,
  IndicatorData,
  Indicators,
  MarkerData,
  MarketStatus,
  MACDData,
  BollingerBandsData,
  ATRBandsData,
  VolumeProfileData,
  VolumeProfile,
  Position,
  PositionLine,
} from './chartStore'
export {
  selectCurrentPrice,
  selectPriceChange,
  selectIsMarketOpen,
  selectRSI,
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
  selectChartsLocked,
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
