"""News-driven trading signal and paper-trading demo for Alphabet (GOOGL/GOOG).

This script is organized around three layers:
1. News ingestion: pull GOOGL/Alphabet news from Finnhub when an API key exists,
   otherwise use demo stories for a dry-run workflow.
2. Sentiment and signal engine: score headlines/summaries, associate them with
   topics like AI, cloud, earnings, or antitrust, and convert them into a BUY/
   HOLD/SELL recommendation.
3. Paper trading: simulate a simple cash-based trade strategy that reacts to the
   generated news signal, with no live broker execution.

Example usage:
    python google_news_agent.py --demo
    python google_news_agent.py --demo --paper-trade
    FINNHUB_API_KEY=... python google_news_agent.py --symbol GOOGL --days 7
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib import parse, request

try:
    import yfinance as yf
except Exception:  # pragma: no cover - optional dependency
    yf = None


DEFAULT_SYMBOL = "GOOGL"
DEFAULT_DAYS = 7
POSITIVE_KEYWORDS = {
    "beat",
    "beats",
    "surge",
    "surges",
    "strong",
    "growth",
    "accelerat",
    "higher",
    "rally",
    "revenue",
    "cloud",
    "ai",
    "artificial intelligence",
    "expansion",
    "upgrade",
    "upbeat",
    "gain",
    "profit",
    "record",
    "raise",
    "outlook",
    "demand",
    "wins",
    "renewal",
    "pricing",
}
NEGATIVE_KEYWORDS = {
    "miss",
    "misses",
    "decline",
    "declining",
    "drop",
    "drops",
    "slowdown",
    "weak",
    "sluggish",
    "lawsuit",
    "litigation",
    "antitrust",
    "regulatory",
    "risk",
    "pressure",
    "cut",
    "downgrade",
    "loss",
    "pullback",
    "concern",
    "underperform",
    "uncertain",
    "delay",
    "softness",
    "overhang",
}
TOPIC_KEYWORDS = {
    "earnings": {"earnings", "revenue", "profit", "guidance", "quarter"},
    "cloud": {"cloud", "gcp", "google cloud", "ai infrastructure"},
    "ai": {"ai", "artificial intelligence", "gemini", "search ai"},
    "antitrust": {"antitrust", "lawsuit", "regulatory", "court"},
    "search": {"search", "ad revenue", "ads", "traffic"},
    "products": {"pixel", "android", "youtube", "chrome", "launch"},
}


def normalize_symbol(symbol: str) -> str:
    symbol = (symbol or DEFAULT_SYMBOL).upper().strip()
    if symbol in {"GOOG", "GOOGL"}:
        return "GOOGL"
    return symbol


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return None


def safe_json_get(url: str) -> Any:
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with request.urlopen(req, timeout=20) as resp:
        payload = resp.read().decode("utf-8", errors="replace")
        return json.loads(payload)


def fetch_finnhub_news(symbol: str, days: int = DEFAULT_DAYS, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
    if not api_key:
        api_key = os.getenv("FINNHUB_API_KEY")
    if not api_key:
        raise RuntimeError("FINNHUB_API_KEY is not set. Use --demo or export FINNHUB_API_KEY.")
    from_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    to_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = (
        "https://finnhub.io/api/v1/company-news"
        f"?symbol={parse.quote(symbol)}&from={from_date}&to={to_date}&token={api_key}"
    )
    data = safe_json_get(url)
    if not isinstance(data, list):
        return []

    articles: List[Dict[str, Any]] = []
    for item in data:
        date_value = item.get("datetime")
        dt_value = datetime.utcfromtimestamp(int(date_value)) if date_value else None
        headline = item.get("headline") or item.get("summary") or "Alphabet news"
        summary = item.get("summary") or headline
        articles.append(
            {
                "published_at": dt_value.isoformat() if dt_value else None,
                "headline": headline,
                "summary": summary,
                "source": item.get("source") or "Finnhub",
                "url": item.get("url") or "",
            }
        )
    return articles


def demo_news(symbol: str, days: int = DEFAULT_DAYS) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    articles = [
        {
            "published_at": (now - timedelta(hours=2)).isoformat(),
            "headline": "Alphabet says AI infrastructure and cloud demand are accelerating across Google Cloud",
            "summary": "Google Cloud customers are expanding AI workloads, supporting stronger revenue growth and a more bullish outlook for the business.",
            "source": "Demo",
            "url": "https://example.com/google-ai-cloud",
        },
        {
            "published_at": (now - timedelta(days=1)).isoformat(),
            "headline": "Regulators increase scrutiny on Google antitrust and ad market strategies",
            "summary": "Analysts warn that antitrust and regulatory probes may pressure search ad profitability and raise legal uncertainty.",
            "source": "Demo",
            "url": "https://example.com/google-antitrust",
        },
        {
            "published_at": (now - timedelta(days=2)).isoformat(),
            "headline": "Alphabet beats analyst estimates as cloud and search revenue both accelerate",
            "summary": "Alphabet posted better-than-expected results with strong ad monetization and accelerating cloud growth across multiple regions.",
            "source": "Demo",
            "url": "https://example.com/google-beat",
        },
        {
            "published_at": (now - timedelta(days=4)).isoformat(),
            "headline": "Google AI spending raises concerns about margins and capital intensity",
            "summary": "Higher AI capex and infrastructure investments could pressure margins in the near term as Alphabet invests into future capacity.",
            "source": "Demo",
            "url": "https://example.com/google-ai-costs",
        },
    ]
    return articles[: max(1, min(len(articles), max(1, days)))]


def tokenize(text: str) -> List[str]:
    return re.findall(r"[a-zA-Z0-9\+\-]{3,}", (text or "").lower())


def match_keywords(text: str, keyword_set: Iterable[str]) -> int:
    tokens = set(tokenize(text))
    hits = 0
    for term in keyword_set:
        term_tokens = term.split()
        if len(term_tokens) > 1:
            if term in text.lower():
                hits += 1
        else:
            if term in tokens:
                hits += 1
    return hits


def infer_topic(text: str) -> str:
    topic_scores = {}
    for topic, keywords in TOPIC_KEYWORDS.items():
        score = match_keywords(text, keywords)
        topic_scores[topic] = score
    if not any(topic_scores.values()):
        return "general"
    return max(topic_scores.items(), key=lambda item: item[1])[0]


def article_sentiment_score(article: Dict[str, Any]) -> Dict[str, Any]:
    headline = article.get("headline") or ""
    summary = article.get("summary") or ""
    text = f"{headline} {summary}".lower()
    positive_hits = match_keywords(text, POSITIVE_KEYWORDS)
    negative_hits = match_keywords(text, NEGATIVE_KEYWORDS)
    score = (positive_hits - negative_hits) / max(1, positive_hits + negative_hits + 1)
    if positive_hits > negative_hits:
        sentiment = "positive"
    elif negative_hits > positive_hits:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    return {
        "headline": headline,
        "summary": summary,
        "sentiment_score": float(score),
        "sentiment": sentiment,
        "positive_hits": positive_hits,
        "negative_hits": negative_hits,
        "topic": infer_topic(text),
        "published_at": article.get("published_at"),
        "source": article.get("source"),
        "url": article.get("url"),
    }


def get_price_context(symbol: str, lookback_days: int = 30) -> Optional[Dict[str, Any]]:
    if yf is None:
        return None
    try:
        data = yf.download(symbol, period=f"{lookback_days}d", progress=False, auto_adjust=True)
        if data.empty or "Close" not in data.columns:
            return None
        close = data["Close"].dropna()
        if close.empty:
            return None
        last_close = close.iloc[-1]
        if hasattr(last_close, "item"):
            last_close = last_close.item()
        price = float(last_close)
        sma = close.rolling(window=20, min_periods=1).mean()
        last_sma = sma.iloc[-1]
        if hasattr(last_sma, "item"):
            last_sma = last_sma.item()
        sma_20 = float(last_sma)
        return {
            "price": price,
            "sma_20": sma_20,
            "trend_ratio": float(price / sma_20) if sma_20 else 1.0,
            "symbol": symbol,
        }
    except Exception:
        return None


def aggregate_signal(articles: List[Dict[str, Any]], price_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    scored = [article_sentiment_score(article) for article in articles]
    if not scored:
        return {
            "decision": "HOLD",
            "score": 0.0,
            "confidence": 0.0,
            "positive_count": 0,
            "negative_count": 0,
            "articles": [],
            "topic": "general",
        }

    avg_score = sum(item["sentiment_score"] for item in scored) / len(scored)
    pos_count = sum(1 for item in scored if item["sentiment"] == "positive")
    neg_count = sum(1 for item in scored if item["sentiment"] == "negative")
    topic = max(
        ((item["topic"], 1) for item in scored),
        key=lambda pair: pair[1],
    )[0]

    technical_adjustment = 0.0
    if price_context:
        ratio = price_context.get("trend_ratio", 1.0)
        if ratio > 1.02:
            technical_adjustment += 0.5
        elif ratio < 0.98:
            technical_adjustment -= 0.5

    combined_signal = avg_score * 3.0 + technical_adjustment + (0.2 * (pos_count - neg_count))
    if combined_signal >= 1.0:
        decision = "BUY"
    elif combined_signal <= -1.0:
        decision = "SELL"
    else:
        decision = "HOLD"

    confidence = min(0.99, max(0.0, abs(combined_signal) / 4.0))
    return {
        "decision": decision,
        "score": float(combined_signal),
        "confidence": float(confidence),
        "positive_count": pos_count,
        "negative_count": neg_count,
        "articles": scored,
        "topic": topic,
    }


def paper_trade_signal(symbol: str, signal: Dict[str, Any], price_context: Optional[Dict[str, Any]] = None, cash: float = 100_000.0) -> Dict[str, Any]:
    price = (price_context or {}).get("price")
    if price is None:
        price = 150.0

    position_shares = 0
    initial_cash = cash
    trades: List[Dict[str, Any]] = []

    decision = signal.get("decision")
    score = signal.get("score", 0.0)

    if decision == "BUY" and cash > 0:
        buy_fraction = 0.25
        allocation = cash * buy_fraction
        shares = int(allocation // price)
        if shares > 0:
            cash -= shares * price
            position_shares = shares
            trades.append({"type": "BUY", "shares": shares, "price": price, "score": score})
    elif decision == "SELL" and position_shares > 0:
        cash += position_shares * price
        trades.append({"type": "SELL", "shares": position_shares, "price": price, "score": score})
        position_shares = 0

    final_value = cash + (position_shares * price)
    pnl = final_value - initial_cash
    return {
        "symbol": symbol,
        "initial_cash": initial_cash,
        "final_value": final_value,
        "pnl": pnl,
        "position_shares": position_shares,
        "decision": decision,
        "score": score,
        "trades": trades,
    }


def print_article_summary(articles: List[Dict[str, Any]], max_items: int = 5) -> None:
    if not articles:
        print("No articles returned.")
        return
    print("Recent relevant articles:")
    for item in articles[:max_items]:
        dt_value = parse_dt(item.get("published_at"))
        time_label = dt_value.strftime("%Y-%m-%d %H:%M UTC") if dt_value else "unknown time"
        print(f"  - [{time_label}] {item.get('headline', 'News')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor GOOGL/Alphabet news and translate it into a simple BUY/HOLD/SELL trigger.")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="Ticker to watch, e.g. GOOGL or GOOG.")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help="How many days of news to review.")
    parser.add_argument("--demo", action="store_true", help="Use demo news instead of live Finnhub data.")
    parser.add_argument("--paper-trade", action="store_true", help="Simulate a paper-trade decision based on the generated signal.")
    parser.add_argument("--api-key", default=None, help="Optional Finnhub API key (or set FINNHUB_API_KEY).")
    parser.add_argument("--show-articles", action="store_true", help="Print a compact list of recent articles for review.")
    args = parser.parse_args()

    symbol = normalize_symbol(args.symbol)
    if args.days <= 0:
        parser.error("--days must be positive")

    if args.demo:
        articles = demo_news(symbol, days=args.days)
    else:
        try:
            articles = fetch_finnhub_news(symbol, days=args.days, api_key=args.api_key)
        except Exception as exc:
            print(f"Live news fetch failed: {exc}")
            print("Falling back to demo data.")
            articles = demo_news(symbol, days=args.days)

    price_context = get_price_context(symbol, lookback_days=30)
    signal = aggregate_signal(articles, price_context=price_context)

    print(f"Alphabet news signal for {symbol}")
    print(f"  Decision: {signal['decision']}")
    print(f"  Composite score: {signal['score']:.2f}")
    print(f"  Confidence: {signal['confidence']:.0%}")
    print(f"  Positive articles: {signal['positive_count']}")
    print(f"  Negative articles: {signal['negative_count']}")
    if price_context:
        print(
            f"  Price context: ${price_context['price']:.2f} vs SMA20 ${price_context['sma_20']:.2f} "
            f"(ratio {price_context['trend_ratio']:.2f})"
        )
    else:
        print("  Price context: unavailable (yfinance not installed or market data unavailable)")

    if args.show_articles or args.paper_trade:
        print_article_summary(articles)

    if args.paper_trade:
        result = paper_trade_signal(symbol, signal, price_context=price_context)
        print("\nPaper-trade summary:")
        print(f"  Cash: ${result['initial_cash']:,.2f} -> ${result['final_value']:,.2f}")
        print(f"  P&L: ${result['pnl']:,.2f}")
        print(f"  Position: {result['position_shares']} shares")
        for trade in result["trades"]:
            print(f"  {trade['type']} {trade['shares']} @ ${trade['price']:.2f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
