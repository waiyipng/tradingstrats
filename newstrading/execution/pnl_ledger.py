"""Persistent realized-P&L ledger for the equity-signal strategy.

TWS only exposes the current session's executions over the API, so each
scheduler cycle copies the strategy's closing fills (with IBKR's own FIFO
realized P&L from the commission report) into a local ledger before they age
out. Entries are keyed by IBKR execId, so repeated syncs never double-count.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from newstrading.common import DATA_DIR, load_json, save_json

LEDGER_PATH = DATA_DIR / "realized_pnl_ledger.json"
UNSET = 1e300  # ib_async reports "no value" as sys.float_info.max


def load_ledger() -> Dict[str, Any]:
    if LEDGER_PATH.exists():
        return load_json(LEDGER_PATH)
    return {"entries": {}}


def _save(ledger: Dict[str, Any]) -> None:
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_json(LEDGER_PATH, ledger)


def sync_from_fills(fills: Iterable[Any], strategy_client_id: int) -> int:
    """Record closing stock fills placed by the strategy's IBKR client id.

    Only fills from ``strategy_client_id`` count: manual trades (client 0), the
    wheel (45) and gold (46) strategies use other client ids. Bracket take-profit
    and stop-loss children inherit the parent's client id, so they are included.
    """
    ledger = load_ledger()
    entries = ledger.setdefault("entries", {})
    added = 0
    for fill in fills:
        execution, report = fill.execution, fill.commissionReport
        if fill.contract.secType != "STK" or execution.clientId != strategy_client_id or execution.execId in entries:
            continue
        realized = report.realizedPNL if report else None
        if realized is None or abs(realized) >= UNSET or realized == 0:
            continue  # opening fill, or commission report not received yet
        entries[execution.execId] = {
            "symbol": fill.contract.symbol,
            "time": execution.time.isoformat(),
            "side": execution.side,
            "shares": float(execution.shares),
            "price": float(execution.price),
            "order_id": execution.orderId,
            "commission": float(report.commission or 0.0),
            "realized_pnl": round(float(realized), 2),
            "source": "ibkr_fill",
        }
        added += 1
    if added:
        _save(ledger)
    return added


def add_entry(entry_id: str, symbol: str, time: str, realized_pnl: float, source: str, note: str, **extra: Any) -> None:
    """Record a realized amount that is no longer available as an API fill (e.g. a backfill)."""
    ledger = load_ledger()
    entries = ledger.setdefault("entries", {})
    if entry_id not in entries:
        entries[entry_id] = {"symbol": symbol, "time": time, "realized_pnl": round(realized_pnl, 2), "source": source, "note": note, **extra}
        _save(ledger)


def summary(year: Optional[int] = None, ledger: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    year = year or datetime.now(timezone.utc).year
    ledger = ledger if ledger is not None else load_ledger()
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for entry in ledger.get("entries", {}).values():
        if datetime.fromisoformat(entry["time"]).year != year:
            continue
        row = by_symbol.setdefault(entry["symbol"], {"symbol": entry["symbol"], "realized_pnl": 0.0, "closing_fills": 0, "last_exit": None, "reconstructed": False})
        row["realized_pnl"] = round(row["realized_pnl"] + float(entry["realized_pnl"]), 2)
        row["closing_fills"] += 1
        row["last_exit"] = max(filter(None, [row["last_exit"], entry["time"]]))
        row["reconstructed"] = row["reconstructed"] or entry.get("source") != "ibkr_fill"
    rows: List[Dict[str, Any]] = sorted(by_symbol.values(), key=lambda row: row["realized_pnl"])
    return {"year": year, "ytd_realized_pnl": round(sum(row["realized_pnl"] for row in rows), 2), "by_symbol": rows}
