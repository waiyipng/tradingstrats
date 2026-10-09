"""Conservative defaults for the MS bull call spread strategy."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BullCallSpreadConfig:
    symbol: str = "MS"
    # Only consider expirations falling in the quarterly cycle months.
    quarterly_months: tuple[int, ...] = (1, 4, 7, 10)
    # Lower bound keeps the chosen expiration from sitting uncomfortably close
    # to the target date; upper bound avoids rolling to the following cycle.
    min_days_to_expiry: int = 14
    max_days_to_expiry: int = 120
    # Vertical width search range as a fraction of spot price.
    min_width_pct: float = 0.025
    max_width_pct: float = 0.15
    # Estimated per-contract round-trip commission/slippage, in dollars.
    round_trip_cost_per_contract: float = 2.0
    max_notional_pct_of_excess_liquidity: float = 1.0
    # Reject a leg whose bid/ask spread is this wide relative to its ask, since a
    # near-zero bid on an illiquid strike artificially inflates return-on-debit.
    max_relative_bid_ask_spread: float = 0.50
    max_concurrent_positions: int = 1
    # Suggested exit: close if the spread's current value falls to this
    # fraction of the entry debit (a premium-based stop, not a stock price).
    stop_loss_pct_of_debit: float = 0.50
    # Suggested exit: close by this many days before expiry regardless of P&L.
    exit_days_before_expiry: int = 7
    # Default research parameters used by the scheduler and as CLI defaults.
    # Update these (or override via CLI flags) when your price target or horizon changes.
    target_price: float = 202.0
    target_date: str = "2026-10-16"
    default_amount_usd: float = 6000.0


MS_CONFIG = BullCallSpreadConfig()

# The scheduler only runs while US equity options are trading. Outside this
# window delayed/live option quotes are stale or missing.
MARKET_TIMEZONE = "America/New_York"
MARKET_OPEN = (9, 30)
MARKET_CLOSE = (16, 0)
