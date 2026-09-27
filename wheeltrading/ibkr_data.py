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


def account_state(ib: IB, symbol: str) -> AccountState:
    summary = {row.tag: row.value for row in ib.accountSummary()}
    qty = sum(int(position.position) for position in ib.positions() if position.contract.secType == "STK" and position.contract.symbol == symbol)
    cash = float(summary.get("TotalCashValue", 0.0))
    return AccountState(cash=cash, net_liquidation=float(summary.get("NetLiquidation", cash)), stock_qty=qty)


def _target_strike(strikes: set[float], spot: float, right: str, target_otm_pct: float) -> float | None:
    if right == "P":
        candidates = [strike for strike in strikes if strike <= spot * (1 - target_otm_pct)]
        return max(candidates) if candidates else None
    candidates = [strike for strike in strikes if strike >= spot * (1 + target_otm_pct)]
    return min(candidates) if candidates else None


def _snapshot_quote(ib: IB, contract: Option) -> OptionQuote:
    ticker = ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)
    delta = next(
        (
            float(computation.delta)
            for computation in (ticker.modelGreeks, ticker.lastGreeks, ticker.bidGreeks, ticker.askGreeks)
            if computation and computation.delta is not None
        ),
        None,
    )
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


def option_quotes(ib: IB, symbol: str, min_days: int, max_days: int, target_otm_pct: float = 0.05) -> list[OptionQuote]:
    ib.reqMarketDataType(3)  # Delayed data when real-time subscriptions are unavailable.
    stock = Stock(symbol, "SMART", "USD")
    ib.qualifyContracts(stock)
    tickers = ib.run(ib.reqTickersAsync(stock), timeout=REQUEST_TIMEOUT_SECONDS)
    underlying_price = tickers[0].marketPrice()
    if not underlying_price or underlying_price != underlying_price:
        return []
    chains = ib.run(ib.reqSecDefOptParamsAsync(symbol, "", "STK", stock.conId), timeout=REQUEST_TIMEOUT_SECONDS)
    chain = next((item for item in chains if item.exchange == "SMART"), None)
    if chain is None:
        return []
    expiration = next((expiry for expiry in sorted(chain.expirations) if min_days <= _days_to_expiry(expiry) <= max_days), None)
    if expiration is None:
        return []
    contracts = []
    for right in ("P", "C"):
        strike = _target_strike(chain.strikes, underlying_price, right, target_otm_pct)
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
        )
        return wheel_account, option_quotes(ib, symbol, min_days, max_days, target_otm_pct)
    finally:
        if ib.isConnected():
            ib.disconnect()