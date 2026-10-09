"""Defaults for the BTC trend-following strategy. See STRATEGY.md for the research behind them."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BtcTrendConfig:
    # IBKR routes spot bitcoin through Paxos; yfinance supplies the daily history
    # the signals (and the backtest) are computed from.
    symbol: str = "BTC"
    exchange: str = "PAXOS"
    currency: str = "USD"
    history_symbol: str = "BTC-USD"
    history_days: int = 450
    # Ensemble members: standard medium-horizon lookbacks, chosen a priori rather
    # than optimized. Each casts a 0/1 long vote; the score is the vote fraction.
    sma_lookbacks: tuple[int, ...] = (50, 100, 150)
    sma_crossovers: tuple[tuple[int, int], ...] = ((20, 100), (50, 200))
    momentum_lookbacks: tuple[int, ...] = (60, 120)
    # (entry N-day high, exit M-day low) channel breakouts.
    donchian_channels: tuple[tuple[int, int], ...] = ((55, 20), (100, 50))
    # Scale exposure down when realized volatility exceeds the target; never lever up.
    vol_target_annual: float = 0.60
    vol_window_days: int = 30
    max_exposure: float = 1.0
    # Risk exit: trailing stop at the highest close since entry minus this many
    # 14-day ATRs, checked every cycle against the live bid. Once stopped out, stay
    # flat until the close breaks above the prior 20-day high. 3.75-4.25x sits on a
    # stable plateau in the backtest; tighter stops get whipsawed (see STRATEGY.md).
    trailing_stop_atr_multiple: float = 4.0
    atr_window_days: int = 14
    reentry_breakout_days: int = 20
    # Profit taking: once a trade's daily close is this far above its entry close,
    # trim to (1 - fraction) of full exposure for the rest of the trade and let the
    # remainder ride the trailing stop. +25%..+100% all improved Sharpe and drawdown.
    profit_take_gain_pct: float = 0.50
    profit_take_fraction: float = 1 / 3
    # The newest completed daily bar must be at most this many days old (UTC);
    # otherwise exposure may only be reduced, never increased.
    max_bar_age_days: int = 1
    # Only rebalance when the target exposure moves by more than this (fraction of
    # the sleeve); a move to zero always executes. Cuts turnover roughly in half.
    rebalance_band: float = 0.20
    # Strategy sleeve: a fully-long position is this fraction of excess liquidity
    # (IBKR's ExcessLiquidity: buying power left after margin requirements), not
    # net liquidation, so the sleeve sizes down when margin is already committed.
    max_allocation_pct_of_excess_liquidity: float = 0.10
    # Keep this fraction of cash untouched when buying.
    min_cash_reserve_pct: float = 0.05
    min_order_usd: float = 25.0
    # Marketable-limit offset from the touch, so IOC orders fill without chasing.
    limit_offset_pct: float = 0.005
    # Reject the cycle when the IBKR quote and the last daily close disagree this much
    # (bad tick, stale data, or wrong contract).
    max_quote_deviation_pct: float = 0.15
    # Backtest assumptions: per-side commission plus slippage, and the in/out-of-sample split.
    backtest_cost_per_side: float = 0.0025
    backtest_start: str = "2014-09-17"
    backtest_oos_start: str = "2021-01-01"


BTC_CONFIG = BtcTrendConfig()

# Scheduler cadence, from trading_config.json. The trailing stop is checked against
# the live bid each cycle, so a short interval keeps live stop fills close to the
# backtest's intraday stop; daily bars are cached, so frequent cycles don't
# re-download history.
from trading_config import get_strategy_config as _get_strategy_config

RUN_INTERVAL_MINUTES = _get_strategy_config("btctrend")["run_interval_minutes"]
