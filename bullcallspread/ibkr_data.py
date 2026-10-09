"""Read-only IBKR paper account and call-chain data for bull call spread recommendations."""
from __future__ import annotations

from datetime import date, datetime, timezone
from ib_async import IB, Option, Stock

from newstrading.common import usd_summary_value
from bullcallspread.config import BullCallSpreadConfig
from bullcallspread.models import AccountState, CallLeg

PAPER_PORT = 7497
LIVE_PORT = 7496
REQUEST_TIMEOUT_SECONDS = 8


def _days_to_expiry(expiry: str) -> int:
    return max(0, (datetime.strptime(expiry, "%Y%m%d").date() - date.today()).days)


def account_state(ib: IB) -> AccountState:
    rows = ib.accountSummary()
    cash = usd_summary_value(rows, "TotalCashValue")
    return AccountState(
        cash=cash,
        net_liquidation=usd_summary_value(rows, "NetLiquidation", cash),
        excess_liquidity=usd_summary_value(rows, "ExcessLiquidity", cash),
    )


def underlying_price(ib: IB, stock: Stock) -> float | None:
    """Stock price from a delayed snapshot, falling back to the latest historical bar."""
    ib.reqMarketDataType(3)  # Delayed data when real-time subscriptions are unavailable.
    try:
        tickers = ib.run(ib.reqTickersAsync(stock), timeout=REQUEST_TIMEOUT_SECONDS)
        price = tickers[0].marketPrice() if tickers else None
        if price and price == price:
            return float(price)
    except TimeoutError:
        pass
    bars = ib.reqHistoricalData(stock, endDateTime="", durationStr="1 D", barSizeSetting="1 min", whatToShow="TRADES", useRTH=False)
    return float(bars[-1].close) if bars and bars[-1].close > 0 else None


def _ticker_delta(ticker) -> float | None:
    return next(
        (
            float(computation.delta)
            for computation in (ticker.modelGreeks, ticker.lastGreeks, ticker.bidGreeks, ticker.askGreeks)
            if computation and computation.delta is not None
        ),
        None,
    )


def _snapshot_quote(ib: IB, contract: Option, max_wait_seconds: float = 10.0) -> CallLeg:
    # Delayed option data arrives over several seconds (bid/ask first, greeks later),
    # so stream and wait for bid, ask, and delta rather than taking a fixed snapshot.
    ticker = ib.reqMktData(contract, "", False, False)
    waited = 0.0
    while waited < max_wait_seconds:
        ib.sleep(0.5)
        waited += 0.5
        if ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0 and _ticker_delta(ticker) is not None:
            break
    ib.cancelMktData(contract)
    delta = _ticker_delta(ticker)
    return CallLeg(
        symbol=contract.symbol,
        expiry=contract.lastTradeDateOrContractMonth,
        strike=float(contract.strike),
        bid=float(ticker.bid) if ticker.bid and ticker.bid > 0 else None,
        ask=float(ticker.ask) if ticker.ask and ticker.ask > 0 else None,
        delta=delta,
        con_id=contract.conId,
    )


def _nearest_quarterly_expiration(expirations: list[str], config: BullCallSpreadConfig, target_date: date) -> str | None:
    candidates = []
    for expiry in sorted(expirations):
        expiry_date = datetime.strptime(expiry, "%Y%m%d").date()
        if expiry_date.month not in config.quarterly_months:
            continue
        if expiry_date < target_date:
            continue
        days = _days_to_expiry(expiry)
        if config.min_days_to_expiry <= days <= config.max_days_to_expiry:
            candidates.append(expiry)
    return candidates[0] if candidates else None


def fetch_call_chain(
    ib: IB, config: BullCallSpreadConfig, target_date: date
) -> tuple[float, str, dict[float, Option]]:
    """Return (spot_price, chosen_expiration, {strike: qualified call contract})."""
    stock = Stock(config.symbol, "SMART", "USD")
    ib.qualifyContracts(stock)
    spot = underlying_price(ib, stock)
    if spot is None:
        raise RuntimeError(f"no underlying price available for {config.symbol}")

    chains = ib.run(ib.reqSecDefOptParamsAsync(config.symbol, "", "STK", stock.conId), timeout=REQUEST_TIMEOUT_SECONDS)
    smart_chains = [item for item in chains if item.exchange == "SMART"]
    chain = next((item for item in smart_chains if item.tradingClass == config.symbol), smart_chains[0] if smart_chains else None)
    if chain is None:
        raise RuntimeError(f"no SMART option chain found for {config.symbol}")

    expiration = _nearest_quarterly_expiration(list(chain.expirations), config, target_date)
    if expiration is None:
        raise RuntimeError(f"no quarterly-cycle expiration available for {config.symbol} within the configured DTE window")

    low = spot * (1 - config.max_width_pct - 0.05)
    high = spot * (1 + config.max_width_pct + 0.05)
    strikes = sorted(strike for strike in chain.strikes if low <= strike <= high)
    contracts = [Option(config.symbol, expiration, strike, "C", "SMART", multiplier=chain.multiplier, tradingClass=chain.tradingClass) for strike in strikes]
    qualified = ib.qualifyContracts(*contracts)
    # qualifyContracts leaves unresolved entries as None (the chain can list strikes
    # that aren't actually listed for this specific expiry/tradingClass combination).
    by_strike = {float(contract.strike): contract for contract in qualified if contract is not None and contract.conId}
    return spot, expiration, by_strike


def fetch_recommendation_inputs(
    config: BullCallSpreadConfig, target_date: date, client_id: int, live: bool = False
) -> tuple[AccountState, float, str, list[CallLeg]]:
    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id, timeout=10)
    try:
        account = account_state(ib)
        spot, expiration, by_strike = fetch_call_chain(ib, config, target_date)
        legs = [_snapshot_quote(ib, contract) for contract in by_strike.values()]
        return account, spot, expiration, legs
    finally:
        if ib.isConnected():
            ib.disconnect()
