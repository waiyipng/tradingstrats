"""Read-only IBKR paper account, BTC (Paxos) contract, quote, and position data."""
from __future__ import annotations

import requests
from ib_async import IB, Crypto

from newstrading.common import usd_summary_value
from btctrend.config import BtcTrendConfig
from btctrend.models import AccountState, BtcQuote

PAPER_PORT = 7497
LIVE_PORT = 7496
QUOTE_WAIT_SECONDS = 8.0
DEFAULT_SIZE_INCREMENT = 0.0001
DEFAULT_PRICE_TICK = 0.25
# Public, keyless top-of-book used only when IBKR returns no BTC quote (e.g. the
# account lacks the PAXOS crypto market-data permission).
REFERENCE_QUOTE_URL = "https://api.exchange.coinbase.com/products/BTC-USD/ticker"


def connect(client_id: int, live: bool = False) -> IB:
    ib = IB()
    ib.connect("127.0.0.1", LIVE_PORT if live else PAPER_PORT, clientId=client_id, timeout=10)
    return ib


def account_state(ib: IB) -> AccountState:
    rows = ib.accountSummary()
    cash = usd_summary_value(rows, "TotalCashValue")
    net_liquidation = usd_summary_value(rows, "NetLiquidation", cash)
    return AccountState(
        cash=cash, net_liquidation=net_liquidation,
        excess_liquidity=usd_summary_value(rows, "ExcessLiquidity", net_liquidation),
    )


def btc_contract(ib: IB, config: BtcTrendConfig) -> tuple[Crypto, float, float]:
    """Qualified BTC contract, its order size increment, and its price tick."""
    details = ib.reqContractDetails(Crypto(config.symbol, config.exchange, config.currency))
    if not details:
        raise RuntimeError(f"{config.symbol}/{config.exchange} crypto contract could not be qualified (check crypto trading permissions)")
    increment = float(details[0].sizeIncrement or details[0].minSize or DEFAULT_SIZE_INCREMENT)
    return details[0].contract, increment, float(details[0].minTick or DEFAULT_PRICE_TICK)


def btc_quote(ib: IB, contract: Crypto) -> BtcQuote:
    ib.reqMarketDataType(3)  # delayed when a real-time subscription is unavailable
    ticker = ib.reqMktData(contract, "", False, False)
    waited = 0.0
    while waited < QUOTE_WAIT_SECONDS and not (ticker.bid and ticker.bid > 0 and ticker.ask and ticker.ask > 0):
        ib.sleep(0.5)
        waited += 0.5
    ib.cancelMktData(contract)
    valid = lambda value: float(value) if value and value == value and value > 0 else None  # noqa: E731 - filters NaN/zero
    return BtcQuote(bid=valid(ticker.bid), ask=valid(ticker.ask), last=valid(ticker.last))


def reference_quote() -> BtcQuote:
    try:
        response = requests.get(REFERENCE_QUOTE_URL, timeout=8, headers={"User-Agent": "tradingstrats-btctrend"})
        response.raise_for_status()
        data = response.json()
        return BtcQuote(bid=float(data["bid"]), ask=float(data["ask"]), last=float(data["price"]), source="coinbase_reference")
    except (requests.RequestException, KeyError, ValueError) as exc:
        raise RuntimeError(f"no IBKR BTC quote and the reference quote failed: {exc}") from exc


def btc_quote_with_fallback(ib: IB, contract: Crypto) -> BtcQuote:
    quote = btc_quote(ib, contract)
    return quote if quote.bid and quote.ask else reference_quote()


def account_btc_qty(ib: IB, config: BtcTrendConfig) -> float:
    return sum(
        float(position.position)
        for position in ib.positions()
        if position.contract.secType == "CRYPTO" and position.contract.symbol == config.symbol
    )
