"""Generate read-only IBKR gold carry/calendar-spread recommendations (paper or live); never submits orders."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from newstrading.common import save_json, utcnow_iso
from trading_config import get_strategy_config
from goldtrading.config import GOLD_CONFIG
from goldtrading.ibkr_data import fetch_market_snapshot
from goldtrading.state import load_state, open_position_count
from goldtrading.strategy import evaluate_calendar_spread, evaluate_cash_and_carry

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "recommendations"

# Same double gate as the scheduler: trading_config.json mode="live" AND this env var.
LIVE_CONFIRM_ENV = "GOLDTRADING_LIVE_CONFIRM"


def _use_live() -> bool:
    cfg = get_strategy_config("goldtrading")
    return cfg["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate read-only IBKR gold carry/calendar-spread recommendations (paper, or live if trading_config.json and GOLDTRADING_LIVE_CONFIRM both enable it).")
    parser.add_argument("--client-id", type=int, default=42)
    args = parser.parse_args()

    live = _use_live()
    try:
        account, snapshot = fetch_market_snapshot(GOLD_CONFIG, args.client_id, live=live)
        open_positions = open_position_count(load_state())
        carry = evaluate_cash_and_carry(GOLD_CONFIG, account, snapshot, open_positions)
        calendar = evaluate_calendar_spread(GOLD_CONFIG, account, snapshot, open_positions)
        payload = {
            "generated_at": utcnow_iso(),
            "mode": "live_recommendation_only" if live else "recommendation_only",
            "account": account.__dict__,
            "cash_and_carry": carry.to_dict(),
            "calendar_spread": calendar.to_dict(),
        }
    except (TimeoutError, RuntimeError) as exc:
        reason = str(exc) or "IBKR gold market-data request timed out"
        payload = {"generated_at": utcnow_iso(), "mode": "live_recommendation_only" if live else "recommendation_only", "status": "data_unavailable", "reason": reason}

    output = OUTPUT_DIR / f"gold_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
    save_json(output, payload)
    print(f"cash_and_carry: {payload.get('cash_and_carry', {}).get('action', payload.get('status'))}")
    print(f"calendar_spread: {payload.get('calendar_spread', {}).get('action', payload.get('status'))}")
    print(f"-> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
