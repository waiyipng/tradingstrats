"""Conservative defaults for the wheel strategy's supported underlyings."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WheelConfig:
    symbol: str
    max_allocation_pct: float = 0.10
    min_days_to_expiry: int = 21
    max_days_to_expiry: int = 45
    min_delta: float = 0.15
    max_delta: float = 0.30
    min_annualized_yield: float = 0.08
    contracts_per_trade: int = 1
    target_otm_pct: float = 0.05
    max_contracts_per_symbol: int = 2  # 200 shares / 2 lots outstanding, per underlying


# Portfolio-wide cap: total cash collateral committed to open wheel cash-secured
# puts across every symbol must not exceed this share of net liquidation. This
# is separate from WheelConfig.max_allocation_pct, which caps a single put's
# collateral at 10% of net liquidation.
PORTFOLIO_MAX_ALLOCATION_PCT = 0.30


WHEEL_CONFIGS = {
    "GOOGL": WheelConfig("GOOGL"),
    # VOO is low-volatility: a 5% OTM put sits near 0.10 delta, below min_delta,
    # so VOO targets strikes about 3% OTM instead.
    "VOO": WheelConfig("VOO", target_otm_pct=0.03),
}

# Wheel orders are only submitted during regular US trading hours (Mon-Fri,
# America/New_York). Outside this window delayed quotes are stale or missing.
MARKET_TIMEZONE = "America/New_York"
MARKET_OPEN = (9, 30)
MARKET_CLOSE = (16, 0)


def get_config(symbol: str) -> WheelConfig:
    try:
        return WHEEL_CONFIGS[symbol.upper()]
    except KeyError as exc:
        raise ValueError(f"Wheel strategy is not configured for {symbol}") from exc