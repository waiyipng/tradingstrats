"""Create paper-safe wheel strategy recommendations; never submits options orders."""
from __future__ import annotations

import argparse
from pathlib import Path

from newstrading.common import save_json, utcnow_iso
from wheeltrading.config import WHEEL_CONFIGS, get_config
from wheeltrading.ibkr_data import fetch_recommendation_inputs
from wheeltrading.strategy import recommend_wheel_action

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "recommendations"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate read-only IBKR paper wheel recommendations.")
    parser.add_argument("--symbol", choices=sorted(WHEEL_CONFIGS))
    parser.add_argument("--all", action="store_true", help="Evaluate GOOGL and VOO.")
    parser.add_argument("--client-id", type=int, default=41)
    args = parser.parse_args()
    if not args.symbol and not args.all:
        parser.error("Provide --symbol or --all")

    symbols = [args.symbol] if args.symbol else sorted(WHEEL_CONFIGS)
    for symbol in symbols:
        config = get_config(symbol)
        try:
            account, quotes = fetch_recommendation_inputs(
                symbol,
                config.min_days_to_expiry,
                config.max_days_to_expiry,
                config.target_otm_pct,
                args.client_id,
            )
            recommendation = recommend_wheel_action(config, account, quotes)
            payload = {"generated_at": utcnow_iso(), "mode": "recommendation_only", "account": account.__dict__, "quotes_considered": len(quotes), "recommendation": recommendation.to_dict()}
        except (TimeoutError, RuntimeError) as exc:
            reason = str(exc) or "IBKR option-chain market-data request timed out"
            payload = {"generated_at": utcnow_iso(), "mode": "recommendation_only", "status": "data_unavailable", "symbol": symbol, "reason": reason}
        output = OUTPUT_DIR / f"wheel_{symbol}_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
        save_json(output, payload)
        print(f"{symbol}: {payload.get('recommendation', {}).get('action', payload.get('status'))} -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())