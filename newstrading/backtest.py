"""Historical news-signal backtest for the configured watchlist.

The backtest uses Finnhub company news and Yahoo Finance daily closes. News is
available only up to each as-of timestamp, and trades enter on the next
available trading day to avoid using the signal day's closing price.

Usage:
    FINNHUB_API_KEY=... python -m newstrading.backtest --start 2023-01-01 --end 2025-12-31
    FINNHUB_API_KEY=... python -m newstrading.backtest --symbol AAPL --start 2024-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import math
import os
import time as clock
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError
from urllib import parse

from newstrading.common import DATA_DIR, save_json
from newstrading.config.loader import all_symbols, get_symbol_entry
from newstrading.models.news import NewsArticle, NewsBatch
from newstrading.signaling.aggregator import aggregate_signal
from newstrading.signaling.analyzers.keyword_analyzer import score_article
from newstrading.signaling.keyword_sets import financial as financial_keywords
from newstrading.signaling.keyword_sets import tech as tech_keywords
from newstrading.sourcing.deduplicator import dedupe_articles
from newstrading.sourcing.http_utils import safe_json_get

try:
    import yfinance as yf
except Exception:  # pragma: no cover - dependency is optional at import time
    yf = None


KEYWORD_SETS = {"tech": tech_keywords, "financial": financial_keywords}
FINNHUB_SOURCE_WEIGHT = 0.8
POLYGON_SOURCE_WEIGHT = 0.8
ALPHA_VANTAGE_SOURCE_WEIGHT = 0.75
BENZINGA_SOURCE_WEIGHT = 0.85
TIINGO_SOURCE_WEIGHT = 0.8


def fetch_json_with_backoff(url: str, attempts: int = 4) -> Any:
    for attempt in range(attempts):
        try:
            return safe_json_get(url)
        except HTTPError as exc:
            if exc.code != 429 or attempt == attempts - 1:
                raise
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else 2.0 ** (attempt + 1)
            except ValueError:
                delay = 2.0 ** (attempt + 1)
            clock.sleep(min(60.0, max(1.0, delay)))
    raise RuntimeError("historical news request retry loop ended unexpectedly")


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value}; expected YYYY-MM-DD") from exc


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_historical_news(symbol: str, start: date, end: date, api_key: str) -> List[Dict[str, Any]]:
    """Fetch a fixed Finnhub date range, preserving publication timestamps."""
    url = (
        "https://finnhub.io/api/v1/company-news"
        f"?symbol={parse.quote(symbol)}&from={start.isoformat()}&to={end.isoformat()}"
        f"&token={parse.quote(api_key)}"
    )
    payload = safe_json_get(url)
    if not isinstance(payload, list):
        raise RuntimeError(f"Finnhub returned an unexpected response for {symbol}")

    raw_articles: List[Dict[str, Any]] = []
    for item in payload:
        title = (item.get("headline") or item.get("summary") or "").strip()
        summary = (item.get("summary") or title or "").strip()
        if not title and not summary:
            continue
        published_at = parse_timestamp(item.get("datetime"))
        raw_articles.append(
            {
                "title": title,
                "summary": summary,
                "url": item.get("url") or "",
                "published_at": published_at.isoformat() if published_at else None,
                "author": item.get("source") or "",
                "content": "",
                "source": "finnhub",
                "source_weight": FINNHUB_SOURCE_WEIGHT,
            }
        )
    return dedupe_articles(raw_articles)


def month_windows(start: date, end: date) -> List[Tuple[date, date]]:
    windows: List[Tuple[date, date]] = []
    cursor = start.replace(day=1)
    while cursor <= end:
        next_month = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        windows.append((max(start, cursor), min(end, next_month - timedelta(days=1))))
        cursor = next_month
    return windows


def fetch_polygon_historical_news(symbol: str, start: date, end: date, api_key: str) -> List[Dict[str, Any]]:
    """Fetch Polygon news in bounded windows so multi-year ranges are not truncated."""
    raw_articles: List[Dict[str, Any]] = []
    for window_start, window_end in month_windows(start, end):
        url = (
            "https://api.polygon.io/v2/reference/news"
            f"?limit=1000&order=asc&sort=published_utc&ticker={parse.quote(symbol)}"
            f"&published_utc.gte={window_start.isoformat()}&published_utc.lte={window_end.isoformat()}"
            f"&apiKey={parse.quote(api_key)}"
        )
        payload = fetch_json_with_backoff(url)
        if not isinstance(payload, dict):
            continue
        pages = [payload]
        next_url = payload.get("next_url")
        while next_url:
            if "apiKey=" not in next_url:
                next_url += "&apiKey=" + parse.quote(api_key)
            page = fetch_json_with_backoff(next_url)
            if not isinstance(page, dict):
                break
            pages.append(page)
            next_url = page.get("next_url")
        for page in pages:
            for item in page.get("results", []):
                title = (item.get("title") or "").strip()
                summary = (item.get("description") or item.get("summary") or title or "").strip()
                if not title and not summary:
                    continue
                raw_articles.append(
                    {
                        "title": title,
                        "summary": summary,
                        "url": item.get("article_url") or item.get("url") or "",
                        "published_at": item.get("published_utc") or item.get("publishedAt"),
                        "author": (item.get("publisher") or {}).get("name", "") if isinstance(item.get("publisher"), dict) else item.get("author", ""),
                        "content": "",
                        "source": "polygon",
                        "source_weight": POLYGON_SOURCE_WEIGHT,
                    }
                )
    return dedupe_articles(raw_articles)


def fetch_alpha_vantage_historical_news(symbol: str, start: date, end: date, api_key: str) -> List[Dict[str, Any]]:
    raw_articles: List[Dict[str, Any]] = []
    for window_start, window_end in month_windows(start, end):
        url = (
            "https://www.alphavantage.co/query"
            f"?function=NEWS_SENTIMENT&tickers={parse.quote(symbol)}"
            f"&time_from={window_start:%Y%m%d}0000&time_to={window_end:%Y%m%d}2359"
            f"&sort=EARLIEST&limit=1000&apikey={parse.quote(api_key)}"
        )
        payload = fetch_json_with_backoff(url)
        if not isinstance(payload, dict):
            continue
        for item in payload.get("feed", []):
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or title or "").strip()
            if not title:
                continue
            raw_articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": item.get("time_published"),
                    "author": item.get("source") or "",
                    "content": "",
                    "source": "alpha_vantage",
                    "source_weight": ALPHA_VANTAGE_SOURCE_WEIGHT,
                }
            )
    return dedupe_articles(raw_articles)


def fetch_benzinga_historical_news(symbol: str, start: date, end: date, api_key: str) -> List[Dict[str, Any]]:
    raw_articles: List[Dict[str, Any]] = []
    for window_start, window_end in month_windows(start, end):
        url = (
            "https://api.benzinga.com/api/v2/news"
            f"?tickers={parse.quote(symbol)}&date_from={window_start.isoformat()}&date_to={window_end.isoformat()}"
            f"&pagesize=100&token={parse.quote(api_key)}"
        )
        payload = fetch_json_with_backoff(url)
        if not isinstance(payload, list):
            continue
        for item in payload:
            title = (item.get("title") or "").strip()
            summary = (item.get("teaser") or title or "").strip()
            if not title:
                continue
            raw_articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": item.get("created"),
                    "author": item.get("author") or "",
                    "content": "",
                    "source": "benzinga",
                    "source_weight": BENZINGA_SOURCE_WEIGHT,
                }
            )
    return dedupe_articles(raw_articles)


def fetch_tiingo_historical_news(symbol: str, start: date, end: date, api_key: str) -> List[Dict[str, Any]]:
    raw_articles: List[Dict[str, Any]] = []
    for window_start, window_end in month_windows(start, end):
        url = (
            "https://api.tiingo.com/tiingo/news"
            f"?tickers={parse.quote(symbol)}&startDate={window_start.isoformat()}&endDate={window_end.isoformat()}"
            f"&limit=1000&token={parse.quote(api_key)}"
        )
        payload = fetch_json_with_backoff(url)
        if not isinstance(payload, list):
            continue
        for item in payload:
            title = (item.get("title") or "").strip()
            summary = (item.get("description") or title or "").strip()
            if not title:
                continue
            raw_articles.append(
                {
                    "title": title,
                    "summary": summary,
                    "url": item.get("url") or "",
                    "published_at": item.get("publishedDate"),
                    "author": item.get("source") or "",
                    "content": "",
                    "source": "tiingo",
                    "source_weight": TIINGO_SOURCE_WEIGHT,
                }
            )
    return dedupe_articles(raw_articles)


def fetch_news_for_provider(
    symbol: str, start: date, end: date, provider: str, api_key: Optional[str] = None
) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    if provider == "all":
        providers = {
            "polygon": (os.getenv("POLYGON_API_KEY"), fetch_polygon_historical_news),
            "finnhub": (os.getenv("FINNHUB_API_KEY"), fetch_historical_news),
            "alpha_vantage": (os.getenv("ALPHAVANTAGE_API_KEY"), fetch_alpha_vantage_historical_news),
            "benzinga": (os.getenv("BENZINGA_API_KEY"), fetch_benzinga_historical_news),
            "tiingo": (os.getenv("TIINGO_API_KEY"), fetch_tiingo_historical_news),
        }
        all_articles: List[Dict[str, Any]] = []
        statuses: Dict[str, str] = {}
        for name, (provider_key, fetcher) in providers.items():
            if not provider_key:
                statuses[name] = "missing_api_key"
                continue
            try:
                articles = fetcher(symbol, start, end, provider_key)
                all_articles.extend(articles)
                statuses[name] = f"ok:{len(articles)}"
            except Exception as exc:
                statuses[name] = f"error:{type(exc).__name__}"
        statuses.update(
            {
                "reuters_rss": "not_historical",
                "yahoo_finance_rss": "not_historical",
                "google_news_rss": "not_historical",
            }
        )
        return dedupe_articles(all_articles), statuses

    if not api_key:
        raise RuntimeError(f"missing API key for {provider}")
    if provider == "polygon":
        articles = fetch_polygon_historical_news(symbol, start, end, api_key)
    elif provider == "finnhub":
        articles = fetch_historical_news(symbol, start, end, api_key)
    elif provider == "alpha_vantage":
        articles = fetch_alpha_vantage_historical_news(symbol, start, end, api_key)
    elif provider == "benzinga":
        articles = fetch_benzinga_historical_news(symbol, start, end, api_key)
    elif provider == "tiingo":
        articles = fetch_tiingo_historical_news(symbol, start, end, api_key)
    else:
        raise ValueError(f"unsupported historical provider: {provider}")
    return articles, {provider: f"ok:{len(articles)}"}


def load_daily_closes(symbol: str, start: date, end: date) -> Dict[date, float]:
    if yf is None:
        raise RuntimeError("yfinance is required for historical prices; install requirements.txt")
    data = yf.download(
        symbol,
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        progress=False,
        auto_adjust=True,
        group_by="column",
    )
    if data.empty or "Close" not in data.columns:
        raise RuntimeError(f"no historical close data returned for {symbol}")
    close = data["Close"]
    if getattr(close, "ndim", 1) == 2:
        close = close.iloc[:, 0]
    closes: Dict[date, float] = {}
    for timestamp, value in close.dropna().items():
        timestamp_date = timestamp.date() if hasattr(timestamp, "date") else timestamp
        closes[timestamp_date] = float(value)
    if not closes:
        raise RuntimeError(f"no usable historical close data returned for {symbol}")
    return closes


def market_context_for_date(closes: Dict[date, float], as_of: date, window: int = 20) -> Tuple[Optional[float], Optional[float], str]:
    dates = sorted(day for day in closes if day <= as_of)
    if not dates:
        return None, None, "UNKNOWN"
    recent = dates[-window:]
    price = closes[dates[-1]]
    sma = sum(closes[day] for day in recent) / len(recent)
    ratio = price / sma if sma else 1.0
    trend = "BULLISH" if ratio > 1.02 else "BEARISH" if ratio < 0.98 else "NEUTRAL"
    return price, sma, trend


def signal_value(decision: str, confidence: float) -> float:
    if decision == "BUY":
        return confidence
    if decision == "SELL":
        return -confidence
    return 0.0


def regression_stats(scores: Sequence[float], returns: Sequence[float]) -> Dict[str, Optional[float]]:
    """Return Pearson correlation, OLS slope/intercept, and R-squared."""
    if len(scores) != len(returns) or len(scores) < 2:
        return {"correlation": None, "slope": None, "intercept": None, "r_squared": None}
    mean_score = sum(scores) / len(scores)
    mean_return = sum(returns) / len(returns)
    covariance = sum((score - mean_score) * (value - mean_return) for score, value in zip(scores, returns))
    score_variance = sum((score - mean_score) ** 2 for score in scores)
    return_variance = sum((value - mean_return) ** 2 for value in returns)
    if score_variance == 0 or return_variance == 0:
        return {"correlation": None, "slope": None, "intercept": mean_return, "r_squared": None}
    correlation = covariance / math.sqrt(score_variance * return_variance)
    slope = covariance / score_variance
    return {
        "correlation": correlation,
        "slope": slope,
        "intercept": mean_return - slope * mean_score,
        "r_squared": correlation**2,
    }


def summarize_horizon(rows: Sequence[Dict[str, Any]], horizon: int) -> Dict[str, Any]:
    samples = [row for row in rows if row["forward_returns"].get(str(horizon)) is not None]
    scores = [float(row["signal_score"]) for row in samples]
    returns = [float(row["forward_returns"][str(horizon)]) for row in samples]
    actionable = [row for row in samples if row["decision"] in {"BUY", "SELL"}]
    trade_returns = [
        (1 if row["decision"] == "BUY" else -1) * float(row["forward_returns"][str(horizon)])
        for row in actionable
    ]
    correct = sum(value > 0 for value in trade_returns)
    strategy_returns = [
        (1 if row["decision"] == "BUY" else -1 if row["decision"] == "SELL" else 0)
        * float(row["forward_returns"][str(horizon)])
        for row in samples
    ]
    compound = math.prod(1 + value for value in trade_returns) - 1 if trade_returns else None
    benchmark_return = None
    if samples:
        first_entry = float(samples[0]["entry_price"])
        last_exit = float(samples[-1]["exit_prices"][str(horizon)])
        benchmark_return = last_exit / first_entry - 1.0
    return {
        "horizon_trading_days": horizon,
        "samples": len(samples),
        "actionable_trades": len(actionable),
        "regression": regression_stats(scores, returns),
        "mean_forward_return": sum(returns) / len(returns) if returns else None,
        "mean_actionable_return": sum(trade_returns) / len(trade_returns) if trade_returns else None,
        "compound_actionable_return": compound,
        "mean_strategy_return_per_sample": sum(strategy_returns) / len(strategy_returns) if strategy_returns else None,
        "directional_hit_rate": correct / len(trade_returns) if trade_returns else None,
        "buy_and_hold_return_over_sample_window": benchmark_return,
    }


def run_symbol_backtest(
    symbol: str,
    start: date,
    end: date,
    api_key: str,
    horizons: Sequence[int],
    lookback_days: int,
    news_provider: str,
) -> Dict[str, Any]:
    entry = get_symbol_entry(symbol)
    if entry["sector"] not in KEYWORD_SETS:
        raise RuntimeError(f"no keyword set configured for sector {entry['sector']}")
    max_horizon = max(horizons)
    closes = load_daily_closes(symbol, start - timedelta(days=30), end + timedelta(days=max_horizon + 7))
    news, source_statuses = fetch_news_for_provider(
        symbol, start - timedelta(days=lookback_days), end, news_provider, api_key
    )
    news_dates = sorted(
        {published_at.date() for published_at in (parse_timestamp(article.get("published_at")) for article in news) if published_at}
    )
    keywords = KEYWORD_SETS[entry["sector"]]
    scored_news = []
    for index, article in enumerate(news):
        scored = score_article(article, keywords.POSITIVE_KEYWORDS, keywords.NEGATIVE_KEYWORDS, keywords.TOPIC_KEYWORDS)
        scored["published_at"] = article.get("published_at")
        scored["id"] = f"{symbol.lower()}_article_{index}"
        scored_news.append((parse_timestamp(article.get("published_at")), scored, article))

    evaluation_dates = sorted(day for day in closes if start <= day <= end)
    trading_dates = sorted(day for day in closes if start <= day <= end + timedelta(days=max_horizon + 7))
    rows: List[Dict[str, Any]] = []
    for as_of in evaluation_dates:
        index = trading_dates.index(as_of)
        entry_index = index + 1
        if entry_index + max_horizon >= len(trading_dates):
            break
        as_of_timestamp = datetime.combine(as_of, time(21, 0), tzinfo=timezone.utc)
        window_start = as_of_timestamp - timedelta(days=lookback_days)
        available = [
            article
            for published_at, article, _raw in scored_news
            if published_at is not None and window_start <= published_at <= as_of_timestamp
        ]
        batch = NewsBatch(
            batch_id=f"backtest_{symbol}_{as_of:%Y%m%d}",
            symbol=symbol,
            generated_at=as_of_timestamp.isoformat(),
            articles=[],
        )
        price, sma, trend = market_context_for_date(closes, as_of)
        from newstrading.models.signal import MarketContext

        signal = aggregate_signal(
            batch,
            available,
            MarketContext(current_price=price, sma_20=sma, trend=trend),
            as_of=as_of_timestamp,
        )
        entry_day = trading_dates[entry_index]
        forward_returns = {
            str(horizon): (closes[trading_dates[entry_index + horizon]] / closes[closes_date] - 1.0)
            for horizon in horizons
            for closes_date in [entry_day]
        }
        exit_prices = {str(horizon): closes[trading_dates[entry_index + horizon]] for horizon in horizons}
        rows.append(
            {
                "as_of": as_of.isoformat(),
                "entry_date": entry_day.isoformat(),
                "articles": len(available),
                "decision": signal.decision,
                "confidence": signal.confidence,
                "signal_score": float(signal.evidence.get("combined_score", signal.sentiment_score)),
                "recommendation_score": signal_value(signal.decision, signal.confidence),
                "entry_price": closes[entry_day],
                "exit_prices": exit_prices,
                "forward_returns": forward_returns,
            }
        )

    return {
        "symbol": symbol,
        "sector": entry["sector"],
        "start": start.isoformat(),
        "end": end.isoformat(),
        "news_source": f"{news_provider} historical company-news",
        "source_statuses": source_statuses,
        "news_articles": len(news),
        "news_days": len(news_dates),
        "news_coverage_start": news_dates[0].isoformat() if news_dates else None,
        "news_coverage_end": news_dates[-1].isoformat() if news_dates else None,
        "price_source": "Yahoo Finance adjusted daily closes via yfinance",
        "lookback_days": lookback_days,
        "rows": rows,
        "horizons": {str(horizon): summarize_horizon(rows, horizon) for horizon in horizons},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest historical news recommendations against forward stock returns.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--symbol", help="One configured ticker, for example AAPL.")
    group.add_argument("--all", action="store_true", help="Run every symbol in config/watchlist.json.")
    parser.add_argument("--start", required=True, type=parse_date, help="Inclusive backtest start date (YYYY-MM-DD).")
    parser.add_argument("--end", required=True, type=parse_date, help="Inclusive backtest end date (YYYY-MM-DD).")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument("--horizons", nargs="+", type=int, default=[1, 5, 20], metavar="TRADING_DAYS")
    parser.add_argument(
        "--news-provider",
        choices=["all", "polygon", "finnhub", "alpha_vantage", "benzinga", "tiingo"],
        default="polygon",
        help="Historical API source, or all historical-capable APIs. RSS feeds are current-only.",
    )
    parser.add_argument("--output", help="Output JSON path; defaults to newstrading/data/backtests/<timestamp>.json.")
    args = parser.parse_args()
    if args.end <= args.start:
        parser.error("--end must be after --start")
    if any(horizon <= 0 for horizon in args.horizons):
        parser.error("--horizons values must be positive")
    api_key_name = {
        "polygon": "POLYGON_API_KEY",
        "finnhub": "FINNHUB_API_KEY",
        "alpha_vantage": "ALPHAVANTAGE_API_KEY",
        "benzinga": "BENZINGA_API_KEY",
        "tiingo": "TIINGO_API_KEY",
    }.get(args.news_provider)
    api_key = os.getenv(api_key_name) if api_key_name else None
    if args.news_provider != "all" and not api_key:
        parser.error(f"{args.news_provider.upper()}_API_KEY is required to retrieve historical news")

    symbols = [args.symbol.upper()] if args.symbol else all_symbols()
    results: Dict[str, Any] = {
        "methodology": "Daily as-of signals; next-trading-day entry; adjusted close forward returns.",
        "warning": "Backtest evidence is not proof of future profitability. Review coverage, costs, and out-of-sample results.",
        "symbols": {},
    }
    for symbol in symbols:
        print(f"Backtesting {symbol}...")
        results["symbols"][symbol] = run_symbol_backtest(
            symbol,
            args.start,
            args.end,
            api_key,
            args.horizons,
            args.lookback_days,
            args.news_provider,
        )
        for horizon, summary in results["symbols"][symbol]["horizons"].items():
            correlation = summary["regression"]["correlation"]
            print(f"  {horizon}d: samples={summary['samples']} trades={summary['actionable_trades']} correlation={correlation}")

    output = Path(args.output) if args.output else DATA_DIR / "backtests" / f"backtest_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.json"
    save_json(output, results)
    print(f"Results -> {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())