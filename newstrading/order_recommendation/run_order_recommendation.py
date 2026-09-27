"""CLI entry point for the Order Recommendation module.

Reads a trading_signal.json artifact, pulls a live IBKR account snapshot (cash,
net liquidation, existing position), applies sizing/risk rules, and writes an
order_recommendation.json artifact.

Usage:
    python -m newstrading.order_recommendation.run_order_recommendation --symbol AAPL
    python -m newstrading.order_recommendation.run_order_recommendation --symbol AAPL --live
    python -m newstrading.order_recommendation.run_order_recommendation --symbol AAPL --mock-account
"""
from __future__ import annotations

import argparse

from newstrading.common import DATA_DIR, latest_artifact, load_json, save_json
from newstrading.audit import update_symbol
from newstrading.config.loader import get_symbol_entry
from newstrading.models.order_recommendation import AccountSnapshot
from newstrading.models.signal import TradingSignal
from newstrading.order_recommendation import ibkr_account
from newstrading.order_recommendation.sizing import recommend_order


def main() -> int:
    parser = argparse.ArgumentParser(description="Turn a trading_signal.json into an order_recommendation.json.")
    parser.add_argument("--symbol", help="Use the latest trading_signal.json for this symbol.")
    parser.add_argument("--signal-file", help="Path to a specific trading_signal.json artifact.")
    parser.add_argument("--live", action="store_true", help="Query the live IBKR account instead of paper.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--client-id", type=int, default=21)
    parser.add_argument("--audit-run-id", help="Link this recommendation to a scheduler audit run.")
    parser.add_argument(
        "--mock-account",
        action="store_true",
        help="Skip the IBKR connection and use a placeholder account snapshot (for testing without TWS running).",
    )
    args = parser.parse_args()

    if not args.symbol and not args.signal_file:
        parser.error("Provide --symbol SYMBOL or --signal-file PATH")

    signal_path = args.signal_file or str(latest_artifact("signals", args.symbol))
    signal = TradingSignal.from_dict(load_json(signal_path))
    entry = get_symbol_entry(signal.symbol)

    if args.mock_account:
        account = AccountSnapshot(cash=100_000.0, net_liquidation=100_000.0, existing_position_qty=0)
    else:
        with ibkr_account.connect(host=args.host, live=args.live, client_id=args.client_id) as ib:
            account = ibkr_account.get_account_snapshot(ib, signal.symbol)

    recommendation = recommend_order(signal, account, entry["sector"])
    update_symbol(
        args.audit_run_id,
        signal.symbol,
        recommendation={"order": recommendation.to_dict(), "account_snapshot": recommendation.account_snapshot.__dict__},
    )

    out_path = DATA_DIR / "order_recommendations" / signal.symbol / f"{recommendation.recommendation_id}.json"
    save_json(out_path, recommendation.to_dict())

    print(f"Order recommendation for {signal.symbol}: {recommendation.action} qty={recommendation.qty}")
    print(f"  -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
