"""Conservative defaults for the gold cash-and-carry and calendar-spread strategies."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GoldConfig:
    futures_symbol: str = "MGC"
    futures_exchange: str = "COMEX"
    futures_multiplier_oz: int = 10
    spot_symbol: str = "XAUUSD"
    # Manually-maintained proxy for short-term financing cost. Not fetched live;
    # review and update periodically against actual short-term rates.
    financing_rate_annual: float = 0.045
    storage_rate_annual: float = 0.003
    convenience_yield_annual: float = 0.0
    # Estimated round-trip commission/slippage cost as a fraction of spot notional,
    # subtracted from the raw mispricing before the minimum-edge check.
    round_trip_cost_pct: float = 0.0005
    min_net_edge_pct: float = 0.0015
    max_notional_pct_of_net_liq: float = 0.20
    max_concurrent_positions: int = 1
    calendar_contracts_per_trade: int = 1
    profit_take_pct_of_edge: float = 0.70
    stop_loss_edge_multiple: float = 2.0
    # Avoid entering or holding into a contract's delivery/notice window (MGC is
    # physically settled).
    min_days_to_expiry_near: int = 5
    last_trading_day_buffer: int = 3
    # Minimum gap between the near and far leg so the calendar spread carries a
    # meaningful amount of theoretical carry cost.
    min_days_between_months: int = 30


GOLD_CONFIG = GoldConfig()
