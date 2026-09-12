"""APScheduler wrapper for VOO options automation

- Schedules two jobs by default:
  1) daily_roll_job: runs shortly after market close (US/Eastern) to open/roll the
     30-day 5%-OTM covered-call & cash-secured-put cycle.
  2) hourly_monitor_job: runs hourly to scan positions and close short options
     that are within the safety window.

Design decisions
- Runs the existing CLI script `voo_options_automation.py` as a subprocess using
  the same Python interpreter (sys.executable). This keeps the scheduler lightweight
  and avoids sharing long-lived IB sessions between jobs.
- Default behavior is DRY-RUN. Set EXECUTE=True in the CONFIG section below to
  allow the scheduler to submit orders.
- Logs stdout/stderr from each run to scheduler.log in the repo.
- Retries failed runs up to 3 times with exponential backoff.

Usage
1. Install dependencies:
   pip install APScheduler pytz

2. Edit the CONFIG section below to choose live vs paper, execution mode, and
   the schedule times.

3. Run the scheduler daemon interactively or use your OS service manager to
   run it at startup. Example quick run:
   python scheduler.py

"""

from datetime import datetime
import os
import shlex
import subprocess
import sys
import time
import logging

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
except Exception:  # pragma: no cover - import error handled at runtime
    raise SystemExit("APScheduler is required. Install with: pip install APScheduler")

try:
    import pytz
    TZ = pytz.timezone("US/Eastern")
except Exception:
    TZ = None

# ---------------------------------------------------------------------------
# CONFIG - adjust these to taste
# ---------------------------------------------------------------------------
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
SCRIPT = os.path.join(REPO_DIR, "voo_options_automation.py")
LOG_FILE = os.path.join(REPO_DIR, "scheduler.log")

# Set to True only after you have validated dry-runs and are ready to submit orders
EXECUTE = False
# Set True to use live IB port; otherwise script defaults to paper if not set
USE_LIVE = False

# Daily roll job: run shortly after market close in US/Eastern (example: 17:50)
DAILY_ROLL_CRON = {"hour": 17, "minute": 50}  # time in US/Eastern
# Hourly monitor job: check every hour for options that should be closed
MONITOR_INTERVAL_MINUTES = 60

# Retry behavior
MAX_RETRIES = 3
RETRY_BASE_SECONDS = 10

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("voo-scheduler")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def build_cmd(mode: str) -> str:
    """Return a command string to run the automation script.

    mode: one of 'roll' or 'monitor'
    """
    args = [shlex.quote(PYTHON), shlex.quote(SCRIPT)]
    if mode == "roll":
        args.append("--roll")
    elif mode == "monitor":
        args.append("--monitor")
    else:
        raise ValueError("mode must be 'roll' or 'monitor'")

    if EXECUTE:
        args.append("--execute")
    if USE_LIVE:
        args.append("--live")

    # don't use --watch here; run a single scan per invocation
    return " ".join(args)


def run_command_with_retries(cmd: str, max_retries=MAX_RETRIES) -> int:
    """Run cmd as a subprocess, capture output, and retry on failure."""
    attempt = 0
    while True:
        attempt += 1
        start = datetime.utcnow()
        logger.info("Starting: %s (attempt %d)", cmd, attempt)
        try:
            # Use a reasonably long timeout in case IB calls take time
            proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=900)
            duration = (datetime.utcnow() - start).total_seconds()
            logger.info("Finished: %s (attempt %d) exit=%d duration=%.1fs", cmd, attempt, proc.returncode, duration)
            if proc.stdout:
                logger.info("STDOUT:\n%s", proc.stdout)
            if proc.stderr:
                logger.warning("STDERR:\n%s", proc.stderr)
            if proc.returncode == 0:
                return 0
            else:
                raise RuntimeError(f"command exited {proc.returncode}")
        except Exception as exc:
            logger.exception("Command failed on attempt %d: %s", attempt, exc)
            if attempt >= max_retries:
                logger.error("Max retries reached for: %s", cmd)
                return 1
            backoff = RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            logger.info("Retrying in %d second(s)...", backoff)
            time.sleep(backoff)


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

def daily_roll_job():
    """Job that opens/rolls the 30-day 5% OTM cycle once per day."""
    cmd = build_cmd("roll")
    rc = run_command_with_retries(cmd)
    if rc != 0:
        logger.error("daily_roll_job failed with rc=%d", rc)


def hourly_monitor_job():
    """Job that runs a single monitor scan to close near-expiration shorts."""
    cmd = build_cmd("monitor")
    rc = run_command_with_retries(cmd)
    if rc != 0:
        logger.error("hourly_monitor_job failed with rc=%d", rc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("Starting VOO scheduler; repo=%s; execute=%s; live=%s", REPO_DIR, EXECUTE, USE_LIVE)
    sched = BlockingScheduler(timezone=TZ) if TZ else BlockingScheduler()

    # daily roll (cron)
    try:
        trigger = CronTrigger(**DAILY_ROLL_CRON, timezone=TZ)
        sched.add_job(daily_roll_job, trigger, id="daily_roll", max_instances=1, replace_existing=True)
        logger.info("Scheduled daily_roll at %s (tz=%s)", DAILY_ROLL_CRON, TZ)
    except Exception:
        logger.exception("Failed to schedule daily_roll; check DAILY_ROLL_CRON config")

    # hourly monitor (interval)
    try:
        i_trigger = IntervalTrigger(minutes=MONITOR_INTERVAL_MINUTES, timezone=TZ)
        sched.add_job(hourly_monitor_job, i_trigger, id="hourly_monitor", max_instances=1, replace_existing=True)
        logger.info("Scheduled hourly_monitor interval=%d minutes (tz=%s)", MONITOR_INTERVAL_MINUTES, TZ)
    except Exception:
        logger.exception("Failed to schedule hourly monitor; check MONITOR_INTERVAL_MINUTES config")

    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped by user")


if __name__ == "__main__":
    main()
