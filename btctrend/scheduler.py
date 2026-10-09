"""Automated IBKR paper-only BTC trend-following scheduler.

Bitcoin trades every day, so this runs every 5 minutes around the clock. The
signal only changes when a new daily bar completes (00:00 UTC); every cycle
re-evaluates the trailing stop against the live bid. No order reaches IBKR
automatically: a BUY/SELL recommendation is queued as a pending approval
(btctrend/approval.py) for a human to approve or reject, e.g. from the
dashboard's BTC panel. An unapproved recommendation expires after
approval.APPROVAL_WINDOW_MINUTES and the next cycle re-evaluates fresh.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from newstrading.common import save_json, utcnow_iso
from trading_config import get_strategy_config
from btctrend.config import BTC_CONFIG, RUN_INTERVAL_MINUTES
from btctrend.pipeline import run_cycle as run_pipeline_cycle

CLIENT_ID = 49
EXECUTE = True

# Live execution requires BOTH trading_config.json mode="live" AND this env var set to
# "1" on the process running the scheduler, so a config edit alone can never flip an
# unattended scheduler to live order submission.
_CFG = get_strategy_config("btctrend")
LIVE_CONFIRM_ENV = "BTCTREND_LIVE_CONFIRM"
USE_LIVE_IBKR = _CFG["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"

LOG_PATH = Path(__file__).resolve().parent / "btctrend_scheduler.log"
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "automated_runs"

logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s btctrend-scheduler - %(message)s")
logger = logging.getLogger("btctrend-scheduler")

if _CFG["mode"] == "live" and not USE_LIVE_IBKR:
    logger.warning(
        "trading_config.json requests mode=live for btctrend but %s is not set to '1'; "
        "staying on paper trading.", LIVE_CONFIRM_ENV,
    )


def run_cycle() -> None:
    payload = run_pipeline_cycle(BTC_CONFIG, CLIENT_ID, execute=EXECUTE, live=USE_LIVE_IBKR)
    path = OUTPUT_DIR / f"btctrend_run_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
    save_json(path, payload)
    logger.info("btctrend cycle -> %s", json.dumps(payload, default=str))


def main() -> None:
    logger.info("Starting automated IBKR %s BTC trend scheduler every %d minutes (execute=%s)", "live" if USE_LIVE_IBKR else "paper", RUN_INTERVAL_MINUTES, EXECUTE)
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, IntervalTrigger(minutes=RUN_INTERVAL_MINUTES), id="btctrend_cycle", max_instances=1, replace_existing=True)
    scheduler.start()


if __name__ == "__main__":
    main()
