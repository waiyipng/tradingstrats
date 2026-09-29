"""Gold spot/futures quote, account, and recommendation contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class AccountState:
    cash: float
    net_liquidation: float


@dataclass(frozen=True)
class SpotQuote:
    symbol: str
    bid: Optional[float]
    ask: Optional[float]

    @property
    def mid_price(self) -> Optional[float]:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        return round((self.bid + self.ask) / 2, 2)


@dataclass(frozen=True)
class FuturesQuote:
    symbol: str
    local_symbol: str
    expiry: str
    bid: Optional[float]
    ask: Optional[float]
    days_to_expiry: int
    min_tick: float

    @property
    def mid_price(self) -> Optional[float]:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        return round((self.bid + self.ask) / 2, 2)


@dataclass(frozen=True)
class MarketSnapshot:
    spot: SpotQuote
    near_future: Optional[FuturesQuote]
    far_future: Optional[FuturesQuote]


@dataclass(frozen=True)
class CarryLadder:
    """Full cost-of-carry breakdown for a single spot-to-futures time ladder."""

    days_to_expiry: int
    years_to_expiry: float
    financing_rate_annual: float
    storage_rate_annual: float
    convenience_yield_annual: float
    carry_rate_annual: float  # financing + storage - convenience yield
    spot_price: float
    carry_cost_amount: float  # theoretical_price - spot_price, in $/oz
    theoretical_price: float
    market_price: float
    raw_mispricing: float  # market_price - theoretical_price

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CarryRecommendation:
    action: Literal["CASH_AND_CARRY", "HOLD"]
    contracts: int
    spot_quantity_oz: float
    spot: Optional[SpotQuote]
    near_future: Optional[FuturesQuote]
    entry_basis: Optional[float]
    theoretical_futures_price: Optional[float]
    net_edge_after_costs: Optional[float]
    reasons: list[str]
    ladder: Optional[CarryLadder] = None
    round_trip_cost: Optional[float] = None
    min_net_edge_threshold: Optional[float] = None
    is_arbitrage_opportunity: bool = False
    verdict: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CalendarRecommendation:
    action: Literal["SELL_CALENDAR_SPREAD", "BUY_CALENDAR_SPREAD", "HOLD"]
    contracts: int
    near_future: Optional[FuturesQuote]
    far_future: Optional[FuturesQuote]
    market_spread: Optional[float]
    theoretical_spread: Optional[float]
    mispricing: Optional[float]
    net_edge_after_costs: Optional[float]
    reasons: list[str]
    near_ladder: Optional[CarryLadder] = None
    far_ladder: Optional[CarryLadder] = None
    round_trip_cost: Optional[float] = None
    min_net_edge_threshold: Optional[float] = None
    is_arbitrage_opportunity: bool = False
    verdict: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
