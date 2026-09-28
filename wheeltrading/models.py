"""Wheel strategy input and recommendation contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class AccountState:
    cash: float
    net_liquidation: float
    stock_qty: int
    # Cash already committed as collateral to open wheel cash-secured puts
    # across ALL symbols, used to enforce the portfolio-wide 30% cap.
    existing_put_collateral: float = 0.0
    # Count of currently open short wheel option contracts (puts or calls)
    # for THIS symbol, used to enforce the 2-lot (200 share) per-symbol cap.
    existing_symbol_contracts: int = 0


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