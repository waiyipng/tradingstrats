"""Paper-first VOO covered-call and cash-secured-put automation.

VOO options are physically settled. This manager therefore closes every short
option before expiration, rather than allowing assignment or exercise.

Examples:
    python voo_options_automation.py
    python voo_options_automation.py --execute
    python voo_options_automation.py --close --execute
    python voo_options_automation.py --live --execute
"""

import argparse
import sys
from datetime import date, datetime, timedelta

from ib_async import IB, LimitOrder, Option, Stock


TICKER = "VOO"
PAPER_PORT = 7497
LIVE_PORT = 7496
CONTRACT_SIZE = 100
DEFAULT_SHARES = 100
DEFAULT_DTE = 30
DEFAULT_OTM_PCT = 5.0
DEFAULT_CLOSE_DAYS = 2


def valid_quote(ticker):
    bid = float(ticker.bid) if ticker.bid and ticker.bid > 0 else 0.0
    ask = float(ticker.ask) if ticker.ask and ticker.ask > 0 else 0.0
    last = float(ticker.last) if ticker.last and ticker.last > 0 else 0.0
    if bid and ask:
        return bid, ask, (bid + ask) / 2
    if last:
        return bid, ask, last
    raise RuntimeError("No usable bid, ask, or last price was returned.")


def option_quote(ib, contract):
    ticker = ib.reqMktData(contract, snapshot=True)
    ib.sleep(2)
    return valid_quote(ticker)


def select_option(ib, underlying, right, spot, dte, otm_pct):
    chains = ib.reqSecDefOptParams(
        underlying.symbol, "", underlying.secType, underlying.conId
    )
    chains = [chain for chain in chains if chain.exchange == "SMART"] or chains
    if not chains:
        raise RuntimeError("No VOO option chains were returned.")
    chain = chains[0]

    target = date.today() + timedelta(days=dte)
    expirations = sorted(
        datetime.strptime(expiry, "%Y%m%d").date()
        for expiry in chain.expirations
        if datetime.strptime(expiry, "%Y%m%d").date() >= target
    )
    if not expirations:
        raise RuntimeError("No option expiration is available at or beyond the target date.")
    expiration = expirations[0].strftime("%Y%m%d")

    if right == "C":
        eligible = [strike for strike in chain.strikes if strike >= spot * (1 + otm_pct / 100)]
        strike = min(eligible) if eligible else None
    else:
        eligible = [strike for strike in chain.strikes if strike <= spot * (1 - otm_pct / 100)]
        strike = max(eligible) if eligible else None
    if strike is None:
        raise RuntimeError(f"No suitable {right} strike was returned for spot ${spot:.2f}.")

    contract = Option(
        TICKER, expiration, strike, right, "SMART",
        multiplier=chain.multiplier, currency="USD", tradingClass=chain.tradingClass,
    )
    qualified = ib.qualifyContracts(contract)
    if not qualified:
        raise RuntimeError(f"Could not qualify {right} option at strike {strike}.")
    return contract


def submit_open_orders(ib, args):
    underlying = Stock(TICKER, "SMART", "USD")
    if not ib.qualifyContracts(underlying):
        raise RuntimeError("Could not qualify VOO.")
    underlying_ticker = ib.reqMktData(underlying, snapshot=True)
    ib.sleep(2)
    _, _, spot = valid_quote(underlying_ticker)

    shares = args.shares - args.shares % CONTRACT_SIZE
    if shares < CONTRACT_SIZE:
        raise ValueError("--shares must be at least 100 and a multiple of 100.")
    contracts = shares // CONTRACT_SIZE
    call = select_option(ib, underlying, "C", spot, args.dte, args.otm_pct)
    put = select_option(ib, underlying, "P", spot, args.dte, args.otm_pct)
    call_bid, call_ask, call_mid = option_quote(ib, call)
    put_bid, put_ask, put_mid = option_quote(ib, put)

    print(f"VOO spot: ${spot:.2f}")
    print(f"Expiration: {call.lastTradeDateOrContractMonth}")
    print(f"Covered call: {call.localSymbol} | bid ${call_bid:.2f} / ask ${call_ask:.2f}")
    print(f"Cash-secured put: {put.localSymbol} | bid ${put_bid:.2f} / ask ${put_ask:.2f}")
    print(f"Put collateral target: ${put.strike * CONTRACT_SIZE * contracts:,.2f}")
    print(f"Sell-to-open quantity: {contracts} contract(s)")
    if not args.execute:
        print("DRY RUN: no orders submitted. Add --execute to place paper/live orders.")
        return

    call_trade = ib.placeOrder(call, LimitOrder("SELL", contracts, call_bid or call_mid))
    put_trade = ib.placeOrder(put, LimitOrder("SELL", contracts, put_bid or put_mid))
    print(f"Covered-call order ID: {call_trade.order.orderId} ({call_trade.orderStatus.status})")
    print(f"Cash-secured-put order ID: {put_trade.order.orderId} ({put_trade.orderStatus.status})")
    print("Record these option symbols/order IDs; run --close before expiration.")


def close_short_option(ib, symbol, expiration, strike, right, quantity, execute):
    contract = Option(symbol, expiration, strike, right, "SMART", multiplier="100", currency="USD")
    if not ib.qualifyContracts(contract):
        raise RuntimeError(f"Could not qualify {symbol} closing contract.")
    bid, ask, mid = option_quote(ib, contract)
    price = ask or mid or bid
    print(f"Close {contract.localSymbol}: ask ${ask:.2f}, limit ${price:.2f}")
    if execute:
        trade = ib.placeOrder(contract, LimitOrder("BUY", quantity, price))
        print(f"Buy-to-close order ID: {trade.order.orderId} ({trade.orderStatus.status})")


def roll_expired_short_options(ib, args):
    """Close any expired VOO short options and reopen the 30-day 5%-OTM cycle."""
    today = date.today()
    expired = []
    for position in ib.positions():
        contract = position.contract
        if contract.symbol != TICKER or contract.secType != "OPT" or position.position >= 0:
            continue
        expiration = datetime.strptime(contract.lastTradeDateOrContractMonth, "%Y%m%d").date()
        if expiration < today:
            expired.append((position, contract))

    if not expired:
        return False

    for position, contract in expired:
        quantity = int(abs(position.position))
        print(
            f"{contract.localSymbol}: expired on {contract.lastTradeDateOrContractMonth}; "
            f"closing {quantity} contract(s) and rolling into the next cycle."
        )
        close_short_option(
            ib, contract.symbol, contract.lastTradeDateOrContractMonth,
            contract.strike, contract.right, quantity, args.execute,
        )

    if args.execute:
        print("Expired VOO short options closed; rolling into fresh 30-day 5% OTM call/put positions.")
        submit_open_orders(ib, args)
    else:
        print("DRY RUN: expired options marked for rollover, but no new orders were submitted.")
    return True


def monitor_short_options(ib, args):
    """Close all short VOO options inside the expiration safety window and auto-roll on expiry."""
    print(f"Monitoring VOO short options; closing at <= {args.close_days} day(s) to expiration.")
    while True:
        today = date.today()
        found = False
        expired = roll_expired_short_options(ib, args)
        if expired:
            found = True
        for position in ib.positions():
            contract = position.contract
            if contract.symbol != TICKER or contract.secType != "OPT" or position.position >= 0:
                continue
            expiration = datetime.strptime(contract.lastTradeDateOrContractMonth, "%Y%m%d").date()
            days_left = (expiration - today).days
            if days_left > args.close_days:
                continue
            if days_left <= 0:
                continue
            found = True
            quantity = int(abs(position.position))
            print(f"{contract.localSymbol}: {days_left} day(s) left, closing {quantity} contract(s).")
            close_short_option(
                ib, contract.symbol, contract.lastTradeDateOrContractMonth,
                contract.strike, contract.right, quantity, args.execute,
            )
        if found and args.execute:
            print("Close/roll orders submitted. Rechecking on the next interval.")
        elif not found:
            print("No VOO short options require closing or rolling right now.")
        if not args.watch:
            return
        ib.sleep(args.interval)
        ib.reqPositions()


def main():
    parser = argparse.ArgumentParser(description="Manage VOO 5%%-OTM options without physical settlement.")
    parser.add_argument("--shares", type=int, default=DEFAULT_SHARES)
    parser.add_argument("--dte", type=int, default=DEFAULT_DTE)
    parser.add_argument("--otm-pct", type=float, default=DEFAULT_OTM_PCT)
    parser.add_argument("--close-days", type=int, default=DEFAULT_CLOSE_DAYS)
    parser.add_argument("--close", action="store_true", help="Buy-to-close supplied short option details.")
    parser.add_argument("--monitor", action="store_true", help="Scan positions and close short VOO options near expiration.")
    parser.add_argument("--roll", action="store_true", help="Open the 30-day 5%%-OTM VOO call/put cycle and continuously auto-roll expired positions.")
    parser.add_argument("--watch", action="store_true", help="Keep monitoring instead of performing one scan.")
    parser.add_argument("--interval", type=int, default=300, help="Monitor interval in seconds.")
    parser.add_argument("--symbol")
    parser.add_argument("--expiration", help="YYYYMMDD expiration for --close")
    parser.add_argument("--strike", type=float)
    parser.add_argument("--right", choices=("C", "P"))
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--client-id", type=int, default=10)
    parser.add_argument("--live", action="store_true", help="Use live port 7496 instead of paper port 7497.")
    parser.add_argument("--execute", action="store_true", help="Actually submit orders; default is dry run.")
    args = parser.parse_args()

    if args.otm_pct <= 0 or args.dte <= 0 or args.close_days < 1:
        parser.error("--otm-pct, --dte, and --close-days must be positive")
    if args.close and not all((args.symbol, args.expiration, args.strike, args.right)):
        parser.error("--close requires --symbol, --expiration, --strike, and --right")
    if args.watch and not (args.monitor or args.roll):
        parser.error("--watch requires --monitor or --roll")
    if args.interval < 10:
        parser.error("--interval must be at least 10 seconds")

    ib = IB()
    port = LIVE_PORT if args.live else PAPER_PORT
    try:
        print(f"Connecting to {'LIVE' if args.live else 'PAPER'} IBKR at {args.host}:{port}...")
        ib.connect(args.host, port, clientId=args.client_id)
        if args.close:
            close_short_option(ib, args.symbol, args.expiration, args.strike, args.right, args.quantity, args.execute)
        elif args.roll:
            submit_open_orders(ib, args)
            monitor_short_options(ib, args)
        elif args.monitor:
            monitor_short_options(ib, args)
        else:
            submit_open_orders(ib, args)
    except Exception as exc:
        print(f"Automation failed: {exc}", file=sys.stderr)
        return 1
    finally:
        if ib.isConnected():
            ib.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())