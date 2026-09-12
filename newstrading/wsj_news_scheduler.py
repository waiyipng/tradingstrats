"""Background scheduler for WSJ + public-sources news ingestion.

This service continuously fetches Alphabet/Google-related WSJ articles and ingests
fetches into a SQLite database while also computing a signal score. It is a simple,
dependency-light scheduler intended to run in the background on a workstation or
VM.

Examples:
    python wsj_news_scheduler.py --symbol GOOGL --interval 300
    WSJ_USERNAME=... WSJ_PASSWORD=... python wsj_news_scheduler.py --symbol GOOGL --interval 1800
"""

from __future__ import annotations

import argparse
import time
import sys
from pathlib import Path
from typing import Optional

from wsj_news_app import (
    DEFAULT_DB_PATH,
    build_session,
    choose_query,
    fetch_wsj_search_results,
    article_from_url,
    login_to_wsj,
    score_and_aggregate,
)


def run_once(symbol: str, query: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None, db_path: str = DEFAULT_DB_PATH) -> dict:
    """Perform a single fetch/score cycle.

    username/password are optional and will fall back to environment variables
    inside login_to_wsj if omitted.
    """
    session = build_session()
    # Explicitly pass password; login_to_wsj will read from env if password is None.
    session = login_to_wsj(session, username=username, password=password)
    query_text = query or choose_query(symbol)
    links = fetch_wsj_search_results(session, query_text, max_links=5)
    articles = [article_from_url(session, link) for link in links]
    result = score_and_aggregate([symbol], articles, db_path=db_path, save_to_db=True)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a background scheduler that ingests WSJ and public-source news into SQLite.")
    parser.add_argument("--symbol", default="GOOGL", help="Ticker to monitor, e.g. GOOGL or GOOG")
    parser.add_argument("--query", default=None, help="Optional WSJ search query; defaults to Alphabet/Google AI cloud search.")
    parser.add_argument("--interval", type=int, default=300, help="Polling interval in seconds.")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH, help="SQLite database path for storing article records.")
    parser.add_argument("--username", default=None, help="WSJ username/email or set WSJ_USERNAME")
    parser.add_argument("--password", default=None, help="WSJ password or set WSJ_PASSWORD")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit instead of looping indefinitely.")
    args = parser.parse_args()

    if args.interval <= 0:
        parser.error("--interval must be positive")

    try:
        if args.once:
            result = run_once(args.symbol, query=args.query, username=args.username, password=args.password, db_path=args.db_path)
            print(result["signal"])
            return 0

        print(f"Starting WSJ news scheduler for {args.symbol}; interval={args.interval}s")
        while True:
            result = run_once(args.symbol, query=args.query, username=args.username, password=args.password, db_path=args.db_path)
            print(f"[{__import__('datetime').datetime.utcnow().isoformat()}] signal={result['signal']['decision']} score={result['signal']['score']:.3f}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopping WSJ news scheduler.")
        return 0
    except Exception as exc:
        print(f"Scheduler failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
