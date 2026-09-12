"""Submit one conditional VOO limit-buy order through Interactive Brokers.

Prerequisites:
    pip install ib_async

Start IBKR Trader Workstation or IB Gateway and enable API access first.
The default connection is to the paper-trading account on port 7497.

Examples:
    python buy_voo_limit.py
    python buy_voo_limit.py --shares 2 --trigger-price 702 --limit-price 680
    python buy_voo_limit.py --live
"""

import argparse
import sys

from ib_async import IB, LimitOrder, PriceCondition, Stock


DEFAULT_TICKER = "VOO"
DEFAULT_TRIGGER_PRICE = 702.00
DEFAULT_LIMIT_PRICE = 680.00
DEFAULT_SHARES = 1
PAPER_PORT = 7497
LIVE_PORT = 7496


def submit_limit_order(
    ticker: str,
    shares: int,
    trigger_price: float,
    limit_price: float,
    tif: str,
    host: str,
    port: int,
    client_id: int,
) -> None:
    ib = IB()
    try:
        print(f"Connecting to IBKR at {host}:{port}...")
        ib.connect(host, port, clientId=client_id)

        contract = Stock(ticker, "SMART", "USD")
        qualified_contracts = ib.qualifyContracts(contract)
        if not qualified_contracts:
            raise RuntimeError(f"Could not qualify contract for {ticker}.")

        order = LimitOrder("BUY", shares, limit_price)
        order.tif = tif
        order.conditions.append(
            PriceCondition(
                conId=contract.conId,
                exch=contract.exchange,
                isMore=True,
                price=trigger_price,
            )
        )
        trade = ib.placeOrder(contract, order)

        print("Conditional order submitted.")
        print(f"  Order ID: {trade.order.orderId}")
        print(f"  Action:   {order.action}")
        print(f"  Quantity: {order.totalQuantity:g} share(s)")
        print(f"  Limit:    ${order.lmtPrice:,.2f}")
        print(f"  Trigger:  VOO >= ${trigger_price:,.2f}")
        print(f"  Time in force: {order.tif}")
        print(f"  Status:   {trade.orderStatus.status}")
    finally:
        if ib.isConnected():
            ib.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Submit one conditional VOO limit-buy order through Interactive Brokers."
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    parser.add_argument("--shares", type=int, default=DEFAULT_SHARES)
    parser.add_argument("--trigger-price", type=float, default=DEFAULT_TRIGGER_PRICE)
    parser.add_argument("--limit-price", type=float, default=DEFAULT_LIMIT_PRICE)
    parser.add_argument(
        "--tif",
        choices=("DAY", "GTC"),
        default="GTC",
        help="Order lifetime: GTC waits across sessions; DAY expires today.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--client-id", type=int, default=1)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use the live IBKR port 7496. Without this flag, use paper trading.",
    )
    args = parser.parse_args()

    if args.shares <= 0:
        parser.error("--shares must be greater than zero")
    if args.trigger_price <= 0:
        parser.error("--trigger-price must be greater than zero")
    if args.limit_price <= 0:
        parser.error("--limit-price must be greater than zero")

    port = LIVE_PORT if args.live else PAPER_PORT
    account_type = "LIVE" if args.live else "PAPER"
    print(f"{account_type} account selected for a one-time {args.ticker} purchase.")

    try:
        submit_limit_order(
            ticker=args.ticker.upper(),
            shares=args.shares,
            trigger_price=args.trigger_price,
            limit_price=args.limit_price,
            tif=args.tif,
            host=args.host,
            port=port,
            client_id=args.client_id,
        )
    except Exception as exc:
        print(f"Order was not submitted: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
