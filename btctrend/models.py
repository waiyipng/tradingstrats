"""Signal, account, rebalance recommendation, and execution contracts."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Optional


@dataclass(frozen=True)
class SignalVote:
    name: str
    long: bool
    detail: str


@dataclass(frozen=True)
class TrendSignal:
    """Ensemble state at the last completed daily bar."""

    bar_date: str
    close: float
    votes: list[SignalVote]
    score: float
    realized_vol_annual: float
    vol_scalar: float
    target_exposure: float
    return_30d_pct: float
    drawdown_from_high_pct: float
    atr: float
    reentry_breakout_level: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AccountState:
    cash: float
    net_liquidation: float
    # IBKR's ExcessLiquidity: cash/securities value in excess of margin requirements.
    # The sleeve is sized off this rather than net liquidation, so a margin-constrained
    # account (e.g. other open positions eating into buying power) sizes down accordingly.
    excess_liquidity: float


@dataclass(frozen=True)
class BtcQuote:
    bid: Optional[float]
    ask: Optional[float]
    last: Optional[float] = None
    source: str = "ibkr"

    @property
    def mid_price(self) -> Optional[float]:
        if self.bid and self.ask and self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2
        return self.last if self.last and self.last > 0 else None


@dataclass(frozen=True)
class RebalanceRecommendation:
    action: Literal["BUY", "SELL", "HOLD"]
    signal_target_exposure: float
    held_exposure_before: float
    new_held_exposure: float
    sleeve_usd: float
    current_qty: float
    target_qty: float
    order_qty: float
    limit_price: Optional[float]
    order_notional: float
    reasons: list[str] = field(default_factory=list)
    # Risk-exit state to persist after this cycle (see strategy.evaluate_rebalance).
    peak_close: float = 0.0
    stop_price: Optional[float] = None
    stop_triggered: bool = False
    reentry_locked: bool = False
    entry_price: float = 0.0
    profit_taken: bool = False
    # Loss if the post-trade position were stopped out at the current stop level.
    risk_at_stop_usd: float = 0.0
    risk_at_stop_pct_of_net_liq: float = 0.0
    # Where the trailing stop would sit once target_qty is reached, even while flat
    # today (stop_price above is only set for an already-open position).
    stop_price_if_filled: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TradeExecutionReport:
    status: str
    reason: str
    order_id: Optional[int] = None
    filled_qty: float = 0.0
    avg_fill_price: Optional[float] = None
    limit_price: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
