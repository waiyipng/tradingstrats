"""Street consensus data for the MS earnings analyst agent, sourced from
yfinance plus Nasdaq's public analyst-forecast API as a second, corroborating
source.

Pure data fetch, no LLM call - kept separate from analyst_agent.py so it is
unit-testable with fakes and so either source's outage degrades the same way
as any other data_unavailable condition (Nasdaq is best-effort: its absence
does not block the pipeline, since yfinance alone is still a usable snapshot).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Optional

import requests
import yfinance as yf

NASDAQ_REQUEST_TIMEOUT_SECONDS = 10
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}


@dataclass(frozen=True)
class EarningsHistoryQuarter:
    report_date: str
    eps_estimate: Optional[float]
    eps_actual: Optional[float]
    surprise_pct: Optional[float]


@dataclass(frozen=True)
class NasdaqEpsForecast:
    """The nearest upcoming quarter's EPS forecast from Nasdaq's public
    analyst-forecast API (https://www.nasdaq.com/market-activity/stocks/<symbol>/earnings),
    kept separate from yfinance's consensus as an independent corroborating source."""

    fiscal_quarter_end: str
    consensus_eps: Optional[float]
    eps_low: Optional[float]
    eps_high: Optional[float]
    num_estimates: Optional[int]
    revisions_up: Optional[int]
    revisions_down: Optional[int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConsensusSnapshot:
    symbol: str
    current_price: Optional[float]
    next_earnings_date: Optional[str]
    consensus_eps: Optional[float]
    eps_low: Optional[float]
    eps_high: Optional[float]
    revenue_low: Optional[float]
    revenue_high: Optional[float]
    revenue_average: Optional[float]
    shares_outstanding: Optional[float]
    analyst_target_mean: Optional[float]
    analyst_target_median: Optional[float]
    analyst_target_low: Optional[float]
    analyst_target_high: Optional[float]
    history: list[EarningsHistoryQuarter]
    nasdaq_forecast: Optional[NasdaqEpsForecast] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def fetch_nasdaq_eps_forecast(symbol: str) -> Optional[NasdaqEpsForecast]:
    """Best-effort fetch from Nasdaq's public analyst-forecast JSON API.

    Not a licensed/paid feed - a public endpoint behind the same earnings page
    nasdaq.com shows. Returns None on any failure (network, shape change,
    empty data) so an outage here never blocks the rest of the pipeline.
    """
    try:
        response = requests.get(
            f"https://api.nasdaq.com/api/analyst/{symbol}/earnings-forecast",
            headers=NASDAQ_HEADERS, timeout=NASDAQ_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        rows = response.json()["data"]["quarterlyForecast"]["rows"]
        if not rows:
            return None
        # Nasdaq returns quarters in ascending order; the first row is the
        # nearest upcoming fiscal quarter end, i.e. the one being reported next.
        nearest = rows[0]
        return NasdaqEpsForecast(
            fiscal_quarter_end=nearest["fiscalEnd"],
            consensus_eps=nearest.get("consensusEPSForecast"),
            eps_low=nearest.get("lowEPSForecast"),
            eps_high=nearest.get("highEPSForecast"),
            num_estimates=nearest.get("noOfEstimates"),
            revisions_up=nearest.get("up"),
            revisions_down=nearest.get("down"),
        )
    except Exception:
        return None


def fetch_consensus(symbol: str, history_quarters: int = 8) -> ConsensusSnapshot:
    ticker = yf.Ticker(symbol)
    info = ticker.get_info()
    calendar = ticker.calendar or {}
    targets = ticker.analyst_price_targets or {}

    earnings_date_list = calendar.get("Earnings Date") or []
    next_earnings_date = earnings_date_list[0].isoformat() if earnings_date_list else None

    history: list[EarningsHistoryQuarter] = []
    try:
        earnings_dates = ticker.earnings_dates
    except Exception:
        earnings_dates = None
    if earnings_dates is not None:
        for report_date, row in earnings_dates.iterrows():
            reported = row.get("Reported EPS")
            if reported != reported:  # NaN -> not yet reported, skip for history
                continue
            history.append(
                EarningsHistoryQuarter(
                    report_date=report_date.isoformat(),
                    eps_estimate=float(row.get("EPS Estimate")) if row.get("EPS Estimate") == row.get("EPS Estimate") else None,
                    eps_actual=float(reported),
                    surprise_pct=float(row.get("Surprise(%)")) if row.get("Surprise(%)") == row.get("Surprise(%)") else None,
                )
            )
            if len(history) >= history_quarters:
                break

    return ConsensusSnapshot(
        symbol=symbol,
        current_price=info.get("currentPrice") or info.get("regularMarketPrice"),
        next_earnings_date=next_earnings_date,
        consensus_eps=calendar.get("Earnings Average"),
        eps_low=calendar.get("Earnings Low"),
        eps_high=calendar.get("Earnings High"),
        revenue_low=calendar.get("Revenue Low"),
        revenue_high=calendar.get("Revenue High"),
        revenue_average=calendar.get("Revenue Average"),
        shares_outstanding=info.get("sharesOutstanding") or info.get("impliedSharesOutstanding"),
        analyst_target_mean=targets.get("mean"),
        analyst_target_median=targets.get("median"),
        analyst_target_low=targets.get("low"),
        analyst_target_high=targets.get("high"),
        history=history,
        nasdaq_forecast=fetch_nasdaq_eps_forecast(symbol),
    )
