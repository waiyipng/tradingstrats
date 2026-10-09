"""Manual BTC trend cycle: prints the ensemble signal, the trailing stop, and the
rebalance the rules produce. Places a paper order only with --confirm.

    /usr/local/bin/python3 -m btctrend.run_btctrend [--confirm]
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from newstrading.common import save_json, utcnow_iso
from trading_config import get_strategy_config
from btctrend.config import BTC_CONFIG
from btctrend.pipeline import run_cycle

OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "manual_runs"
LIVE_CONFIRM_ENV = "BTCTREND_LIVE_CONFIRM"


def _use_live() -> bool:
    cfg = get_strategy_config("btctrend")
    return cfg["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one BTC trend-following cycle against IBKR paper (or live, if trading_config.json and BTCTREND_LIVE_CONFIRM both enable it).")
    parser.add_argument("--confirm", action="store_true", help="Submit the rebalance to IBKR (default: research only).")
    parser.add_argument("--client-id", type=int, default=50)
    args = parser.parse_args()

    payload = run_cycle(BTC_CONFIG, args.client_id, execute=args.confirm, live=_use_live())
    output = OUTPUT_DIR / f"btctrend_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
    save_json(output, payload)

    signal = payload.get("signal")
    if signal:
        print(f"=== BTC trend signal ({signal['bar_date']} close {signal['close']:,.2f}) ===")
        for vote in signal["votes"]:
            print(f"  {'LONG' if vote['long'] else 'flat':4s}  {vote['name']:16s} {vote['detail']}")
        print(f"score {signal['score']:.2f} x vol scalar {signal['vol_scalar']:.2f} (30d vol {signal['realized_vol_annual']:.0%}) "
              f"= target exposure {signal['target_exposure']:.0%}")
    if payload.get("status") == "data_unavailable":
        print(f"status: data_unavailable ({payload['reason']})")
        print(f"-> {output}")
        return 0

    rec = payload["recommendation"]
    print(f"\n=== Rebalance: {rec['action']} ===")
    for reason in rec["reasons"]:
        print(f"  - {reason}")
    print(f"execution: {payload['execution']['status']} ({payload['execution'].get('reason', '')})")

    print(f"-> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
