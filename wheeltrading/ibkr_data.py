"""Read-only IBKR paper account and option-chain data for wheel recommendations."""
from __future__ import annotations

from datetime import date, datetime, timezone
from ib_async import IB, Option, Stock

from wheeltrading.models import AccountState, OptionQuote
from wheeltrading.state import active_wheel_summary, load_state

PAPER_PORT = 7497
REQUEST_TIMEOUT_SECONDS = 8


def _days_to_expiry(expiry: str) -> int:
    return max(0, (datetime.strptime(expiry, "%Y%m%d").date() - date.today()).days)


def _open_short_option_positions(ib: IB) -> list:
    return [position for position in ib.positions() if position.contract.secType == "OPT" and position.position < 0]


def portfolio_put_collateral(ib: IB) -> float:
    """Cash collateral already committed to open short puts across every wheel symbol."""
    return sum(
        float(position.contract.strike) * 100 * abs(int(position.position))
        for position in _open_short_option_positions(ib)
        if position.contract.right == "P"
    )


def symbol_open_contracts(ib: IB, symbol: str) -> int:
    """Currently open short option contracts (puts or calls) for a single symbol."""
    return sum(abs(int(position.position)) for position in _open_short_option_positions(ib) if position.contract.symbol == symbol)


def account_state(ib: IB, symbol: str) -> AccountState:
    summary = {row.tag: row.value for row in ib.accountSummary()}
    qty = sum(int(position.position) for position in ib.positions() if position.contract.secType == "STK" and position.contract.symbol == symbol)
    cash = float(summary.get("TotalCashValue", 0.0))
    return AccountState(
        cash=cash,
        net_liquidation=float(summary.get("NetLiquidation", cash)),
        stock_qty=qty,
        existing_put_collateral=portfolio_put_collateral(ib),
        existing_symbol_contracts=symbol_open_contracts(ib, symbol),
    )


def _target_strike(strikes: set[float], spot: float, right: str, target_otm_pct: float) -> float | None:
    if right == "P":
        candidates = [strike for strike in strikes if strike <= spot * (1 - target_otm_pct)]
        return max(candidates) if candidates else None
    candidates = [strike for strike in strikes if strike >= spot * (1 + target_otm_pct)]
    return min(candidates) if candidates else None


def _ticker_delta(ticker) -> float | None:
    return next(
        (
            float(computation.delta)
            for computation in (ticker.modelGreeks, ticker.lastGreeks, ticker.bidGreeks, ticker.askGreeks)
            if computation and computation.delta is not None
        ),
        None,
    )


def _snapshot_quote(ib: IB, contract: Option, max_wait_seconds: float = 10.0) -> OptionQuote:
    # Delayed option data arrives over several seconds (bid/ask first, greeks later),
    # so stream and wait for bid, ask, and delta rather than taking a fixed 2s snapshot.
    ticker = ib.reqMktData(contract, "", False, False)
    waited = 0.0
    while waited < max_wait_seconds:
        ib.sleep(0.5)
        waited += 0.5
        if ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0 and _ticker_delta(ticker) is not None:
            break
    ib.cancelMktData(contract)
    delta = _ticker_delta(ticker)
    return OptionQuote(
        symbol=contract.symbol,
        expiry=contract.lastTradeDateOrContractMonth,
        strike=float(contract.strike),
        right=contract.right,
        bid=float(ticker.bid) if ticker.bid and ticker.bid > 0 else None,
        ask=float(ticker.ask) if ticker.ask and ticker.ask > 0 else None,
        delta=delta,
        days_to_expiry=_days_to_expiry(contract.lastTradeDateOrContractMonth),
    )


def underlying_price(ib: IB, stock: Stock) -> float | None:
    """Stock price from a delayed snapshot, falling back to the latest historical bar.

    The paper account has no US stock market-data subscription, and delayed stock
    snapshots come back empty (the request times out), while historical bars and
    delayed option quotes still work.
    """
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


def option_quotes(ib: IB, symbol: str, min_days: int, max_days: int, target_otm_pct: float = 0.05) -> list[OptionQuote]:
    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)
    spot = underlying_price(ib, stock)
    if spot is None:
        return []
    chains = ib.run(ib.reqSecDefOptParamsAsync(symbol, "", "STK", stock.conId), timeout=REQUEST_TIMEOUT_SECONDS)
    # IBKR can return several SMART chains (e.g. an adjusted "2GOOGL" class with a
    # single expiry); only the standard class carries the regular monthly ladder.
    smart_chains = [item for item in chains if item.exchange == "SMART"]
    chain = next((item for item in smart_chains if item.tradingClass == symbol), smart_chains[0] if smart_chains else None)
    if chain is None:
        return []
    expiration = next((expiry for expiry in sorted(chain.expirations) if min_days <= _days_to_expiry(expiry) <= max_days), None)
    if expiration is None:
        return []
    contracts = []
    for right in ("P", "C"):
        strike = _target_strike(chain.strikes, spot, right, target_otm_pct)
        if strike is not None:
            contracts.append(Option(symbol, expiration, strike, right, "SMART", multiplier=chain.multiplier, tradingClass=chain.tradingClass))
    qualified = ib.qualifyContracts(*contracts)
    return [_snapshot_quote(ib, contract) for contract in qualified]


def fetch_recommendation_inputs(symbol: str, min_days: int, max_days: int, target_otm_pct: float = 0.05, client_id: int = 41) -> tuple[AccountState, list[OptionQuote]]:
    ib = IB()
    ib.connect("127.0.0.1", PAPER_PORT, clientId=client_id)
    try:
        account = account_state(ib, symbol)
        active_wheel = active_wheel_summary(load_state(), symbol)
        wheel_account = AccountState(
            cash=account.cash,
            net_liquidation=account.net_liquidation,
            # Only registered put-assignment lots are wheel inventory. Equity
            # signal positions and manual holdings are intentionally excluded.
            stock_qty=min(account.stock_qty, int(active_wheel["shares"])),
            existing_put_collateral=account.existing_put_collateral,
            existing_symbol_contracts=account.existing_symbol_contracts,
        )
        return wheel_account, option_quotes(ib, symbol, min_days, max_days, target_otm_pct)
    finally:
        if ib.isConnected():
            ib.disconnect()