"""Automated paper-only wheel recommendation and execution scheduler."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from newstrading.common import save_json, utcnow_iso
from wheeltrading.config import WHEEL_CONFIGS, get_config
from wheeltrading.execution import execute_paper
from wheeltrading.ibkr_data import fetch_recommendation_inputs
from wheeltrading.strategy import recommend_wheel_action

RUN_INTERVAL_MINUTES = 30
CLIENT_ID = 45
LOG_PATH = Path(__file__).resolve().parent / "wheel_scheduler.log"
OUTPUT_DIR = Path(__file__).resolve().parent / "data" / "automated_runs"

logging.basicConfig(filename=LOG_PATH, level=logging.INFO, format="%(asctime)s %(levelname)s wheel-scheduler - %(message)s")
logger = logging.getLogger("wheel-scheduler")


def run_cycle() -> None:
    for symbol in WHEEL_CONFIGS:
        config = get_config(symbol)
        payload: dict[str, object] = {"generated_at": utcnow_iso(), "symbol": symbol, "mode": "paper_automated"}
        try:
            account, quotes = fetch_recommendation_inputs(symbol, config.min_days_to_expiry, config.max_days_to_expiry, config.target_otm_pct, CLIENT_ID)
            recommendation = recommend_wheel_action(config, account, quotes)
            payload.update({"account": account.__dict__, "quotes_considered": len(quotes), "recommendation": recommendation.to_dict(), "execution": execute_paper(recommendation, CLIENT_ID)})
        except Exception as exc:
            payload.update({"status": "data_unavailable", "reason": str(exc) or "IBKR option-chain market-data request timed out"})
        path = OUTPUT_DIR / f"wheel_run_{symbol}_{utcnow_iso().replace(':', '').replace('+00:00', 'Z')}.json"
        save_json(path, payload)
        logger.info("%s -> %s", symbol, json.dumps(payload, default=str))


def main() -> None:
    logger.info("Starting automated IBKR paper wheel scheduler every %d minutes", RUN_INTERVAL_MINUTES)
    scheduler = BlockingScheduler()
    scheduler.add_job(run_cycle, IntervalTrigger(minutes=RUN_INTERVAL_MINUTES), id="wheel_cycle", max_instances=1, replace_existing=True)
    scheduler.start()


if __name__ == "__main__":
    main()