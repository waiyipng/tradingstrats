"""Generate read-only IBKR paper gold carry/calendar-spread recommendations; never submits orders."""
from __future__ import annotations

import argparse
from pathlib import Path

from newstrading.common import save_json, utcnow_iso
from goldtrading.config import GOLD_CONFIG
from goldtrading.ibkr_data import fetch_market_snapshot
from goldtrading.state import load_state, open_position_count
from goldtrading.strategy import evaluate_calendar_spread, evaluate_cash_and_carry

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "recommendations"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate read-only IBKR paper gold carry/calendar-spread recommendations.")
    parser.add_argument("--client-id", type=int, default=42)
    args = parser.parse_args()

    try:
        account, snapshot = fetch_market_snapshot(GOLD_CONFIG, args.client_id)
        open_positions = open_position_count(load_state())
        carry = evaluate_cash_and_carry(GOLD_CONFIG, account, snapshot, open_positions)
        calendar = evaluate_calendar_spread(GOLD_CONFIG, account, snapshot, open_positions)
        payload = {
            "generated_at": utcnow_iso(),
            "mode": "recommendation_only",
            "account": account.__dict__,
            "cash_and_carry": carry.to_dict(),
            "calendar_spread": calendar.to_dict(),
        }
    except (TimeoutError, RuntimeError) as exc:
        reason = str(exc) or "IBKR gold market-data request timed out"
        payload = {"generated_at": utcnow_iso(), "mode": "recommendation_only", "status": "data_unavailable", "reason": reason}

    output = OUTPUT_DIR / f"gold_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
    save_json(output, payload)
    print(f"cash_and_carry: {payload.get('cash_and_carry', {}).get('action', payload.get('status'))}")
    print(f"calendar_spread: {payload.get('calendar_spread', {}).get('action', payload.get('status'))}")
    print(f"-> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
