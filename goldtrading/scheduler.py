"""Automated paper-only gold carry/calendar-spread recommendation and execution scheduler."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from newstrading.common import save_json, utcnow_iso
from goldtrading.config import GOLD_CONFIG
from goldtrading.execution import execute_calendar_spread, execute_cash_and_carry
from goldtrading.ibkr_data import fetch_market_snapshot
from goldtrading.monitor import run_monitor_cycle
from goldtrading.state import load_state, open_position_count
from goldtrading.strategy import evaluate_calendar_spread, evaluate_cash_and_carry

RUN_INTERVAL_MINUTES = 30
CLIENT_ID = 46
LOG_PATH = Path(__file__).resolve().parent / "gold_scheduler.log"
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "automated_runs"

logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s gold-scheduler - %(message)s")
logger = logging.getLogger("gold-scheduler")


def run_cycle() -> None:
    payload: dict[str, object] = {"generated_at": utcnow_iso(), "mode": "paper_automated"}
    try:
        payload["monitor"] = run_monitor_cycle(GOLD_CONFIG, CLIENT_ID)
        account, snapshot = fetch_market_snapshot(GOLD_CONFIG, CLIENT_ID)
        open_positions = open_position_count(load_state())

        carry_recommendation = evaluate_cash_and_carry(GOLD_CONFIG, account, snapshot, open_positions)
        carry_execution = execute_cash_and_carry(GOLD_CONFIG, carry_recommendation, CLIENT_ID)
        if carry_execution.get("status") == "SUBMITTED":
            open_positions += 1

        calendar_recommendation = evaluate_calendar_spread(GOLD_CONFIG, account, snapshot, open_positions)
        calendar_execution = execute_calendar_spread(GOLD_CONFIG, calendar_recommendation, CLIENT_ID)

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
    logger.info("Starting automated IBKR paper gold scheduler every %d minutes", RUN_INTERVAL_MINUTES)
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, IntervalTrigger(minutes=RUN_INTERVAL_MINUTES), id="gold_cycle", max_instances=1, replace_existing=True)
    scheduler.start()


if __name__ == "__main__":
    main()
