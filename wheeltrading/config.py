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


WHEEL_CONFIGS = {symbol: WheelConfig(symbol) for symbol in ("GOOGL", "VOO")}


def get_config(symbol: str) -> WheelConfig:
    try:
        return WHEEL_CONFIGS[symbol.upper()]
    except KeyError as exc:
        raise ValueError(f"Wheel strategy is not configured for {symbol}") from exc