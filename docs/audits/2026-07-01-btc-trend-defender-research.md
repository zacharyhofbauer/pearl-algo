# BTC Trend Defender Research - 2026-07-01

## Source
- Input provided: Discord screenshot of MNQ TradingView chart plus request to research BTC strategies, build/upload/backtest, and iterate agentically.
- Canonical implementation artifact: `pine/btc_trend_defender.pine`.
- Local backtest harness: `scripts/ops/backtest_btc_trend_defender.py`.
- Backtest artifact: `docs/audits/2026-07-01-btc-trend-defender-backtest.json`.
- Sweep artifact: `docs/audits/2026-07-01-btc-trend-defender-sweep.json`.

## Research question
What BTC strategy family has the strongest prior and can be translated into a safe PearlAlgo TradingView research candidate without touching live execution?

## Evidence map
- General trend-following prior: time-series momentum/trend-following is a documented cross-asset effect, but it has drawdowns and implementation risk. Source: https://quantpedia.com/strategies/time-series-momentum-effect
- Crypto-specific prior: Zarattini/Pagani/Barbon propose Donchian channel trend models with volatility-based sizing for crypto. Source: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5209907
- BTC-specific design prior: Quantpedia's BTC study frames hourly trend-following as reasonable for BTC but warns raw indicator crosses are too noisy without higher-timeframe structure. Source: https://quantpedia.com/how-to-design-a-simple-multi-timeframe-trend-strategy-on-bitcoin/
- Pine anti-repaint requirement: TradingView docs warn HTF `request.security()` can repaint and that confirmed offsets are required. Sources: https://www.tradingview.com/pine-script-docs/concepts/repainting/ and https://www.tradingview.com/pine-script-docs/concepts/other-timeframes-and-data/
- CME MBT risk context: MBT is 0.10 bitcoin and $5 index points = $0.50/contract. Sources: https://www.cmegroup.com/markets/cryptocurrencies/bitcoin/micro-bitcoin.contractSpecs.html and CME Rulebook Chapter 348.

## Candidate built
`btc_trend_defender.pine` implements:
- 1h execution surface.
- Confirmed 4h regime: EMA 20/50 plus ADX.
- Confirmed daily 200 EMA direction filter.
- Long-only Donchian breakout by default.
- Wide Chandelier exit: 8x ATR.
- Costs: 0.06% per side and $5 slippage in the Pine tester.
- Alerts muted by default via `Signal status = Research - alerts muted`.

## Backtest result
Data: Coinbase Exchange BTC-USD hourly candles, 2019-07-05 00:00 UTC through 2026-07-01 00:00 UTC.

Default candidate:
- Trades: 100
- Total return: +282.09%
- Buy and hold over same post-warmup window: +424.07%
- Profit factor: 1.662
- Win rate: 43.0%
- Max drawdown: -36.56%
- Mean per-trade expectancy: +2.821% of starting equity
- Bootstrap CI95 for mean trade: [-0.465%, +6.474%]

Interpretation: positive but not promoted. The lower CI crosses zero and buy-and-hold still outperformed. This is research/paper only.

## Failed draft
The first fixed prior used Donchian 55, 3x ATR trail, two-sided entries, and a 240-hour time stop. It failed badly:
- Trades: 465
- Total return: -89.08%
- Profit factor: 0.629
- Bootstrap CI95: [-0.320%, -0.053%] per trade

The failure mode was clear: shorts plus tight exits created whipsaw bleed.

## Sweep takeaway
A bounded 72-variant sweep was used as a disconfirmation tool, not an optimizer. The stable shape was:
- Long-only beats two-sided for drawdown and robustness.
- Wide 8x ATR Chandelier exits dominate 3x/5x exits.
- Donchian 100-200 stays positive across ADX 10-25.

The chosen default is the middle of the robust band with an adequate 100-trade sample: Donchian 100, ADX 10, 8x ATR, long-only, no time stop.

## Promotion gate
Do not arm alerts or trade this until all are true:
1. TradingView Strategy Tester compiles and broadly matches the local result on BTCUSD/BTCUSD.P/MBT chart data.
2. Both half-window tests are green, not just the recent bull regime.
3. Cost sensitivity survives costs-on versus costs-zeroed.
4. At least 30 forward paper alerts are journaled with actual fill delay/slippage.
5. If using CME MBT/BTC, contract sizing is recalibrated to the account drawdown limit before alerts are armed.

## Operational boundary
No edits were made to `config/live/tradovate_paper.yaml`, execution remains disarmed, and the automated Tradovate paper evaluator was not started.
TradingView upload was not performed because there is no authenticated TradingView upload/API surface in this session.
