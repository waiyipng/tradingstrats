"""CLI entry point for the Execution module.

Reads an order_recommendation.json artifact, runs final pre-trade risk checks,
routes to the paper or IBKR broker, and writes an execution_report.json artifact.

Usage:
    python -m newstrading.execution.run_execution --symbol AAPL --broker paper
    python -m newstrading.execution.run_execution --symbol AAPL --broker ibkr --execute
"""
from __future__ import annotations

import argparse

from newstrading.common import DATA_DIR, latest_artifact, load_json, save_json
from newstrading.audit import update_symbol
from newstrading.execution import risk_manager
from newstrading.execution.brokers import ibkr_broker, paper_broker
from newstrading.execution.position_monitor import track_entry
from newstrading.models.order_recommendation import OrderRecommendation


def main() -> int:
    parser = argparse.ArgumentParser(description="Execute (or paper-simulate) an order_recommendation.json.")
    parser.add_argument("--symbol", help="Use the latest order_recommendation.json for this symbol.")
    parser.add_argument("--recommendation-file", help="Path to a specific order_recommendation.json artifact.")
    parser.add_argument("--broker", choices=["paper", "ibkr"], default="paper")
    parser.add_argument("--execute", action="store_true", help="For --broker ibkr, actually submit the order (default is dry run).")
    parser.add_argument("--live", action="store_true", help="For --broker ibkr, use the live IBKR port instead of paper.")
    parser.add_argument("--client-id", type=int, default=22)
    parser.add_argument("--audit-run-id", help="Link this execution result to a scheduler audit run.")
    args = parser.parse_args()

    if not args.symbol and not args.recommendation_file:
        parser.error("Provide --symbol SYMBOL or --recommendation-file PATH")

    rec_path = args.recommendation_file or str(latest_artifact("order_recommendations", args.symbol))
    order = OrderRecommendation.from_dict(load_json(rec_path))

    open_notional = 0.0
    if args.broker == "ibkr" and order.action == "BUY":
        open_notional = ibkr_broker.open_buy_notional(live=args.live, client_id=args.client_id)
    passed, reasons = risk_manager.pre_trade_checks(order, open_buy_notional=open_notional)
    if not passed:
        print(f"Risk checks failed: {reasons}")

    if args.broker == "paper":
        report = paper_broker.execute(order, passed, reasons)
    else:
        report = ibkr_broker.execute(
            order, passed, reasons, live=args.live, client_id=args.client_id, dry_run=not args.execute
        )

    out_path = DATA_DIR / "execution_reports" / order.symbol / f"{report.execution_id}.json"
    save_json(out_path, report.to_dict())
    update_symbol(args.audit_run_id, order.symbol, execution=report.to_dict())
    if args.broker == "ibkr" and order.action == "BUY":
        track_entry(order, report)

    print(f"Execution for {order.symbol}: {report.status} ({report.broker})")
    print(f"  -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
