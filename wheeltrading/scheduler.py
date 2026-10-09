"""Automated paper-only wheel recommendation and execution scheduler."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler

from newstrading.common import save_json, utcnow_iso
from trading_config import get_strategy_config
from wheeltrading.approval import clear_pending, is_expired, load_pending, save_pending
from wheeltrading.config import WHEEL_CONFIGS, get_config
from wheeltrading.ibkr_data import fetch_recommendation_inputs
from wheeltrading.schedule import scan_trigger
from wheeltrading.strategy import recommend_wheel_action

_CFG = get_strategy_config("wheeltrading")
RUN_INTERVAL_MINUTES = _CFG["run_interval_minutes"]
CLIENT_ID = 45

# Live execution requires BOTH trading_config.json mode="live" AND this env var set to
# "1" on the process running the scheduler, so a config edit alone can never flip an
# unattended scheduler to live order submission. Per CLAUDE.md this must stay gated
# behind an explicit, separate confirmation, not a config flag alone.
LIVE_CONFIRM_ENV = "WHEELTRADING_LIVE_CONFIRM"
USE_LIVE_IBKR = _CFG["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"

LOG_PATH = Path(__file__).resolve().parent / "wheel_scheduler.log"
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "automated_runs"

logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s wheel-scheduler - %(message)s")
logger = logging.getLogger("wheel-scheduler")

if _CFG["mode"] == "live" and not USE_LIVE_IBKR:
    logger.warning(
        "trading_config.json requests mode=live for wheeltrading but %s is not set to '1'; "
        "staying on paper trading.", LIVE_CONFIRM_ENV,
    )


def run_cycle() -> None:
    for symbol in WHEEL_CONFIGS:
        config = get_config(symbol)
        payload: dict[str, object] = {"generated_at": utcnow_iso(), "symbol": symbol, "mode": "live_automated" if USE_LIVE_IBKR else "paper_automated"}
        try:
            account, quotes = fetch_recommendation_inputs(symbol, config.min_days_to_expiry, config.max_days_to_expiry, config.target_otm_pct, CLIENT_ID, live=USE_LIVE_IBKR)
            recommendation = recommend_wheel_action(config, account, quotes)
            if recommendation.action == "HOLD":
                clear_pending(symbol)  # a flattened recommendation drops any stale pending order
                execution = {"status": "SKIPPED", "reason": "no actionable wheel recommendation"}
            else:
                # Orders are never submitted automatically: a human must approve this
                # recommendation (e.g. from the dashboard) before anything reaches IBKR.
                pending = load_pending(symbol)
                if pending is not None and is_expired(pending):
                    clear_pending(symbol)
                    pending = None
                if pending is None:
                    pending = save_pending(symbol, recommendation)
                execution = {"status": "PENDING_APPROVAL", "reason": f"awaiting human approval (expires {pending['expires_at']})"}
            payload.update({"account": account.__dict__, "quotes_considered": len(quotes), "recommendation": recommendation.to_dict(), "execution": execution})
        except Exception as exc:
            payload.update({"status": "data_unavailable", "reason": str(exc) or "IBKR option-chain market-data request timed out"})
        path = OUTPUT_DIR / f"wheel_run_{symbol}_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
        save_json(path, payload)
        logger.info("%s -> %s", symbol, json.dumps(payload, default=str))


def main() -> None:
    logger.info("Starting automated IBKR %s wheel scheduler every %d minutes, Mon-Fri 9:30am-4:00pm ET only (orders require human approval)", "live" if USE_LIVE_IBKR else "paper", RUN_INTERVAL_MINUTES)
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, scan_trigger(RUN_INTERVAL_MINUTES), id="wheel_cycle", max_instances=1, replace_existing=True)
    scheduler.start()


if __name__ == "__main__":
    main()