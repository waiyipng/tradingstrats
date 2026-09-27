"""Wheel strategy input and recommendation contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class AccountState:
    cash: float
    net_liquidation: float
    stock_qty: int


@dataclass(frozen=True)
class OptionQuote:
    symbol: str
    expiry: str
    strike: float
    right: Literal["C", "P"]
    bid: Optional[float]
    ask: Optional[float]
    delta: Optional[float]
    days_to_expiry: int

    @property
    def mid_price(self) -> Optional[float]:
        if self.bid is None or self.ask is None or self.bid < 0 or self.ask < 0:
            return None
        return round((self.bid + self.ask) / 2, 2)


@dataclass(frozen=True)
class WheelRecommendation:
    symbol: str
    action: Literal["SELL_CASH_SECURED_PUT", "SELL_COVERED_CALL", "HOLD"]
    contracts: int
    contract: Optional[OptionQuote]
    premium_credit: Optional[float]
    collateral_required: float
    annualized_yield: Optional[float]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)