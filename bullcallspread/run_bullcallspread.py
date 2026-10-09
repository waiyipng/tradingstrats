"""Research an MS bull call spread for a target price/date/amount; place the combo order only with --confirm."""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from pathlib import Path

from newstrading.common import save_json, utcnow_iso
from trading_config import get_strategy_config
from bullcallspread.config import MS_CONFIG
from bullcallspread.ibkr_data import fetch_recommendation_inputs
from bullcallspread.strategy import evaluate_bull_call_spread

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "recommendations"
EXECUTION_DIR = Path(__file__).resolve().parent / "data" / "execution_reports"

LIVE_CONFIRM_ENV = "BULLCALLSPREAD_LIVE_CONFIRM"


def _use_live() -> bool:
    cfg = get_strategy_config("bullcallspread")
    return cfg["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Research (and optionally place) an MS bull call spread.")
    parser.add_argument("--target-price", type=float, default=MS_CONFIG.target_price, help=f"Price you expect MS to reach by --target-date (default: {MS_CONFIG.target_price}).")
    parser.add_argument("--target-date", type=str, default=MS_CONFIG.target_date, help=f"YYYY-MM-DD date by which you expect the target price (default: {MS_CONFIG.target_date}).")
    parser.add_argument("--amount", type=float, default=MS_CONFIG.default_amount_usd, help=f"Dollar amount to deploy into the spread (default: {MS_CONFIG.default_amount_usd}).")
    parser.add_argument("--confirm", action="store_true", help="Place the combo order on IBKR paper trading (default: research only).")
    parser.add_argument("--client-id", type=int, default=47)
    args = parser.parse_args()

    target_date = datetime.strptime(args.target_date, "%Y-%m-%d").date()
    live = _use_live()

    try:
        account, spot, expiry, legs = fetch_recommendation_inputs(MS_CONFIG, target_date, args.client_id, live=live)
        recommendation = evaluate_bull_call_spread(
            MS_CONFIG, account, spot, expiry, legs, args.target_price, args.target_date, args.amount
        )
        payload = {
            "generated_at": utcnow_iso(),
            "mode": "live_recommendation_only" if live else "recommendation_only",
            "account": account.__dict__,
            "spot_price": spot,
            "bull_call_spread": recommendation.to_dict(),
        }
    except (TimeoutError, RuntimeError) as exc:
        reason = str(exc) or "IBKR market-data request timed out"
        payload = {"generated_at": utcnow_iso(), "mode": "recommendation_only", "status": "data_unavailable", "reason": reason}
        recommendation = None

    stamp = utcnow_iso().replace(":", "").replace("+00:00", "Z")
    output = OUTPUT_DIR / f"bullcallspread_{stamp}.json"
    save_json(output, payload)

    if recommendation is None:
        print(f"status: {payload['status']} ({payload['reason']})")
        print(f"-> {output}")
        return 0

    print(f"action: {recommendation.action}")
    if recommendation.action == "BUY_BULL_CALL_SPREAD":
        print(f"long call: {recommendation.long_leg.strike} @ ask {recommendation.long_leg.ask}")
        print(f"short call: {recommendation.short_leg.strike} @ bid {recommendation.short_leg.bid}")
        print(f"contracts: {recommendation.contracts}, net debit: ${recommendation.net_debit:.2f}")
        print(f"max profit: ${recommendation.max_profit:.2f}, max loss: ${recommendation.max_loss:.2f}, breakeven: ${recommendation.breakeven:.2f}")
        print("payoff ladder:")
        for point in recommendation.payoff_ladder:
            print(f"  {point.label:>16} (${point.price:.2f}): ${point.profit_loss:.2f}")
        print("suggested exit plan:")
        for note in recommendation.exit_plan.notes:
            print(f"  - {note}")
    else:
        print(f"reasons: {'; '.join(recommendation.reasons)}")
    print(f"-> {output}")

    if args.confirm and recommendation is not None and recommendation.action == "BUY_BULL_CALL_SPREAD":
        from bullcallspread.execution import execute_bull_call_spread

        report = execute_bull_call_spread(MS_CONFIG, recommendation, args.client_id, live=live)
        exec_output = EXECUTION_DIR / f"bullcallspread_exec_{stamp}.json"
        save_json(exec_output, {"generated_at": utcnow_iso(), **report.to_dict()})
        print(f"execution: {report.status} ({report.reason})")
        print(f"-> {exec_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
