# Test Migration Notes

## Tests That Need Updates or Removal

The following test files reference deleted `nq_intraday` components and need to be updated or removed:

### Tests Requiring Component Rewrite:
1. **test_backtest_cli.py** - Uses `backtest_adapter`, `TradeSimulator` (deleted)
2. **test_direction_mapping.py** - Uses `MTFAnalyzer`, `TradeSimulator` (deleted)
3. **test_backtest_time_semantics.py** - Uses `RegimeDetector`, `NQSignalGenerator`, `NQScanner`, `NQIntradayStrategy`, `TradeSimulator` (all deleted)
4. **test_trade_simulator_eod_close.py** - Uses `TradeSimulator`, `ExitReason` from `backtest_adapter` (deleted)
5. **test_signal_diagnostics.py** - Uses `NQSignalGenerator`, `SignalDiagnostics`, `NQScanner` (deleted)
6. **test_signal_generation_edge_cases.py** - Uses `NQSignalGenerator`, `NQIntradayStrategy` (deleted)
7. **test_strategy_session_hours.py** - Uses `NQScanner` (deleted)
8. **test_dst_transitions.py** - Uses `NQScanner` (deleted)
9. **test_adaptive_cadence.py** - Uses `NQScanner` (deleted)

### Tests That May Work With Minor Updates:
- Most tests that only use `NQIntradayConfig` have been updated to use `PEARL_BOT_CONFIG`
- Tests using `MarketAgentService` should work with `pearl_bot_auto` strategy

### Action Required:
- **Option 1**: Remove tests that test deleted components (backtest_adapter, TradeSimulator, etc.)
- **Option 2**: Rewrite tests to work with `pearl_bot_auto` if the functionality is still needed
- **Option 3**: Mark tests as `@pytest.mark.skip` until functionality is re-implemented
