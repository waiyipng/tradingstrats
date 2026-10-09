"""Shared utilities: JSON I/O, id/timestamp generation, and data artifact paths."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

NEWSTRADING_ROOT = Path(__file__).resolve().parent
DATA_DIR = NEWSTRADING_ROOT / "data"


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:8]}"


def save_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, default=str)


def load_json(path: "Path | str") -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def latest_artifact(stage: str, symbol: str) -> Path:
    """Return the most recently modified JSON artifact for a symbol within a stage directory."""
    directory = DATA_DIR / stage / symbol.upper()
    files = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise FileNotFoundError(f"No artifacts found in {directory}")
    return files[-1]


def usd_exchange_rate(rows: Any) -> float:
    """Base-currency units per 1 USD, as reported by ib.accountSummary()'s USD
    currency segment (1.0 if the account's base currency is already USD). Needed
    to convert other base-currency-denominated IBKR values - e.g. OrderState.
    initMarginChange from ib.whatIfOrder(), which carries no currency of its own -
    into USD."""
    usd_rate_rows = [float(row.value) for row in rows if row.tag == "ExchangeRate" and row.currency == "USD"]
    return usd_rate_rows[0] if usd_rate_rows and usd_rate_rows[0] > 0 else 1.0


def usd_summary_value(rows: Any, tag: str, default: float = 0.0) -> float:
    """Converts an IBKR ib.accountSummary() tag to USD.

    Account-wide tags such as NetLiquidation, ExcessLiquidity, and TotalCashValue are
    reported by IBKR only once, in the account's base currency - there is no separate
    USD-converted row for them, even on a non-USD-base account. A naive
    {row.tag: row.value for row in rows} lookup silently returns that base-currency
    figure, which is wrong by the FX rate on any account whose base currency isn't
    USD (e.g. a ~7.8x overstatement on an HKD-base account). Convert explicitly using
    the ExchangeRate row IBKR reports for the USD currency segment (base-currency
    units per 1 USD; the BASE row's own rate is always 1.0).
    """
    base_rows = [float(row.value) for row in rows if row.tag == tag]
    if not base_rows:
        return default
    return base_rows[0] / usd_exchange_rate(rows)
