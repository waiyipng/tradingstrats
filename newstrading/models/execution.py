"""JSON schema for the Execution module output (execution_report.json)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class OrderFill:
    requested_qty: int
    filled_qty: int
    avg_fill_price: Optional[float]
    commission: float = 0.0


@dataclass
class RiskCheckResult:
    passed: bool
    reasons: List[str] = field(default_factory=list)


@dataclass
class ExecutionReport:
    execution_id: str
    recommendation_id: str
    symbol: str
    timestamp: str
    status: str  # FILLED | PARTIAL | PENDING | CANCELLED | REJECTED | DRY_RUN
    broker: str
    order: OrderFill
    risk_checks: RiskCheckResult
    broker_order_id: Optional[int] = None
    portfolio_cash_balance: Optional[float] = None
    portfolio_position_qty: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
