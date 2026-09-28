"""Read-only IBKR paper spot/futures data for gold carry and calendar-spread evaluation."""
from __future__ import annotations

from typing import Optional

from ib_async import IB, Contract, Future

from goldtrading.carry import days_to_expiry
from goldtrading.config import GoldConfig
from goldtrading.models import AccountState, FuturesQuote, MarketSnapshot, SpotQuote

PAPER_PORT = 7497
REQUEST_TIMEOUT_SECONDS = 8


def _normalize_expiry(value: str) -> str:
    """IBKR sometimes reports a monthly contract as YYYYMM; normalize to YYYYMMDD."""
    return value if len(value) >= 8 else f"{value}01"


def account_state(ib: IB) -> AccountState:
    summary = {row.tag: row.value for row in ib.accountSummary()}
    cash = float(summary.get("TotalCashValue", 0.0))
    return AccountState(cash=cash, net_liquidation=float(summary.get("NetLiquidation", cash)))


def spot_quote(ib: IB, config: GoldConfig) -> Optional[SpotQuote]:
    contract = Contract(secType="CMDTY", symbol=config.spot_symbol, exchange="SMART", currency="USD")
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        return None
    ticker = ib.reqMktData(qualified[0], snapshot=True)
    ib.sleep(2)
    bid = float(ticker.bid) if ticker.bid and ticker.bid > 0 else None
    ask = float(ticker.ask) if ticker.ask and ticker.ask > 0 else None
    return SpotQuote(symbol=config.spot_symbol, bid=bid, ask=ask)


def _listed_futures_months(ib: IB, config: GoldConfig) -> list:
    details = ib.reqContractDetails(Future(symbol=config.futures_symbol, exchange=config.futures_exchange, currency="USD"))
    dated = [detail for detail in details if detail.contract.lastTradeDateOrContractMonth]
    dated = [detail for detail in dated if days_to_expiry(_normalize_expiry(detail.contract.lastTradeDateOrContractMonth)) >= 0]
    return sorted(dated, key=lambda detail: detail.contract.lastTradeDateOrContractMonth)


def _futures_quote_from_details(ib: IB, detail) -> FuturesQuote:
    contract = detail.contract
    ticker = ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)
    bid = float(ticker.bid) if ticker.bid and ticker.bid > 0 else None
    ask = float(ticker.ask) if ticker.ask and ticker.ask > 0 else None
    expiry = _normalize_expiry(contract.lastTradeDateOrContractMonth)
    return FuturesQuote(
        symbol=contract.symbol,
        local_symbol=contract.localSymbol,
        expiry=expiry,
        bid=bid,
        ask=ask,
        days_to_expiry=days_to_expiry(expiry),
        min_tick=float(detail.minTick or 0.10),
    )


def futures_quotes(ib: IB, config: GoldConfig) -> tuple[Optional[FuturesQuote], Optional[FuturesQuote]]:
    ib.reqMarketDataType(3)  # Delayed data when real-time subscriptions are unavailable.
    months = _listed_futures_months(ib, config)
    near_detail = next(
        (detail for detail in months if days_to_expiry(_normalize_expiry(detail.contract.lastTradeDateOrContractMonth)) >= config.min_days_to_expiry_near),
        None,
    )
    if near_detail is None:
        return None, None
    near_days = days_to_expiry(_normalize_expiry(near_detail.contract.lastTradeDateOrContractMonth))
    far_detail = next(
        (
            detail for detail in months
            if days_to_expiry(_normalize_expiry(detail.contract.lastTradeDateOrContractMonth)) >= near_days + config.min_days_between_months
        ),
        None,
    )
    near_quote = _futures_quote_from_details(ib, near_detail)
    far_quote = _futures_quote_from_details(ib, far_detail) if far_detail is not None else None
    return near_quote, far_quote


def quote_for_expiry(ib: IB, config: GoldConfig, expiry: str) -> Optional[FuturesQuote]:
    """Fetch a fresh quote for a specific, already-known contract month (used by monitor.py)."""
    details = ib.reqContractDetails(Future(symbol=config.futures_symbol, exchange=config.futures_exchange, currency="USD", lastTradeDateOrContractMonth=expiry))
    if not details:
        return None
    return _futures_quote_from_details(ib, details[0])


def fetch_market_snapshot(config: GoldConfig, client_id: int = 41) -> tuple[AccountState, MarketSnapshot]:
    ib = IB()
    ib.connect("127.0.0.1", PAPER_PORT, clientId=client_id, timeout=10)
    try:
        account = account_state(ib)
        spot = spot_quote(ib, config)
        if spot is None:
            raise RuntimeError("US spot gold (XAUUSD) contract could not be qualified for this account")
        near, far = futures_quotes(ib, config)
        return account, MarketSnapshot(spot=spot, near_future=near, far_future=far)
    finally:
        if ib.isConnected():
            ib.disconnect()
