"""Agentic MS earnings pipeline: analyst agent predicts the earnings-day price
from your own net-income forecast, then the trading agent selects and explains
the best bull call spread structure against live IBKR quotes. Never places an
order unless --confirm is passed."""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from newstrading.common import save_json, utcnow_iso
from trading_config import get_strategy_config
from bullcallspread.analyst_agent import run_analyst_agent
from bullcallspread.config import MS_CONFIG
from bullcallspread.consensus import fetch_consensus
from bullcallspread.ibkr_data import fetch_recommendation_inputs
from bullcallspread.trading_agent import run_trading_agent

EARNINGS_VIEW_PATH = Path(__file__).resolve().parent / "my_earnings_view.json"
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "recommendations"
EXECUTION_DIR = Path(__file__).resolve().parent / "data" / "execution_reports"

# Same double gate as the scheduler: trading_config.json mode="live" AND this env var.
LIVE_CONFIRM_ENV = "BULLCALLSPREAD_LIVE_CONFIRM"


def _use_live() -> bool:
    cfg = get_strategy_config("bullcallspread")
    return cfg["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"


def load_earnings_view() -> dict:
    if not EARNINGS_VIEW_PATH.exists():
        raise RuntimeError(
            f"{EARNINGS_VIEW_PATH} does not exist. Copy my_earnings_view.example.json to "
            "my_earnings_view.json and fill in your own net-income prediction first."
        )
    with open(EARNINGS_VIEW_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the agentic MS earnings analyst + bull call spread trading agent pipeline.")
    parser.add_argument("--confirm", action="store_true", help="Place the combo order on IBKR paper trading (default: research only).")
    parser.add_argument("--client-id", type=int, default=47)
    args = parser.parse_args()

    live = _use_live()
    stamp = utcnow_iso().replace(":", "").replace("+00:00", "Z")
    try:
        earnings_view = load_earnings_view()
        consensus = fetch_consensus(MS_CONFIG.symbol)
        if not consensus.next_earnings_date:
            raise RuntimeError(f"no upcoming earnings date found for {MS_CONFIG.symbol}")

        analyst_prediction = run_analyst_agent(
            earnings_view["predicted_net_income_usd_billion"], earnings_view["quarter"],
            earnings_view.get("confidence_pct", 100), earnings_view.get("notes", ""), consensus,
            earnings_view.get("predicted_net_revenue_usd_billion"),
        )

        target_date = datetime.strptime(consensus.next_earnings_date, "%Y-%m-%d").date()
        account, spot, expiry, legs = fetch_recommendation_inputs(MS_CONFIG, target_date, args.client_id, live=live)

        trading_report = run_trading_agent(MS_CONFIG, analyst_prediction, account, spot, expiry, legs, MS_CONFIG.default_amount_usd)

        payload = {
            "generated_at": utcnow_iso(),
            "mode": "live_agentic_research" if live else "agentic_research",
            "account": account.__dict__,
            "spot_price": spot,
            "consensus": consensus.to_dict(),
            "analyst_prediction": analyst_prediction.to_dict(),
            "trading_agent": trading_report.to_dict(),
            "bull_call_spread": trading_report.recommendation.to_dict(),
        }
    except (TimeoutError, RuntimeError) as exc:
        payload = {"generated_at": utcnow_iso(), "mode": "agentic_research", "status": "data_unavailable", "reason": str(exc) or "pipeline failed"}
        trading_report = None

    output = OUTPUT_DIR / f"bullcallspread_{stamp}.json"
    save_json(output, payload)

    if trading_report is None:
        print(f"status: {payload['status']} ({payload['reason']})")
        print(f"-> {output}")
        return 0

    print("=== MS Stock Analyst Agent ===")
    print(f"Predicted price on {payload['analyst_prediction']['earnings_date']}: ${payload['analyst_prediction']['predicted_price']} "
          f"(range ${payload['analyst_prediction']['price_range_low']}-${payload['analyst_prediction']['price_range_high']}, "
          f"confidence {payload['analyst_prediction']['confidence']})")
    print(payload["analyst_prediction"]["consensus_summary"])
    for reason in payload["analyst_prediction"]["reasoning"]:
        print(f"  - {reason}")

    print("\n=== Bull Call Spread Trading Agent ===")
    rec = trading_report.recommendation
    print(f"action: {rec.action}")
    if rec.action == "BUY_BULL_CALL_SPREAD":
        print(f"long call: {rec.long_leg.strike} @ ask {rec.long_leg.ask}")
        print(f"short call: {rec.short_leg.strike} @ bid {rec.short_leg.bid}")
        print(f"contracts: {rec.contracts}, net debit: ${rec.net_debit:.2f}")
        print(f"max profit: ${rec.max_profit:.2f}, max loss: ${rec.max_loss:.2f}, breakeven: ${rec.breakeven:.2f}")
        for reason in trading_report.reasoning:
            print(f"  - {reason}")
        print("alternatives considered:")
        for alt in trading_report.alternatives_considered:
            print(f"  - {alt}")
        print(f"primary risk: {trading_report.primary_risk}")
        print("suggested exit plan:")
        for note in rec.exit_plan.notes:
            print(f"  - {note}")
    print(f"-> {output}")

    if args.confirm and rec.action == "BUY_BULL_CALL_SPREAD":
        from bullcallspread.execution import execute_bull_call_spread

        report = execute_bull_call_spread(MS_CONFIG, rec, args.client_id, live=live)
        exec_output = EXECUTION_DIR / f"bullcallspread_exec_{stamp}.json"
        save_json(exec_output, {"generated_at": utcnow_iso(), **report.to_dict()})
        print(f"execution: {report.status} ({report.reason})")
        print(f"-> {exec_output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
