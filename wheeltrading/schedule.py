"""Wheel scan timetable: every 30 minutes during regular US trading hours only.

Shared by the scheduler and the dashboard so "next wheel scan" matches what actually runs.
Scans fire Mon-Fri at 9:30, 10:00, ..., 15:30 America/New_York. Exchange holidays are
not modelled; a holiday scan finds no live quotes and holds.
"""
from __future__ import annotations

from datetime import datetime

from apscheduler.triggers.combining import OrTrigger
from apscheduler.triggers.cron import CronTrigger

from wheeltrading.config import MARKET_CLOSE, MARKET_OPEN, MARKET_TIMEZONE


def scan_trigger() -> OrTrigger:
    open_hour, open_minute = MARKET_OPEN
    close_hour, _ = MARKET_CLOSE
    return OrTrigger(
        [
            # 9:30 open bar, then every half hour from 10:00 to the last full slot before 16:00.
            CronTrigger(day_of_week="mon-fri", hour=open_hour, minute=open_minute, timezone=MARKET_TIMEZONE),
            CronTrigger(day_of_week="mon-fri", hour=f"{open_hour + 1}-{close_hour - 1}", minute="0,30", timezone=MARKET_TIMEZONE),
        ]
    )


def next_scan_after(now: datetime) -> datetime | None:
    return scan_trigger().get_next_fire_time(None, now)
