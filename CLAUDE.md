# tradingstrats

`tradingstrats` contains two Python trading research and automation projects:

- `newstrading/`: a news-driven equity strategy that collects company news, scores sentiment, produces BUY/SELL/HOLD signals, sizes orders, applies risk controls, and routes to a local simulator or Interactive Brokers.
- `optiontrading/`: scripts and research for VOO options and wheel-style strategies.
- `wheeltrading/`: an independent, automated IBKR paper-only wheel strategy for GOOGL and VOO.

## Newstrading pipeline

The scheduled news-trading pipeline runs these stages for every configured symbol:

```text
sourcing -> signaling -> order_recommendation -> execution
```

1. `sourcing` fetches and normalizes provider news, deduplicates articles, and writes `data/news_batches/<SYMBOL>/` artifacts.
2. `signaling` applies sector keyword scoring, recency/source weighting, and market-trend context to produce `BUY`, `SELL`, or `HOLD` signals in `data/signals/<SYMBOL>/`.
3. `order_recommendation` uses the IBKR account snapshot and sector allocation caps to create limit-order recommendations in `data/order_recommendations/<SYMBOL>/`.
4. `execution` applies independent risk checks and routes to the selected broker, writing reports to `data/execution_reports/<SYMBOL>/`.

The watchlist is in `newstrading/config/watchlist.json`. Xero is represented by `XRO`, routed through IBKR as `ASX` / `AUD`, and uses `XRO.AX` for market data.

## News-source policy

US symbols include SEC EDGAR as a primary-source filing feed. Set a descriptive contact value before using it:

```bash
export SEC_USER_AGENT="tradingstrats research contact@example.com"
```

Paid feeds are marked `unconfigured` until their API-key environment variable is set. Provider results are retained as `ok`, `empty`, `failed`, or `unconfigured` in the audit trail. A BUY signal requires at least one `primary` or `professional` source, or corroboration from two independent `secondary` sources. Tiingo requires a separate News API entitlement beyond a general Tiingo token. Reuters discovery uses a Reuters-restricted Google News RSS search because the legacy direct Reuters RSS host was retired; treat it as a secondary source. Do not scrape the public ASX announcements website; use a licensed ASX announcement/data feed before treating XRO disclosure events as a primary source.

## Current operating mode

`newstrading/scheduler.py` is currently configured for Interactive Brokers **paper** trading:

```python
BROKER = "ibkr"
EXECUTE = True
USE_LIVE_IBKR = False
RUN_INTERVAL_MINUTES = 15
```

`USE_LIVE_IBKR = False` must remain false unless the user explicitly requests live trading. The scheduler requires a running, API-enabled IBKR TWS or Gateway connection on paper port `7497`.

Do not submit manual orders, alter active broker configuration, cancel orders, or start/stop the scheduler without an explicit user request.

## Risk and exits

IBKR BUY orders use a linked bracket: limit entry, `+6%` take-profit, and `-3%` stop-loss. Each actionable BUY requests a fixed 20 shares. The scheduler evaluates all symbols before execution, ranks eligible BUYs by confidence multiplied by evidence quality (`primary` 1.35, `professional` 1.15, `secondary` 1.00), and selects candidates within the remaining daily budget. The risk gate blocks duplicate buys, caps gross allocation at 50% of net liquidation, and caps each day's completed plus open BUY notional at 30% of net liquidation. The position monitor exits tracked strategy positions on a fresh `SELL` signal or after five days.

The separate VOO order used for initial testing is not a strategy-managed position and must not be adopted, altered, or closed by strategy code.

## Decision audit trail

Every new scheduler cycle creates `newstrading/data/audit_runs/<audit_run_id>.json` and automatically deletes records older than 14 days. Audit records retain:

- provider fetch status and article counts
- raw headlines, summaries, URLs, and deduplication outcomes
- keyword hits, sentiment, recency weights, normalized weights, and per-article contribution
- aggregate signal calculation, recommendation, risk outcome, and execution result

Preserve the audit run ID across pipeline stages when adding or modifying a stage. Do not delete audit artifacts outside the retention mechanism.

## Dashboard

`dashboard/` is a local React/Vite operations console. `dashboard/server.py` is a read-only Python API that serves equity strategy artifacts, scheduler events, timing, audit records, and wheel status. The dashboard does not contain broker credentials or execution endpoints.

Run locally:

```bash
/usr/local/bin/python3 dashboard/server.py
pnpm --dir dashboard dev -- --host 127.0.0.1
```

The dashboard refreshes artifacts periodically. Maintain it as an observability surface; do not add one-click order execution controls without explicit confirmation and strong confirmation safeguards.

## Wheel strategy

`wheeltrading/` is independent from `newstrading/` and automates IBKR paper-only wheel orders for GOOGL and VOO:

- With fewer than 100 active wheel shares, it screens cash-secured puts.
- With at least 100 active wheel shares, it screens covered calls.
- It targets 21-45 DTE, approximately 5% out-of-the-money strikes, 0.15-0.30 absolute delta, one contract, and an 8% minimum annualized premium yield.
- It caps a cash-secured put's collateral at 10% of net liquidation.

The wheel scheduler runs every 30 minutes and may submit one-contract IBKR paper option orders only after quote/delta, duplicate-short-position, contract-qualification, bid, and cash-collateral checks pass. If option data is unavailable, it records `data_unavailable` and submits no order. Do not enable live option execution without explicit approval and an approval-gated design. Wheel status is read-only in the dashboard. Only lots explicitly registered as wheel put assignments are eligible to cover wheel calls; GOOGL or VOO shares owned by the equity-signal strategy or externally are displayed as `external` and must never trigger a wheel covered call. A registered assigned-put lot moves into `wheeltrading/data/wheel_state.json`'s `stock_pool` when its market price is at least 10% below the assignment strike. Pooled shares retain their assigned strike as average cost, are excluded from covered-call eligibility, and allow the active wheel to return to screening new cash-secured puts.

## Development checks

Use the configured interpreter for Python commands:

```bash
/usr/local/bin/python3 -m compileall -q newstrading dashboard/server.py
pnpm --dir dashboard build
git diff --check
```

Keep JSON artifacts and existing execution reports intact. Avoid broad formatting or unrelated refactors. See `newstrading/STRATEGY.md` for the strategy contract and `newstrading/BACKTEST_RESEARCH.md` for research constraints.