"""Approval-gated, paper-first VOO wheel strategy.

The scan command only creates a proposal.  The approve command is the only
path that submits an order, and it submits the persisted proposal unchanged.

Examples:
    python wheel_strategy.py scan
    python wheel_strategy.py list
    python wheel_strategy.py approve --proposal-id wheel_...
    python wheel_strategy.py reject --proposal-id wheel_...
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ib_async import IB, LimitOrder, Option, Stock


TICKER = "VOO"
CONTRACT_SIZE = 100
PAPER_PORT = 7497
LIVE_PORT = 7496
DEFAULT_DTE = 30
DEFAULT_OTM_PCT = 5.0
DEFAULT_STATE_PATH = Path(__file__).with_name("wheel_state.json")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:8]}"


def choose_strike(strikes: Iterable[float], spot: float, right: str, otm_pct: float) -> float:
    if spot <= 0 or otm_pct <= 0:
        raise ValueError("spot and otm_pct must be positive")
    available = sorted(float(strike) for strike in strikes)
    if right == "P":
        eligible = [strike for strike in available if strike <= spot * (1 - otm_pct / 100)]
        if eligible:
            return eligible[-1]
    elif right == "C":
        eligible = [strike for strike in available if strike >= spot * (1 + otm_pct / 100)]
        if eligible:
            return eligible[0]
    else:
        raise ValueError("right must be P or C")
    raise ValueError(f"no suitable {right} strike for spot ${spot:.2f}")


@dataclass
class Proposal:
    proposal_id: str
    created_at: str
    symbol: str
    phase: str
    action: str
    right: str
    expiration: str
    strike: float
    quantity: int
    limit_price: float
    collateral: float
    rationale: str
    status: str = "PENDING"
    order_id: Optional[int] = None
    submitted_at: Optional[str] = None


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"proposals": [], "updated_at": None}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_state(path: Path, state: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.write("\n")
    temporary.replace(path)


def add_proposal(path: Path, proposal: Proposal) -> None:
    state = load_state(path)
    state["proposals"].append(asdict(proposal))
    state["updated_at"] = utc_now()
    save_state(path, state)


def find_proposal(state: Dict[str, Any], proposal_id: str) -> Dict[str, Any]:
    for proposal in state.get("proposals", []):
        if proposal["proposal_id"] == proposal_id:
            return proposal
    raise KeyError(f"proposal not found: {proposal_id}")


def valid_quote(ticker: Any) -> Tuple[float, float, float]:
    bid = float(ticker.bid) if ticker.bid and ticker.bid > 0 else 0.0
    ask = float(ticker.ask) if ticker.ask and ticker.ask > 0 else 0.0
    last = float(ticker.last) if ticker.last and ticker.last > 0 else 0.0
    if bid and ask:
        return bid, ask, (bid + ask) / 2
    if last:
        return bid, ask, last
    raise RuntimeError("no usable market data returned; scan aborted")


def option_quote(ib: IB, contract: Option) -> Tuple[float, float, float]:
    ticker = ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)
    return valid_quote(ticker)


def account_cash(ib: IB) -> float:
    summary = {row.tag: row.value for row in ib.accountSummary()}
    return float(summary.get("TotalCashValue", 0.0))


def positions_for_voo(ib: IB) -> Tuple[int, List[Any]]:
    shares = 0
    options = []
    for position in ib.positions():
        contract = position.contract
        if contract.symbol != TICKER:
            continue
        if contract.secType == "STK":
            shares += int(position.position)
        elif contract.secType == "OPT" and position.position:
            options.append(position)
    return shares, options


def open_voo_orders(ib: IB) -> List[Any]:
    ib.reqAllOpenOrders()
    ib.sleep(1)
    return [trade for trade in ib.openTrades() if trade.contract.symbol == TICKER]


def select_option(ib: IB, underlying: Stock, right: str, spot: float, dte: int, otm_pct: float) -> Option:
    chains = ib.reqSecDefOptParams(underlying.symbol, "", underlying.secType, underlying.conId)
    chains = [chain for chain in chains if chain.exchange == "SMART"] or chains
    if not chains:
        raise RuntimeError("no VOO option chain returned")
    chain = chains[0]
    target = date.today() + timedelta(days=dte)
    expirations = sorted(
        expiry for expiry in chain.expirations
        if datetime.strptime(expiry, "%Y%m%d").date() >= target
    )
    if not expirations:
        raise RuntimeError("no option expiration at or beyond target DTE")
    expiration = expirations[0]
    strike = choose_strike(chain.strikes, spot, right, otm_pct)
    contract = Option(
        TICKER, expiration, strike, right, "SMART",
        multiplier=chain.multiplier, currency="USD", tradingClass=chain.tradingClass,
    )
    if not ib.qualifyContracts(contract):
        raise RuntimeError(f"could not qualify VOO {right} option at {strike}")
    return contract


def existing_pending_proposal(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((item for item in state.get("proposals", []) if item["status"] == "PENDING"), None)


def scan(ib: IB, state_path: Path, dte: int, otm_pct: float, max_contracts: int) -> Proposal:
    state = load_state(state_path)
    pending = existing_pending_proposal(state)
    if pending:
        raise RuntimeError(f"pending proposal already exists: {pending['proposal_id']}")
    underlying = Stock(TICKER, "SMART", "USD")
    if not ib.qualifyContracts(underlying):
        raise RuntimeError("could not qualify VOO")
    if open_voo_orders(ib):
        raise RuntimeError("existing VOO order detected; refusing to create a conflicting proposal")
    underlying_ticker = ib.reqMktData(underlying, snapshot=True)
    ib.sleep(2)
    _, _, spot = valid_quote(underlying_ticker)
    shares, options = positions_for_voo(ib)
    short_options = [item for item in options if item.position < 0]
    if short_options:
        raise RuntimeError("existing short VOO option detected; reconcile it before scanning")

    cash = account_cash(ib)
    if shares >= CONTRACT_SIZE:
        phase, right = "CALL", "C"
        quantity = min(max_contracts, shares // CONTRACT_SIZE)
        rationale = f"sell covered calls against {shares} VOO shares"
    else:
        phase, right = "PUT", "P"
        provisional = select_option(ib, underlying, right, spot, dte, otm_pct)
        quantity = min(max_contracts, math.floor(cash / (provisional.strike * CONTRACT_SIZE)))
        rationale = f"sell cash-secured puts using ${cash:,.2f} available cash"
    if quantity < 1:
        raise RuntimeError("insufficient collateral for one wheel contract")

    contract = provisional if phase == "PUT" else select_option(ib, underlying, right, spot, dte, otm_pct)
    bid, _, _ = option_quote(ib, contract)
    if bid <= 0:
        raise RuntimeError("option bid is unavailable; scan aborted")
    proposal = Proposal(
        proposal_id=new_id("wheel"), created_at=utc_now(), symbol=TICKER, phase=phase,
        action="SELL", right=right, expiration=contract.lastTradeDateOrContractMonth,
        strike=float(contract.strike), quantity=quantity, limit_price=bid,
        collateral=float(contract.strike) * CONTRACT_SIZE * quantity if right == "P" else 0.0,
        rationale=rationale,
    )
    add_proposal(state_path, proposal)
    return proposal


def approve(ib: IB, state_path: Path, proposal_id: str, live: bool = False) -> Dict[str, Any]:
    if live:
        raise RuntimeError("live mode is intentionally disabled for this approval workflow")
    state = load_state(state_path)
    proposal = find_proposal(state, proposal_id)
    if proposal["status"] != "PENDING":
        raise RuntimeError(f"proposal is already {proposal['status']}")
    if datetime.strptime(proposal["expiration"], "%Y%m%d").date() < date.today():
        raise RuntimeError("proposal has expired")
    if open_voo_orders(ib):
        raise RuntimeError("an open VOO order already exists; approval aborted")
    shares, options = positions_for_voo(ib)
    if any(item.position < 0 for item in options):
        raise RuntimeError("a short VOO option already exists; approval aborted")
    if proposal["right"] == "P":
        required_cash = proposal["collateral"]
        if account_cash(ib) < required_cash:
            raise RuntimeError(f"cash collateral changed; need ${required_cash:,.2f}")
    elif shares < proposal["quantity"] * CONTRACT_SIZE:
        raise RuntimeError("share coverage changed; approval aborted")
    contract = Option(
        proposal["symbol"], proposal["expiration"], proposal["strike"], proposal["right"],
        "SMART", multiplier=str(CONTRACT_SIZE), currency="USD",
    )
    if not ib.qualifyContracts(contract):
        raise RuntimeError("could not qualify approved option")
    trade = ib.placeOrder(contract, LimitOrder(proposal["action"], proposal["quantity"], proposal["limit_price"]))
    proposal["status"] = "SUBMITTED"
    proposal["order_id"] = trade.order.orderId
    proposal["submitted_at"] = utc_now()
    state["updated_at"] = utc_now()
    save_state(state_path, state)
    return proposal


def reject(state_path: Path, proposal_id: str) -> Dict[str, Any]:
    state = load_state(state_path)
    proposal = find_proposal(state, proposal_id)
    if proposal["status"] != "PENDING":
        raise RuntimeError(f"proposal is already {proposal['status']}")
    proposal["status"] = "REJECTED"
    state["updated_at"] = utc_now()
    save_state(state_path, state)
    return proposal


def print_proposal(proposal: Dict[str, Any]) -> None:
    print(
        f"{proposal['proposal_id']}: {proposal['status']} {proposal['action']} "
        f"{proposal['quantity']} {proposal['symbol']} {proposal['right']} "
        f"{proposal['expiration']} ${proposal['strike']:.2f} "
        f"limit=${proposal['limit_price']:.2f} collateral=${proposal['collateral']:,.2f}"
    )


def watch(args: argparse.Namespace) -> None:
    while True:
        ib = IB()
        try:
            ib.connect(args.host, PAPER_PORT, clientId=args.client_id, timeout=5)
            try:
                proposal = scan(ib, args.state, args.dte, args.otm_pct, args.max_contracts)
                print_proposal(asdict(proposal))
            finally:
                if ib.isConnected():
                    ib.disconnect()
        except Exception as exc:
            print(f"Wheel scan skipped: {exc}", file=sys.stderr)
            if ib.isConnected():
                ib.disconnect()
        time.sleep(args.interval)


def main() -> int:
    parser = argparse.ArgumentParser(description="Approval-gated paper VOO wheel strategy")
    parser.add_argument("command", choices=("scan", "watch", "list", "approve", "reject"))
    parser.add_argument("--proposal-id")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE_PATH)
    parser.add_argument("--dte", type=int, default=DEFAULT_DTE)
    parser.add_argument("--otm-pct", type=float, default=DEFAULT_OTM_PCT)
    parser.add_argument("--max-contracts", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--client-id", type=int, default=340)
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args()
    if args.dte <= 0 or args.otm_pct <= 0 or args.max_contracts <= 0:
        parser.error("--dte, --otm-pct, and --max-contracts must be positive")
    if args.interval < 10:
        parser.error("--interval must be at least 10 seconds")

    try:
        if args.command == "list":
            for proposal in load_state(args.state).get("proposals", []):
                print_proposal(proposal)
            return 0
        if args.command == "watch":
            watch(args)
            return 0
        if args.command == "reject":
            if not args.proposal_id:
                parser.error("reject requires --proposal-id")
            print_proposal(reject(args.state, args.proposal_id))
            return 0
        if not args.proposal_id and args.command == "approve":
            parser.error("approve requires --proposal-id")

        ib = IB()
        ib.connect(args.host, PAPER_PORT, clientId=args.client_id)
        try:
            if args.command == "scan":
                print_proposal(asdict(scan(ib, args.state, args.dte, args.otm_pct, args.max_contracts)))
            else:
                print_proposal(approve(ib, args.state, args.proposal_id))
        finally:
            if ib.isConnected():
                ib.disconnect()
        return 0
    except Exception as exc:
        print(f"Wheel action failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())