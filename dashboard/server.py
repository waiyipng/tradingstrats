"""Read-only local API for the news-trading operations dashboard."""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DATA_DIR = ROOT / "newstrading" / "data"
LOG_PATH = ROOT / "newstrading" / "scheduler.log"
WATCHLIST_PATH = ROOT / "newstrading" / "config" / "watchlist.json"
AUDIT_DIR = DATA_DIR / "audit_runs"
WHEEL_RUN_DIR = ROOT / "wheeltrading" / "data" / "automated_runs"
WHEEL_LOG_PATH = ROOT / "wheeltrading" / "wheel_scheduler.log"
GOLD_RUN_DIR = ROOT / "goldtrading" / "data" / "automated_runs"
GOLD_LOG_PATH = ROOT / "goldtrading" / "gold_scheduler.log"
EXECUTION_LOOKBACK_DAYS = 3


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def newest_json(directory: Path) -> dict[str, Any] | None:
    files = list(directory.glob("*.json"))
    if not files:
        return None
    return load_json(max(files, key=lambda file: file.stat().st_mtime))


def iso_to_epoch(value: str | None) -> float:
    if not value:
        return 0.0
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def recommendation_for_id(recommendation_id: str | None) -> dict[str, Any] | None:
    if not recommendation_id:
        return None
    for path in (DATA_DIR / "order_recommendations").glob("*/*.json"):
        payload = load_json(path)
        if payload.get("recommendation_id") == recommendation_id:
            return payload
    return None


def bracket_details(recommendation: dict[str, Any] | None) -> dict[str, float | None]:
    if not recommendation or recommendation.get("action") != "BUY":
        return {"entry_limit": None, "take_profit": None, "stop_loss": None}
    entry = recommendation.get("limit_price")
    if not entry:
        return {"entry_limit": None, "take_profit": None, "stop_loss": None}
    return {
        "entry_limit": round(float(entry), 2),
        "take_profit": round(float(entry) * (1 + float(recommendation.get("take_profit_pct", 0))), 2),
        "stop_loss": round(float(entry) * (1 - float(recommendation.get("stop_loss_pct", 0))), 2),
    }


def pending_stock_orders(watchlist_symbols: set[str]) -> list[dict[str, Any]]:
    try:
        from ib_async import IB

        ib = IB()
        ib.connect("127.0.0.1", 7497, clientId=10_000 + secrets.randbelow(10_000), timeout=5)
        try:
            ib.reqOpenOrders()
            ib.sleep(0.25)
            active = {"ApiPending", "PendingSubmit", "PreSubmitted", "Submitted"}
            events = []
            for trade in ib.openTrades():
                # Only surface orders for symbols the equity-signal strategy actually
                # tracks. Manually-placed orders (e.g. a VOO test position) are not
                # strategy-driven and must not appear as strategy order events.
                if trade.contract.symbol not in watchlist_symbols:
                    continue
                if trade.contract.secType != "STK" or trade.orderStatus.status not in active:
                    continue
                events.append(
                    {
                        "event_id": f"pending-{trade.order.orderId}",
                        "symbol": trade.contract.symbol,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "status": "PENDING",
                        "broker": "ibkr",
                        "action": trade.order.action,
                        "requested_qty": int(trade.order.totalQuantity),
                        "filled_qty": int(trade.orderStatus.filled),
                        "price": float(trade.order.lmtPrice) if trade.order.lmtPrice else None,
                        "reasons": [],
                        "bracket": {"entry_limit": float(trade.order.lmtPrice) if trade.order.lmtPrice else None, "take_profit": None, "stop_loss": None},
                    }
                )
            return events
        finally:
            if ib.isConnected():
                ib.disconnect()
    except Exception:
        return []


def parse_log_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S,%f").replace(tzinfo=timezone(timedelta(hours=-4)))


def scheduler_events() -> tuple[list[dict[str, str]], dict[str, Any]]:
    if not LOG_PATH.exists():
        return [], {"active": False, "interval_minutes": 30}
    events: list[dict[str, str]] = []
    pattern = re.compile(r"^(?P<time>[^,]+),\d+ INFO .* - (?P<message>.*)$")
    lines = LOG_PATH.read_text(encoding="utf-8").splitlines()
    sweep_starts: list[datetime] = []
    sweep_ends: list[datetime] = []
    for line in lines:
        match = pattern.match(line)
        if not match:
            continue
        message = match.group("message")
        timestamp = parse_log_time(line.split(" INFO ", 1)[0])
        if message.startswith('Running job "pipeline_job'):
            sweep_starts.append(timestamp)
        elif 'Job "pipeline_job' in message and "executed successfully" in message:
            sweep_ends.append(timestamp)
        if any(term in message for term in ("Starting newstrading", "Scheduled", "Starting: ", "Execution for", "Max retries")):
            events.append({"time": match.group("time"), "message": message})
    startup = next((event["time"] for event in reversed(events) if "Starting newstrading" in event["message"]), None)
    last_start = sweep_starts[-1] if sweep_starts else None
    last_end = next((finished for finished in reversed(sweep_ends) if last_start and finished >= last_start), None)
    return list(reversed(events[-12:])), {
        "active": bool(startup),
        "interval_minutes": 30,
        "started_at": startup,
        "last_sweep_started_at": last_start.isoformat() if last_start else None,
        "last_sweep_completed_at": last_end.isoformat() if last_end else None,
        "last_sweep_duration_seconds": round((last_end - last_start).total_seconds()) if last_start and last_end else None,
    }


def strategy_pnl() -> dict[str, Any]:
    # Read-only view of the ledger the position monitor fills from IBKR executions.
    from newstrading.execution.pnl_ledger import summary

    return summary()


def dashboard_payload() -> dict[str, Any]:
    watchlist = load_json(WATCHLIST_PATH)
    watchlist_symbols = {entry["symbol"] for entry in watchlist}
    symbols: list[dict[str, Any]] = []
    all_news = 0
    buy_count = 0
    sell_count = 0

    for entry in watchlist:
        symbol = entry["symbol"]
        batch = newest_json(DATA_DIR / "news_batches" / symbol)
        signal = newest_json(DATA_DIR / "signals" / symbol)
        recommendation = newest_json(DATA_DIR / "order_recommendations" / symbol)
        article_count = int(batch.get("article_count", 0)) if batch else 0
        all_news += article_count
        decision = signal.get("decision", "WAITING") if signal else "WAITING"
        buy_count += decision == "BUY"
        sell_count += decision == "SELL"
        symbols.append(
            {
                "symbol": symbol,
                "name": entry["name"],
                "sector": entry["sector"],
                "exchange": entry.get("exchange", "US"),
                "decision": decision,
                "confidence": signal.get("confidence") if signal else None,
                "sentiment": signal.get("sentiment_score") if signal else None,
                "urgency": signal.get("urgency", "-") if signal else "-",
                "articles": article_count,
                "sources": signal.get("evidence", {}).get("source_count", 0) if signal else 0,
                "trend": signal.get("market_context", {}).get("trend", "UNKNOWN") if signal else "UNKNOWN",
                "price": signal.get("market_context", {}).get("current_price") if signal else None,
                "catalysts": signal.get("catalysts", []) if signal else [],
                "updated_at": signal.get("timestamp") if signal else batch.get("generated_at") if batch else None,
                "order_action": recommendation.get("action") if recommendation else None,
                "order_qty": recommendation.get("qty") if recommendation else None,
            }
        )

    reports: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=EXECUTION_LOOKBACK_DAYS)
    reports_dir = DATA_DIR / "execution_reports"
    for directory in reports_dir.iterdir() if reports_dir.exists() else []:
        # Only strategy-tracked watchlist symbols; a directory can exist from
        # manual/test activity (e.g. VOO) that the strategy never traded.
        if not directory.is_dir() or directory.name not in watchlist_symbols:
            continue
        for path in directory.glob("*.json"):
            report = load_json(path)
            timestamp = datetime.fromisoformat(report["timestamp"].replace("Z", "+00:00"))
            if timestamp < cutoff:
                continue
            recommendation = recommendation_for_id(report.get("recommendation_id"))
            reports.append(
                {
                    "event_id": report.get("execution_id"),
                    "symbol": report.get("symbol"),
                    "timestamp": report.get("timestamp"),
                    "status": report.get("status"),
                    "broker": report.get("broker"),
                    "action": recommendation.get("action") if recommendation else None,
                    "requested_qty": report.get("order", {}).get("requested_qty", 0),
                    "filled_qty": report.get("order", {}).get("filled_qty", 0),
                    "price": report.get("order", {}).get("avg_fill_price"),
                    "reasons": report.get("risk_checks", {}).get("reasons", []),
                    "bracket": bracket_details(recommendation),
                }
            )
    reports.extend(pending_stock_orders(watchlist_symbols))
    reports.sort(key=lambda report: iso_to_epoch(report["timestamp"]), reverse=True)
    events, scheduler = scheduler_events()
    now = datetime.now(timezone.utc)
    next_poll = None
    last_start = scheduler.get("last_sweep_started_at")
    scheduler_start = scheduler.get("started_at")
    anchor_times = [datetime.fromisoformat(last_start)] if last_start else []
    if scheduler_start:
        anchor_times.append(datetime.strptime(scheduler_start, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=-4))))
    if anchor_times:
        started = max(anchor_times)
        interval = timedelta(minutes=scheduler["interval_minutes"])
        next_poll = started + interval
        while next_poll <= now:
            next_poll += interval
    scheduler["next_poll"] = next_poll.isoformat() if next_poll else None

    pnl = strategy_pnl()
    return {
        "generated_at": now.isoformat(),
        "scheduler": scheduler,
        "summary": {"symbols": len(symbols), "articles": all_news, "buy_signals": buy_count, "sell_signals": sell_count, "executions": len(reports)},
        "symbols": sorted(symbols, key=lambda item: (item["decision"] != "BUY", -(item["confidence"] or 0), item["symbol"])),
        "executions": reports,
        "events": events,
        "ytd_realized_pnl": pnl["ytd_realized_pnl"],
        "realized_by_symbol": pnl["by_symbol"],
    }


def audit_runs_payload() -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for path in AUDIT_DIR.glob("*.json") if AUDIT_DIR.exists() else []:
        payload = load_json(path)
        symbols = payload.get("symbols", {})
        runs.append(
            {
                "run_id": payload.get("run_id", path.stem),
                "started_at": payload.get("started_at"),
                "symbol_count": len(symbols),
                "fetched_articles": sum(entry.get("sourcing", {}).get("fetched_article_count", 0) for entry in symbols.values()),
                "retained_articles": sum(entry.get("sourcing", {}).get("retained_article_count", 0) for entry in symbols.values()),
                "buy_signals": sum(entry.get("signaling", {}).get("signal", {}).get("decision") == "BUY" for entry in symbols.values()),
                "sell_signals": sum(entry.get("signaling", {}).get("signal", {}).get("decision") == "SELL" for entry in symbols.values()),
            }
        )
    return sorted(runs, key=lambda item: iso_to_epoch(item["started_at"]), reverse=True)


def audit_run_payload(run_id: str) -> dict[str, Any] | None:
    path = AUDIT_DIR / f"{run_id}.json"
    return load_json(path) if path.exists() else None


def wheel_status_payload() -> dict[str, Any]:
    try:
        from wheeltrading.status import wheel_status

        payload = wheel_status()
        latest_runs: dict[str, Any] = {}
        for path in WHEEL_RUN_DIR.glob("wheel_run_*.json") if WHEEL_RUN_DIR.exists() else []:
            run = load_json(path)
            symbol = run.get("symbol")
            if not symbol:
                continue
            previous = latest_runs.get(symbol)
            if previous and iso_to_epoch(run.get("generated_at")) <= iso_to_epoch(previous.get("generated_at")):
                continue
            latest_runs[symbol] = run
        payload["latest_runs"] = latest_runs
        latest_run_time = max((run.get("generated_at") for run in latest_runs.values()), default=None)
        from wheeltrading.schedule import next_scan_after

        upcoming = next_scan_after(datetime.now(timezone.utc))
        next_run = upcoming.isoformat() if upcoming else None
        active = subprocess.run(["pgrep", "-f", "wheeltrading.scheduler"], capture_output=True, text=True).returncode == 0
        payload["scheduler"] = {"active": active, "interval_minutes": 30, "last_run_at": latest_run_time, "next_run": next_run}
        return payload
    except Exception as exc:
        return {"connection_mode": "unavailable", "status": "unavailable", "reason": str(exc), "ytd_realized_pnl": 0.0, "symbols": []}


def gold_status_payload() -> dict[str, Any]:
    try:
        from goldtrading.status import gold_status

        payload = gold_status()
        latest_run = newest_json(GOLD_RUN_DIR) if GOLD_RUN_DIR.exists() else None
        payload["latest_run"] = latest_run
        latest_run_time = latest_run.get("generated_at") if latest_run else None
        next_run = None
        if latest_run_time:
            next_run = (datetime.fromisoformat(latest_run_time.replace("Z", "+00:00")) + timedelta(minutes=30)).isoformat()
        active = subprocess.run(["pgrep", "-f", "goldtrading.scheduler"], capture_output=True, text=True).returncode == 0
        payload["scheduler"] = {"active": active, "interval_minutes": 30, "last_run_at": latest_run_time, "next_run": next_run}
        return payload
    except Exception as exc:
        return {"connection_mode": "unavailable", "status": "unavailable", "reason": str(exc), "realized_pnl": 0.0, "ytd_realized_pnl": 0.0, "open_positions": []}


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/dashboard":
            payload_data: Any = dashboard_payload()
        elif path == "/api/audit-runs":
            payload_data = audit_runs_payload()
        elif path.startswith("/api/audit-runs/"):
            run_id = path.removeprefix("/api/audit-runs/")
            payload_data = audit_run_payload(run_id)
            if payload_data is None:
                self.send_error(404)
                return
        elif path == "/api/wheel-status":
            payload_data = wheel_status_payload()
        elif path == "/api/gold-status":
            payload_data = gold_status_payload()
        else:
            self.send_error(404)
            return
        payload = json.dumps(payload_data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_: object) -> None:
        return


if __name__ == "__main__":
    print("Dashboard API listening at http://127.0.0.1:8000/api/dashboard")
    ThreadingHTTPServer(("127.0.0.1", 8000), DashboardHandler).serve_forever()