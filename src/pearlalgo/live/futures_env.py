from __future__ import annotations

import pandas as pd

from pearlalgo.risk.agent import RiskAgent


class FuturesEnv:
    """
    Minimal futures-like environment for offline testing.
    - Action space: 0=BUY, 1=HOLD/FLAT, 2=SELL (one contract max).
    - Reward: mark-to-market PnL using close prices and tick_value.
    - Optional RiskAgent halts the episode on drawdown/target breach.
    This is intentionally lightweight and avoids a gym dependency; swap in a
    fuller env for production training.
    """

    ACTIONS = {0: "BUY", 1: "HOLD", 2: "SELL"}

    def __init__(
        self,
        data: pd.DataFrame,
        tick_value: float = 50.0,
        contract_size: float = 1.0,
        risk_agent: RiskAgent | None = None,
        lookback: int = 20,
    ):
        self.data = data.reset_index(drop=True)
        self.tick_value = tick_value
        self.contract_size = contract_size
        self.risk_agent = risk_agent
        self.lookback = lookback
        self._ptr = 1
        self._position = 0  # -1, 0, +1
        self._entry_price: float | None = None
        self._cash = 0.0

    def reset(self):
        self._ptr = 1
        self._position = 0
        self._entry_price = None
        self._cash = 0.0
        return self._observation()

    def _price(self) -> float:
        return float(self.data["Close"].iloc[self._ptr])

    def _observation(self) -> pd.DataFrame:
        start = max(0, self._ptr - self.lookback)
        return self.data.iloc[start : self._ptr + 1].copy()

    def step(self, action: int):
        if action not in self.ACTIONS:
            raise ValueError(f"Invalid action {action}; expected 0/1/2")

        price = self._price()
        reward = 0.0

        target_pos = {0: 1, 1: 0, 2: -1}[action]
        if target_pos != self._position:
            # Close existing position if any.
            if self._position != 0 and self._entry_price is not None:
                reward += (price - self._entry_price) * self._position * self.tick_value * self.contract_size
                self._cash += reward
            # Open new position if not flat.
            self._position = target_pos
            self._entry_price = price if self._position != 0 else None
        else:
            # Mark-to-market PnL for held position.
            if self._position != 0 and self._entry_price is not None:
                reward += (price - self._entry_price) * self._position * self.tick_value * self.contract_size

        self._ptr += 1
        done = self._ptr >= len(self.data)
        info = {"pnl": self._cash + reward, "position": self._position}

        if self.risk_agent:
            self.risk_agent.update(realized_pnl=info["pnl"])
            allowed, reason = self.risk_agent.allow_trade()
            info["risk_reason"] = reason
            if not allowed:
                done = True

        return self._observation(), reward, done, info
