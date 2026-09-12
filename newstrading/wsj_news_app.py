"""WSJ-authenticated news app for a Google/Alphabet news signal pipeline.

This app performs the following steps:
1. Logs into WSJ using a user account (environment variables: WSJ_USERNAME, WSJ_PASSWORD)
2. Uses an authenticated session to fetch WSJ article/search pages
3. Extracts headline, byline, timestamp, summary, URL, and article text
4. Normalizes the data into a common schema
5. Scores relevance and sentiment, weighted by source quality
6. Combines the WSJ results with other public sources (Reuters, Yahoo Finance, Google News, Finnhub, Polygon)

Examples:
    export WSJ_USERNAME=... WSJ_PASSWORD=...
    python wsj_news_app.py --symbol GOOGL --query "Alphabet AI cloud" --fetch-search
    python wsj_news_app.py --symbol GOOGL --article-url "https://www.wsj.com/articles/..."
    python wsj_news_app.py --demo
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import requests
from bs4 import BeautifulSoup

from google_news_pipeline import aggregate_signal, dedupe_articles, score_article


WSJ_LOGIN_URL = os.getenv("WSJ_LOGIN_URL", "https://accounts.wsj.com/login")
WSJ_SEARCH_URL = "https://www.wsj.com/search"
DEFAULT_DB_PATH = str(Path(__file__).resolve().parent / "wsj_news.db")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_env_or_fail(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    return session


def login_to_wsj(session: requests.Session, username: Optional[str] = None, password: Optional[str] = None) -> requests.Session:
    username = username or os.getenv("WSJ_USERNAME")
    password = password or os.getenv("WSJ_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "WSJ credentials are missing. Set WSJ_USERNAME and WSJ_PASSWORD or pass --username/--password."
        )

    try:
        return login_to_wsj_playwright(username=username, password=password)
    except Exception:
        login_url = os.getenv("WSJ_LOGIN_URL", WSJ_LOGIN_URL)
        resp = session.get(login_url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        form = soup.find("form")
        payload: Dict[str, str] = {}
        if form:
            for field in form.find_all("input"):
                name = field.get("name")
                value = field.get("value") or ""
                if name:
                    payload[name] = value

        if not payload:
            payload = {
                "username": username,
                "password": password,
                "submit": "Sign in",
            }
        else:
            payload["username"] = username
            payload["email"] = username
            payload["password"] = password
            payload["login"] = username

        action = form.get("action") if form else login_url
        target_url = action if action.startswith("http") else login_url
        login_resp = session.post(target_url, data=payload, timeout=30, allow_redirects=True)
        login_resp.raise_for_status()

        if "login" in login_resp.url.lower() and "error" in login_resp.text.lower():
            raise RuntimeError("WSJ login failed. Check your WSJ_USERNAME and WSJ_PASSWORD or login flow.")

        return session


def login_to_wsj_playwright(username: Optional[str] = None, password: Optional[str] = None) -> requests.Session:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("playwright is not installed; install it with pip install playwright") from exc

    username = username or os.getenv("WSJ_USERNAME")
    password = password or os.getenv("WSJ_PASSWORD")
    if not username or not password:
        raise RuntimeError("WSJ_PLAYWRIGHT login requires WSJ_USERNAME and WSJ_PASSWORD")

    login_url = os.getenv("WSJ_LOGIN_URL", WSJ_LOGIN_URL)
    session = requests.Session()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(login_url, wait_until="networkidle")
        selectors = [
            "input[name='email']",
            "input[name='username']",
            "input[type='email']",
            "input[id='email']",
            "input[id='username']",
            "input[name='login']",
        ]
        filled = False
        for selector in selectors:
            try:
                page.locator(selector).fill(username)
                filled = True
                break
            except Exception:
                continue
        if not filled:
            raise RuntimeError("Could not find the WSJ username field on the login page")

        password_selectors = [
            "input[name='password']",
            "input[type='password']",
            "input[id='password']",
        ]
        for selector in password_selectors:
            try:
                page.locator(selector).fill(password)
                break
            except Exception:
                continue
        submit_selectors = [
            "button[type='submit']",
            "button:has-text('Sign in')",
            "button:has-text('Log in')",
            "input[type='submit']",
        ]
        clicked = False
        for selector in submit_selectors:
            try:
                page.locator(selector).click()
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise RuntimeError("Could not find the WSJ login submit button")

        page.wait_for_timeout(5000)
        for cookie in page.context.cookies():
            session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path"))
        browser.close()
    return session


def fetch_url(session: requests.Session, url: str) -> str:
    resp = session.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text


def extract_meta_value(soup: BeautifulSoup, attrs: Sequence[str]) -> Optional[str]:
    for attr in attrs:
        meta = soup.select_one(f"meta[{attr}]")
        if meta and meta.get("content"):
            return meta["content"].strip()
    return None


def parse_article_html(html: str, url: str = "") -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")

    headline = (
        extract_meta_value(soup, ["property=og:title", "name=twitter:title"]) or
        soup.find("h1") and soup.find("h1").get_text(" ", strip=True) or
        ""
    )

    byline = (
        extract_meta_value(soup, ["name=author", "property=article:author"]) or
        (soup.select_one(".byline") and soup.select_one(".byline").get_text(" ", strip=True)) or
        ""
    )

    published = (
        extract_meta_value(soup, ["property=article:published_time", "name=parsely-pub-date", "name=date"]) or
        ""
    )

    summary = (
        extract_meta_value(soup, ["property=og:description", "name=description"]) or
        (soup.select_one("meta[name='description']") and soup.select_one("meta[name='description']").get("content", "")) or
        ""
    )

    article_text = []
    article_tag = soup.select_one("article") or soup.select_one("main")
    if article_tag:
        for node in article_tag.find_all(["p", "h2", "h3"]):
            text = node.get_text(" ", strip=True)
            if text:
                article_text.append(text)
    if not article_text:
        for node in soup.find_all("p"):
            text = node.get_text(" ", strip=True)
            if len(text) > 40:
                article_text.append(text)

    text = " ".join(article_text)
    return {
        "source": "WSJ",
        "title": headline,
        "byline": byline,
        "published_at": published,
        "summary": summary,
        "url": url,
        "text": text,
    }


def find_article_links(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: List[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not href:
            continue
        if any(token in href for token in ["/articles/", "/article/", "/news/"]):
            if href.startswith("/"):
                href = "https://www.wsj.com" + href
            links.append(href)
    out: List[str] = []
    seen = set()
    for link in links:
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out


def fetch_wsj_search_results(session: requests.Session, query: str, max_links: int = 10) -> List[str]:
    params = {"query": query, "mod": "searchresults_viewallresults"}
    url = WSJ_SEARCH_URL
    html = fetch_url(session, url + "?" + requests.compat.urlencode(params))
    return find_article_links(html)[:max_links]


def init_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS news_articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT,
            byline TEXT,
            url TEXT UNIQUE,
            published_at TEXT,
            article_text TEXT,
            symbol TEXT,
            topic TEXT,
            sentiment TEXT,
            sentiment_score REAL,
            relevance REAL,
            source_weight REAL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def save_article_record(conn: sqlite3.Connection, article: Dict[str, Any], symbol: str = "GOOGL") -> None:
    article_url = article.get("url") or ""
    if not article_url:
        return
    existing = conn.execute(
        "SELECT 1 FROM news_articles WHERE url = ?",
        (article_url,),
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE news_articles
            SET source = ?, title = ?, summary = ?, byline = ?, published_at = ?, article_text = ?,
                symbol = ?, topic = ?, sentiment = ?, sentiment_score = ?, relevance = ?, source_weight = ?, created_at = ?
            WHERE url = ?
            """,
            (
                article.get("source"),
                article.get("title"),
                article.get("summary"),
                article.get("byline"),
                article.get("published_at"),
                article.get("text"),
                symbol,
                article.get("topic"),
                article.get("sentiment"),
                article.get("sentiment_score"),
                article.get("relevance"),
                article.get("source_weight"),
                now_iso(),
                article_url,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO news_articles (
                source, title, summary, byline, url, published_at, article_text, symbol, topic,
                sentiment, sentiment_score, relevance, source_weight, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                article.get("source"),
                article.get("title"),
                article.get("summary"),
                article.get("byline"),
                article_url,
                article.get("published_at"),
                article.get("text"),
                symbol,
                article.get("topic"),
                article.get("sentiment"),
                article.get("sentiment_score"),
                article.get("relevance"),
                article.get("source_weight"),
                now_iso(),
            ),
        )
    conn.commit()


def normalize_wsj_article(raw: Dict[str, Any]) -> Dict[str, Any]:
    article = {
        "source": "WSJ",
        "title": raw.get("title") or "",
        "summary": raw.get("summary") or "",
        "url": raw.get("url") or "",
        "published_at": raw.get("published_at") or now_iso(),
        "byline": raw.get("byline") or "",
        "text": raw.get("text") or "",
    }
    if not article["title"]:
        article["title"] = "WSJ article"
    if not article["summary"]:
        article["summary"] = article["text"][:240]
    return article


def article_from_url(session: requests.Session, url: str) -> Dict[str, Any]:
    html = fetch_url(session, url)
    raw = parse_article_html(html, url)
    normalized = normalize_wsj_article(raw)
    return normalized


def choose_query(symbol: str, keyword: Optional[str] = None) -> str:
    if keyword:
        return f"{symbol} {keyword}"
    return f"{symbol} Alphabet Google AI cloud"


def build_demo_wsj_article() -> Dict[str, Any]:
    return {
        "source": "WSJ",
        "title": "Alphabet's Cloud Business Keeps Gaining as AI Demand Rises",
        "summary": "Google Cloud demand remains strong as enterprise AI workloads accelerate and customer spend rises.",
        "url": "https://www.wsj.com/articles/alphabet-cloud-ai-demand-rises-123",
        "published_at": "2026-09-12T12:00:00Z",
        "byline": "Patricia Kwan",
        "text": (
            "Alphabet's cloud business continues to gain momentum as enterprise customers expand AI workloads. "
            "The company reported stronger usage across its data-center footprint and a favorable outlook for cloud spending. "
            "Analysts remain constructive on the long-term growth profile even as AI infrastructure costs rise."
        ),
    }


def lookup_public_sources(symbols: Sequence[str]) -> List[Dict[str, Any]]:
    try:
        from google_news_pipeline import (
            GoogleNewsRSSSource,
            ReutersRSSSource,
            YahooFinanceRSSSource,
            FinnhubNewsSource,
            PolygonNewsSource,
        )
    except Exception:
        return []

    source_instances = [
        ReutersRSSSource(),
        YahooFinanceRSSSource(),
        GoogleNewsRSSSource(),
        FinnhubNewsSource(os.getenv("FINNHUB_API_KEY")),
        PolygonNewsSource(os.getenv("POLYGON_API_KEY")),
    ]
    articles: List[Dict[str, Any]] = []
    for source in source_instances:
        try:
            articles.extend(source.fetch(symbols, lookback_days=7))
        except Exception:
            continue
    return dedupe_articles(articles)


def score_and_aggregate(symbols: Sequence[str], wsj_articles: Sequence[Dict[str, Any]], db_path: str = DEFAULT_DB_PATH, save_to_db: bool = True) -> Dict[str, Any]:
    public_articles = lookup_public_sources(symbols)
    all_articles = list(public_articles) + list(wsj_articles)
    scored = [score_article(item) for item in all_articles if item.get("title")]
    scored = [item for item in scored if item["relevance"] >= 0.15]
    signal = aggregate_signal(scored)

    if save_to_db:
        conn = init_db(db_path)
        for article in all_articles:
            normalized = article.copy()
            normalized["source_weight"] = 1.0 if article.get("source") == "WSJ" else 0.7
            normalized["topic"] = "general"
            normalized["sentiment"] = "neutral"
            normalized["sentiment_score"] = 0.0
            normalized["relevance"] = 0.0
            save_article_record(conn, normalized, symbol=symbols[0] if symbols else "GOOGL")
        conn.close()

    return {"signal": signal, "articles": scored}


def print_result(result: Dict[str, Any]) -> None:
    signal = result["signal"]
    print("=" * 72)
    print("WSJ + public-source signal")
    print("=" * 72)
    print(f"Decision: {signal['decision']} | score={signal['score']:.3f} | confidence={signal['confidence']:.0%}")
    print(f"Positive: {signal['positive']} | Negative: {signal['negative']}")
    print("-" * 72)
    for article in signal["articles"][:10]:
        print(f"[{article['source']}] {article['sentiment']} | {article['topic']} | {article['title']}")
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch WSJ articles and combine them with public sources for a Google news signal.")
    parser.add_argument("--symbol", default="GOOGL", help="Ticker to analyze, e.g. GOOGL or GOOG")
    parser.add_argument("--query", default=None, help="Optional WSJ search query; e.g. 'Alphabet AI cloud'")
    parser.add_argument("--article-url", default=None, help="Fetch a specific WSJ article URL and parse it.")
    parser.add_argument("--fetch-search", action="store_true", help="Perform a WSJ search and fetch article links for the symbol/query.")
    parser.add_argument("--username", default=None, help="WSJ username/email (or set WSJ_USERNAME)")
    parser.add_argument("--password", default=None, help="WSJ password (or set WSJ_PASSWORD)")
    parser.add_argument("--demo", action="store_true", help="Use a sample WSJ article for dry-run testing.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="Path to SQLite database file for storing fetched article records.")
    args = parser.parse_args()

    try:
        if args.demo:
            demo_article = build_demo_wsj_article()
            result = score_and_aggregate([args.symbol], [demo_article], db_path=args.db_path, save_to_db=True)
            print_result(result)
            return 0

        if args.article_url:
            session = build_session()
            session = login_to_wsj(session, username=args.username, password=args.password)
            article = article_from_url(session, args.article_url)
            conn = init_db(args.db_path)
            save_article_record(conn, article, symbol=args.symbol)
            conn.close()
            print(json.dumps(article, indent=2, sort_keys=True))
            return 0

        if args.fetch_search:
            session = build_session()
            session = login_to_wsj(session, username=args.username, password=args.password)
            query = args.query or choose_query(args.symbol)
            links = fetch_wsj_search_results(session, query, max_links=5)
            print(json.dumps({"query": query, "links": links}, indent=2, sort_keys=True))
            return 0

        session = build_session()
        session = login_to_wsj(session, username=args.username, password=args.password)
        query = args.query or choose_query(args.symbol)
        links = fetch_wsj_search_results(session, query, max_links=3)
        articles = [article_from_url(session, link) for link in links]
        result = score_and_aggregate([args.symbol], articles, db_path=args.db_path, save_to_db=True)
        print_result(result)
        return 0

    except Exception as exc:
        print(f"WSJ app failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
