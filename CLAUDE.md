# tradingstrats

`tradingstrats` contains two Python trading research and automation projects:

- `newstrading/`: a news-driven equity strategy that collects company news, scores sentiment, produces BUY/SELL/HOLD signals, sizes orders, applies risk controls, and routes to a local simulator or Interactive Brokers.
- `optiontrading/`: scripts and research for VOO options and wheel-style strategies.
- `wheeltrading/`: an independent, automated IBKR wheel strategy for GOOGL and VOO (paper by default; see [Broker mode](#broker-mode)).
- `goldtrading/`: an independent, automated IBKR gold cash-and-carry and calendar-spread strategy (paper by default; see [Broker mode](#broker-mode)).
- `btctrend/`: an independent, automated IBKR, long-only bitcoin trend-following strategy (paper by default; see [Broker mode](#broker-mode)): a backtested 9-signal ensemble decides exposure, with a 4x ATR trailing stop and a one-time profit trim.
- `bullcallspread/`: an independent, agentic MS bull call spread tool (paper by default; see [Broker mode](#broker-mode)). An analyst agent predicts the earnings-day stock price from the user's own net-income forecast, a trading agent selects and explains the best spread structure against live quotes, and placing the order remains a manual step.

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
USE_LIVE_IBKR = _CFG["mode"] == "live"   # from trading_config.json; see Broker mode below
RUN_INTERVAL_MINUTES = 30
```

`newstrading`'s `USE_LIVE_IBKR` is driven solely by `trading_config.json`'s `"newstrading".mode` (no second, per-process env-var confirmation like the other four strategies below) and must stay `"paper"` unless the user explicitly requests live trading. The scheduler requires a running, API-enabled IBKR TWS or Gateway connection on the resulting port (paper `7497` / live `7496`).

Do not submit manual orders, alter active broker configuration (including flipping `trading_config.json`'s `newstrading.mode` to `"live"`), cancel orders, or start/stop the scheduler without an explicit user request.

## Broker mode

`wheeltrading`, `goldtrading`, `btctrend`, and `bullcallspread` each read their broker mode (`"paper"` or `"live"`) and scheduler run interval from `trading_config.json` via `trading_config.get_strategy_config(<strategy>)`; `newstrading` reads only the mode (see above). `trading_config.json` defaults every strategy to `"paper"`; it currently has all four non-newstrading strategies set to `"live"`.

For these four, flipping `trading_config.json` to `"live"` is **not** sufficient on its own: each scheduler, and each strategy's manual CLI, also requires a matching per-process environment variable set to `"1"` before it will actually connect to IBKR's live port `7496` instead of paper port `7497`:

| Strategy | Env var |
|---|---|
| `wheeltrading` | `WHEELTRADING_LIVE_CONFIRM` |
| `goldtrading` | `GOLDTRADING_LIVE_CONFIRM` |
| `btctrend` | `BTCTREND_LIVE_CONFIRM` |
| `bullcallspread` | `BULLCALLSPREAD_LIVE_CONFIRM` |

This two-factor gate (config file + environment variable) means an edit to `trading_config.json` alone can never flip an already-running, unattended scheduler to live trading — the env var must also be set on the process itself, which for a scheduler means restarting it with that variable exported. Live mode only changes which IBKR account/port a strategy connects to for quotes, account data, and (where applicable) order routing; it does not bypass each strategy's own approval gates (wheel/gold/btctrend pending-approval queues, bullcallspread's `--confirm`) or risk checks. Do not flip any strategy's mode to `"live"`, or export any of the above env vars, without an explicit user request.

## Risk and exits

IBKR BUY orders use a linked bracket: limit entry, `+6%` take-profit, and `-3%` stop-loss. Each actionable BUY requests a fixed 20 shares. The scheduler evaluates all symbols before execution, ranks eligible BUYs by confidence multiplied by evidence quality (`primary` 1.35, `professional` 1.15, `secondary` 1.00), and selects candidates within the remaining daily budget. The risk gate blocks duplicate buys, caps gross allocation at 50% of net liquidation, and caps each day's completed plus open BUY notional at 30% of net liquidation. The position monitor exits tracked strategy positions on a fresh `SELL` signal or after five days.

Realized P&L is recorded in `newstrading/data/realized_pnl_ledger.json`: each position-monitor run copies closing stock fills placed by client id 22 (including bracket take-profit/stop-loss children) with IBKR's own realized P&L, keyed by execId, because TWS only exposes the current session's fills. Do not delete or rewrite ledger entries.

The separate VOO order used for initial testing is not a strategy-managed position and must not be adopted, altered, or closed by strategy code.

## Decision audit trail

Every new scheduler cycle creates `newstrading/data/audit_runs/<audit_run_id>.json` and automatically deletes records older than 14 days. Audit records retain:

- provider fetch status and article counts
- raw headlines, summaries, URLs, and deduplication outcomes
- keyword hits, sentiment, recency weights, normalized weights, and per-article contribution
- aggregate signal calculation, recommendation, risk outcome, and execution result

Preserve the audit run ID across pipeline stages when adding or modifying a stage. Do not delete audit artifacts outside the retention mechanism.

## Dashboard

`dashboard/` is a local React/Vite operations console. `dashboard/server.py` is a Python API that is read-only except for three explicit, confirmation-gated approve/reject endpoint pairs, each used to approve or reject a pending order a human must review before it reaches IBKR: `POST /api/btctrend-approve` / `-reject` (see the Bitcoin trend following section below), `POST /api/wheel-approve/<symbol>` / `-reject/<symbol>` (see the Wheel strategy section below), and `POST /api/goldtrading-approve` / `-reject` (see the Gold trading section below). It serves equity strategy artifacts, scheduler events, timing, audit records, and wheel status, and holds no broker credentials of its own.

Run locally:

```bash
/usr/local/bin/python3 dashboard/server.py
pnpm --dir dashboard dev -- --host 127.0.0.1
```

The dashboard refreshes artifacts periodically. Maintain it as an observability surface; do not add further one-click order execution controls beyond the existing btctrend, wheel, and goldtrading approval gates without explicit confirmation and strong confirmation safeguards.

## Wheel strategy

`wheeltrading/` is independent from `newstrading/` and automates IBKR wheel orders for GOOGL and VOO (paper or live per [Broker mode](#broker-mode)):

- With fewer than 100 active wheel shares, it screens cash-secured puts.
- With at least 100 active wheel shares, it screens covered calls.
- It targets 21-45 DTE, approximately 5% out-of-the-money strikes (3% for low-volatility VOO), 0.15-0.30 absolute delta, one contract, and an 8% minimum annualized premium yield.
- It holds at most 2 contracts (200 shares) per symbol and caps total open cash-secured put collateral at 30% of net liquidation across all wheel symbols.
- Orders are only submitted during regular US trading hours (Mon-Fri 9:30am-4:00pm ET; exchange holidays are not modelled). Outside that window recommendations are still recorded but execution is `SKIPPED`.
- It caps a cash-secured put's collateral at 10% of net liquidation.

The wheel scheduler scans every 30 minutes during regular US trading hours only (Mon-Fri 9:30am-3:30pm ET slots, defined in `wheeltrading/schedule.py`). `wheeltrading/run_wheel.py` is the manual, recommendation-only CLI (never submits orders); it honors the same broker-mode gate as the scheduler. No option order reaches IBKR automatically: an actionable recommendation is queued per symbol as a pending approval (`wheeltrading/approval.py`, `wheeltrading/data/pending_approvals.json`) that a human must approve or reject from the dashboard's wheel panel; `approve_pending` re-quotes the option first and refuses to approve if the bid moved more than its tolerance, and either way clears the pending record. An unapproved pending order expires after `APPROVAL_WINDOW_MINUTES` (30) and the next cycle re-evaluates fresh. Once approved, the quote/delta, duplicate-short-position, contract-qualification, bid, and cash-collateral checks still run before the order is placed. If option data is unavailable, it records `data_unavailable` and submits no order. Do not enable live option execution without explicit approval and an approval-gated design (the approval gate above satisfies this). The dashboard's wheel panel can approve or reject a pending order (`POST /api/wheel-approve/<symbol>` / `-reject/<symbol>`); it is otherwise read-only. Only lots explicitly registered as wheel put assignments are eligible to cover wheel calls; GOOGL or VOO shares owned by the equity-signal strategy or externally are displayed as `external` and must never trigger a wheel covered call. A registered assigned-put lot moves into `wheeltrading/data/wheel_state.json`'s `stock_pool` when its market price is at least 10% below the assignment strike. Pooled shares retain their assigned strike as average cost, are excluded from covered-call eligibility, and allow the active wheel to return to screening new cash-secured puts.

## Gold trading

`goldtrading/` is independent from `newstrading/` and `wheeltrading/`. It trades Micro Gold futures (MGC, COMEX) against IBKR's US Spot Gold product (`XAUUSD`, tradable from 1 oz) and, separately, MGC calendar spreads, only when the market price diverges from a computed carry-cost fair value by more than transaction costs plus a minimum edge:

- Fair value: `spot * (1 + (financing rate + storage rate - convenience yield) * years to expiry)`. The financing and storage rates are static, manually-maintained assumptions (not a live feed) — see `goldtrading/STRATEGY.md` for the current values and the rationale.
- Cash-and-carry only trades the long-spot/short-futures direction; the reverse would require shorting physical gold, which isn't supported for a retail account, so that direction is always a `HOLD`.
- Calendar spreads trade the front vs. next active MGC month via a native combo order when possible, with a documented fallback and unwind path if one leg fails to fill after the other has.
- Each trade requires a net edge (after estimated round-trip costs) of at least 0.15% of spot notional, caps notional/margin exposure at 20% of net liquidation, and allows only one open carry/spread position at a time.
- Positions exit on a 70%-of-edge profit target, a 2x-of-edge stop-loss, or before a held near-month contract reaches its last trading day (MGC is physically settled).

The gold scheduler runs every 30 minutes; `goldtrading/run_gold.py` is a manual, read-only CLI that never submits orders and honors the same broker-mode gate as the scheduler (see [Broker mode](#broker-mode)). In paper mode new entries submit directly; in live mode a non-`HOLD` cash-and-carry or calendar-spread entry is instead queued as a pending approval (`goldtrading/approval.py`, `goldtrading/data/pending_approval.json`) that a human must approve or reject from the dashboard (`POST /api/goldtrading-approve` / `-reject`) before anything reaches IBKR; while an entry is pending, new entries are skipped. Do not change this live-mode approval gate without explicit approval. Gold status is read-only in the dashboard. See `goldtrading/STRATEGY.md` for the full strategy contract, worked examples, and risk-gate ordering.

## Bull call spread (MS)

`bullcallspread/` is independent from `newstrading/`, `wheeltrading/`, and `goldtrading/`, and is built as two Claude-API-backed agents:

1. **MS stock analyst agent** (`bullcallspread/analyst_agent.py`) — given the user's own net-income forecast for the upcoming quarter (`bullcallspread/my_earnings_view.json`, copied from `my_earnings_view.example.json`) plus researched Street consensus from two independent sources (`bullcallspread/consensus.py`: yfinance for consensus EPS/revenue range, historical earnings-day surprise pattern, and analyst price targets; Nasdaq's public analyst-forecast API as a best-effort corroborating EPS consensus, never blocking the pipeline if unavailable), predicts MS's stock price on the earnings release day and explains its reasoning, including whether the two sources agree or diverge. Requires `ANTHROPIC_API_KEY` in the environment.
2. **Bull call spread trading agent** (`bullcallspread/trading_agent.py`) — takes the analyst's predicted price as the target and selects the real structure via the same deterministic, live-quote-based logic as before (`strategy.evaluate_bull_call_spread`, so numbers are never invented by the LLM), then explains why that structure is the best way to profit from the predicted move and what the main risk is.

`bullcallspread/scheduler.py` runs every 30 minutes, Mon-Fri during US options trading hours only (`bullcallspread/schedule.py`): if `my_earnings_view.json` exists it runs the full agentic pipeline (caching the analyst agent's prediction by a hash of the earnings-view file, so the LLM only re-runs when the user updates their forecast — the trading agent still re-runs every cycle against fresh quotes); otherwise it falls back to the static `BullCallSpreadConfig.target_price`/`target_date`/`default_amount_usd` (currently $202 by 2026-10-16 with $6,000). The scheduler never places an order itself. `bullcallspread/run_earnings_strategy.py` is the manual CLI for the agentic pipeline; `bullcallspread/run_bullcallspread.py` remains the manual CLI for the static-target path. Both take `--confirm` as the only way to place an order.

- Expiration search is restricted to the quarterly cycle months (Jan/Apr/Jul/Oct); the tool picks the nearest quarterly expiration at or after the target date.
- The long call strike is the strike closest to (but not above) spot; the short call strike is at/above the target price, chosen to maximize return-on-debit among strikes with a tradable (non-stale) quote within a configured width band.
- Sizing: `contracts = floor(amount / (net_debit * 100 + round_trip_cost_per_contract))`, capped at `max_notional_pct_of_excess_liquidity` (100%) of excess liquidity (IBKR's `ExcessLiquidity`, converted to USD regardless of the account's base currency).
- The recommendation includes max profit/loss, breakeven, and a payoff ladder, plus a suggested exit plan (a premium-based stop at a percentage of entry debit, and a time-based exit days before expiry) — this is advisory text only, never auto-executed.
- Once a position is open (`--confirm`), `bullcallspread/monitor.py` runs every scheduler cycle, marks the open spread to its current bid/ask, records an unrealized-P&L history point, and flags (but never acts on) a reached suggested-exit condition.
- Without `--confirm` the tool only prints a recommendation and writes a JSON artifact; with `--confirm` it re-qualifies contracts, re-runs cash/margin/duplicate-position gates, and submits a two-leg combo order to IBKR (paper port 7497, or live port 7496 per [Broker mode](#broker-mode)). Do not enable live execution or auto-exit (closing a position automatically) without explicit approval. See `bullcallspread/STRATEGY.md` for the full contract.

## Bitcoin trend following

`btctrend/` is independent from the other strategies. It trades spot BTC through IBKR Paxos (`Crypto("BTC", "PAXOS", "USD")`), long-only, on paper port `7497` or live port `7496` per [Broker mode](#broker-mode):

- Signal (`btctrend/signals.py`, shared by the backtest and the live trader): nine 0/1 votes on completed yfinance `BTC-USD` daily bars — close vs SMA 50/100/150, SMA 20/100 and 50/200 crosses, 60/120-day momentum, Donchian 55/20 and 100/50. Target exposure = vote fraction x `min(1, 60% / 30-day realized vol)`.
- Sizing: a fully-long position is 10% of excess liquidity (IBKR's `ExcessLiquidity`: buying power left after margin requirements, not net liquidation, so the sleeve shrinks when margin is already committed elsewhere); buys keep a 5% net-liq cash reserve. The target only changes when it moves more than 20 points (a move to zero always executes), and orders are marketable IOC limits that retry next cycle if unfilled.
- Ownership: `btctrend/data/btctrend_state.json` tracks strategy-bought BTC, average cost and realized P&L from fills. BTC held in the account for any other reason must never be sold by strategy code.
- Exits: signal exits (target falls), plus a trailing stop at the peak close since entry minus 4x 14-day ATR, checked against the live bid every cycle. A stop-out locks re-entry until a close above the prior 20-day high. Profit trim: once a daily close is +50% over the trade's entry close, exposure is trimmed by a third, once per trade. Tighter stops, stop-tightening after gains, and equity-drawdown breakers were backtested and rejected (see `btctrend/STRATEGY.md`).
- Position tracking: each executed cycle reconciles IBKR executions from strategy client ids 49/50 into the state file by execId (commissions included), so late fills are never re-bought. State writes are atomic.
- Data: if yfinance lags the latest completed daily bar, it is filled from Coinbase public candles. If the bar is still older than 1 day, increases are blocked and exits still run.
- Pricing: IBKR BTC quote, falling back to the public Coinbase BTC-USD top of book when IBKR has none. Limit prices are rounded to the $0.25 tick. The paper account needs the Cryptocurrency trading permission (otherwise IBKR error 201).
- `btctrend/scheduler.py` runs every 5 minutes (`btctrend.config.RUN_INTERVAL_MINUTES`), 24/7, with `EXECUTE = True`. No BUY/SELL order reaches IBKR automatically: a non-HOLD recommendation is queued as a pending approval (`btctrend/approval.py`, `btctrend/data/pending_approval.json`) that a human must approve or reject before anything is submitted; an unapproved pending order expires after `APPROVAL_WINDOW_MINUTES` (30) and the next cycle re-evaluates fresh rather than filling at a stale price. Risk-state tracking (trailing-stop peak, re-entry lock, profit-trim flag) still updates every cycle regardless of pending approvals. `btctrend/run_btctrend.py` is the manual CLI and only submits with `--confirm`, subject to the same approval gate. `python -m btctrend.backtest` regenerates `btctrend/data/backtest_report.json` (in-sample to 2020, out-of-sample 2021+). Do not enable live execution without explicit approval. The dashboard's BTC panel is the normal way to approve or reject a pending order (`POST /api/btctrend-approve` / `-reject`); it is otherwise read-only. See `btctrend/STRATEGY.md`.

## Development checks

Use the configured interpreter for Python commands:

```bash
/usr/local/bin/python3 -m compileall -q newstrading goldtrading bullcallspread btctrend wheeltrading dashboard/server.py
pnpm --dir dashboard build
git diff --check
```

Keep JSON artifacts and existing execution reports intact. Avoid broad formatting or unrelated refactors. See `newstrading/STRATEGY.md` for the strategy contract and `newstrading/BACKTEST_RESEARCH.md` for research constraints.