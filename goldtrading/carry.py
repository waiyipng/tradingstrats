"""Pure cost-of-carry math for gold spot/futures pricing. No I/O, no broker calls."""
from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from goldtrading.models import CarryLadder


def days_to_expiry(expiry: str) -> int:
    return max(0, (datetime.strptime(expiry, "%Y%m%d").date() - date.today()).days)


def years_between(days: int) -> float:
    return max(days, 0) / 365.0


def theoretical_futures_price(
    spot: float,
    financing_rate_annual: float,
    storage_rate_annual: float,
    convenience_yield_annual: float,
    days_to_expiry: int,
) -> float:
    carry_rate = financing_rate_annual + storage_rate_annual - convenience_yield_annual
    return spot * (1 + carry_rate * years_between(days_to_expiry))


def basis(market_futures_price: float, theoretical_price: float) -> float:
    return market_futures_price - theoretical_price


def theoretical_calendar_spread(
    spot: float,
    financing_rate_annual: float,
    storage_rate_annual: float,
    convenience_yield_annual: float,
    near_days_to_expiry: int,
    far_days_to_expiry: int,
) -> float:
    near_price = theoretical_futures_price(spot, financing_rate_annual, storage_rate_annual, convenience_yield_annual, near_days_to_expiry)
    far_price = theoretical_futures_price(spot, financing_rate_annual, storage_rate_annual, convenience_yield_annual, far_days_to_expiry)
    return far_price - near_price


def round_to_tick(price: float, min_tick: float) -> float:
    tick = Decimal(str(min_tick or 0.10))
    return float((Decimal(str(price)) / tick).quantize(Decimal("1"), rounding=ROUND_HALF_UP) * tick)


def build_ladder(
    spot: float,
    market_price: float,
    financing_rate_annual: float,
    storage_rate_annual: float,
    convenience_yield_annual: float,
    expiry_days: int,
) -> CarryLadder:
    """Full cost-of-carry breakdown for one spot-to-futures time ladder (one contract month)."""
    years = years_between(expiry_days)
    carry_rate = financing_rate_annual + storage_rate_annual - convenience_yield_annual
    theoretical_price = theoretical_futures_price(spot, financing_rate_annual, storage_rate_annual, convenience_yield_annual, expiry_days)
    return CarryLadder(
        days_to_expiry=expiry_days,
        years_to_expiry=round(years, 4),
        financing_rate_annual=financing_rate_annual,
        storage_rate_annual=storage_rate_annual,
        convenience_yield_annual=convenience_yield_annual,
        carry_rate_annual=carry_rate,
        spot_price=spot,
        carry_cost_amount=round(theoretical_price - spot, 4),
        theoretical_price=round(theoretical_price, 4),
        market_price=market_price,
        raw_mispricing=round(market_price - theoretical_price, 4),
    )
