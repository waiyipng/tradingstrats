"""Automated paper-only gold carry/calendar-spread recommendation and execution scheduler."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from newstrading.common import save_json, utcnow_iso
from trading_config import get_strategy_config
from goldtrading.config import GOLD_CONFIG
from goldtrading.execution import execute_calendar_spread, execute_cash_and_carry
from goldtrading.ibkr_data import fetch_market_snapshot
from goldtrading.monitor import run_monitor_cycle
from goldtrading.state import load_state, open_position_count
from goldtrading.strategy import evaluate_calendar_spread, evaluate_cash_and_carry

_CFG = get_strategy_config("goldtrading")
RUN_INTERVAL_MINUTES = _CFG["run_interval_minutes"]
CLIENT_ID = 46

# Live execution requires BOTH trading_config.json mode="live" AND this env var set to
# "1" on the process running the scheduler, so a config edit alone can never flip an
# unattended scheduler to live order submission.
LIVE_CONFIRM_ENV = "GOLDTRADING_LIVE_CONFIRM"
USE_LIVE_IBKR = _CFG["mode"] == "live" and os.environ.get(LIVE_CONFIRM_ENV) == "1"

LOG_PATH = Path(__file__).resolve().parent / "gold_scheduler.log"
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "automated_runs"

logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s gold-scheduler - %(message)s")
logger = logging.getLogger("gold-scheduler")

if _CFG["mode"] == "live" and not USE_LIVE_IBKR:
    logger.warning(
        "trading_config.json requests mode=live for goldtrading but %s is not set to '1'; "
        "staying on paper trading.", LIVE_CONFIRM_ENV,
    )


def run_cycle() -> None:
    payload: dict[str, object] = {"generated_at": utcnow_iso(), "mode": "live_automated" if USE_LIVE_IBKR else "paper_automated"}
    try:
        payload["monitor"] = run_monitor_cycle(GOLD_CONFIG, CLIENT_ID, live=USE_LIVE_IBKR)
        account, snapshot = fetch_market_snapshot(GOLD_CONFIG, CLIENT_ID, live=USE_LIVE_IBKR)
        open_positions = open_position_count(load_state())

        from goldtrading.approval import is_expired, load_pending

        existing_pending = load_pending() if USE_LIVE_IBKR else None
        if existing_pending is not None and is_expired(existing_pending):
            existing_pending = None
        skip_new_entries = existing_pending is not None

        carry_recommendation = evaluate_cash_and_carry(GOLD_CONFIG, account, snapshot, open_positions)
        if skip_new_entries:
            carry_execution = {"status": "SKIPPED", "reason": "an order is already pending human approval"}
        elif USE_LIVE_IBKR and carry_recommendation.action != "HOLD":
            from goldtrading.approval import save_pending

            save_pending("entry_cash_and_carry", {"recommendation": carry_recommendation.to_dict()})
            carry_execution = {"status": "PENDING_APPROVAL", "reason": "live cash-and-carry entry queued for human approval"}
        else:
            carry_execution = execute_cash_and_carry(GOLD_CONFIG, carry_recommendation, CLIENT_ID, live=USE_LIVE_IBKR)
        if carry_execution.get("status") == "SUBMITTED":
            open_positions += 1

        calendar_recommendation = evaluate_calendar_spread(GOLD_CONFIG, account, snapshot, open_positions)
        if skip_new_entries:
            calendar_execution = {"status": "SKIPPED", "reason": "an order is already pending human approval"}
        elif USE_LIVE_IBKR and calendar_recommendation.action != "HOLD":
            from goldtrading.approval import save_pending

            save_pending("entry_calendar_spread", {"recommendation": calendar_recommendation.to_dict()})
            calendar_execution = {"status": "PENDING_APPROVAL", "reason": "live calendar-spread entry queued for human approval"}
        else:
            calendar_execution = execute_calendar_spread(GOLD_CONFIG, calendar_recommendation, CLIENT_ID, live=USE_LIVE_IBKR)

        payload.update(
            {
                "account": account.__dict__,
                "spot": snapshot.spot.__dict__,
                "near_future": snapshot.near_future.__dict__ if snapshot.near_future else None,
                "far_future": snapshot.far_future.__dict__ if snapshot.far_future else None,
                "cash_and_carry": {"recommendation": carry_recommendation.to_dict(), "execution": carry_execution},
                "calendar_spread": {"recommendation": calendar_recommendation.to_dict(), "execution": calendar_execution},
            }
        )
    except Exception as exc:
        payload.update({"status": "data_unavailable", "reason": str(exc) or "IBKR gold market-data request timed out"})
    path = OUTPUT_DIR / f"gold_run_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
    save_json(path, payload)
    logger.info("gold cycle -> %s", json.dumps(payload, default=str))


def main() -> None:
    logger.info("Starting automated IBKR %s gold scheduler every %d minutes", "live" if USE_LIVE_IBKR else "paper", RUN_INTERVAL_MINUTES)
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, IntervalTrigger(minutes=RUN_INTERVAL_MINUTES), id="gold_cycle", max_instances=1, replace_existing=True)
    scheduler.start()


if __name__ == "__main__":
    main()
