"""Call leg, account, and bull call spread recommendation/execution contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class AccountState:
    cash: float
    net_liquidation: float
    excess_liquidity: float


@dataclass(frozen=True)
class CallLeg:
    symbol: str
    expiry: str
    strike: float
    bid: Optional[float]
    ask: Optional[float]
    delta: Optional[float]
    con_id: Optional[int] = None

    @property
    def mid_price(self) -> Optional[float]:
        if self.bid is None or self.ask is None or self.bid <= 0 or self.ask <= 0:
            return None
        return round((self.bid + self.ask) / 2, 2)


@dataclass(frozen=True)
class PayoffPoint:
    price: float
    label: str
    profit_loss: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExitPlan:
    stop_loss_debit_value: float
    stop_loss_pct_of_debit: float
    exit_by_date: str
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BullCallSpreadRecommendation:
    action: Literal["BUY_BULL_CALL_SPREAD", "HOLD"]
    symbol: str
    target_price: float
    target_date: str
    expiry: Optional[str]
    long_leg: Optional[CallLeg]
    short_leg: Optional[CallLeg]
    contracts: int
    net_debit: Optional[float]
    max_profit: Optional[float]
    max_loss: Optional[float]
    breakeven: Optional[float]
    return_on_debit_pct: Optional[float]
    payoff_ladder: list[PayoffPoint]
    exit_plan: Optional[ExitPlan]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "symbol": self.symbol,
            "target_price": self.target_price,
            "target_date": self.target_date,
            "expiry": self.expiry,
            "long_leg": asdict(self.long_leg) if self.long_leg else None,
            "short_leg": asdict(self.short_leg) if self.short_leg else None,
            "contracts": self.contracts,
            "net_debit": self.net_debit,
            "max_profit": self.max_profit,
            "max_loss": self.max_loss,
            "breakeven": self.breakeven,
            "return_on_debit_pct": self.return_on_debit_pct,
            "payoff_ladder": [point.to_dict() for point in self.payoff_ladder],
            "exit_plan": self.exit_plan.to_dict() if self.exit_plan else None,
            "reasons": self.reasons,
        }


@dataclass(frozen=True)
class SpreadExecutionReport:
    status: str
    reason: str
    order_id: Optional[int] = None
    limit_price: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AnalystPrediction:
    """The MS stock analyst agent's earnings-day price prediction and reasoning."""

    symbol: str
    earnings_date: str
    predicted_price: float
    price_range_low: float
    price_range_high: float
    confidence: Literal["low", "medium", "high"]
    predicted_eps: Optional[float]
    implied_surprise_pct: Optional[float]
    consensus_summary: str
    reasoning: list[str]
    input_confidence_pct: float = 100.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradingAgentReport:
    """The bull call spread trading agent's recommendation and its own reasoning,
    layered on top of the deterministic BullCallSpreadRecommendation it is based on."""

    recommendation: BullCallSpreadRecommendation
    reasoning: list[str]
    alternatives_considered: list[str]
    primary_risk: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation": self.recommendation.to_dict(),
            "reasoning": self.reasoning,
            "alternatives_considered": self.alternatives_considered,
            "primary_risk": self.primary_risk,
        }
