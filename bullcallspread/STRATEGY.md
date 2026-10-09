# MS bull call spread research/execution tool

`bullcallspread/` is an independent, IBKR paper-only tool built as two
Claude-API-backed agents: an **MS stock analyst agent** that predicts the
earnings-day stock price from your own earnings forecast, and a **bull call
spread trading agent** that selects and explains the best spread structure
for that prediction. It only places an order when you pass `--confirm`.

## The two agents

1. **MS stock analyst agent** (`bullcallspread/analyst_agent.py`). Input: your
   own net-income forecast for the upcoming quarter, in
   `bullcallspread/my_earnings_view.json` (copy
   `my_earnings_view.example.json` and fill in `quarter`,
   `predicted_net_income_usd_billion`, `confidence_pct` (0-100, default 100
   if omitted), and optional `notes`). **The stated `confidence_pct` is
   trusted as given, not second-guessed.** At or above the 95% threshold
   (`HIGH_CONFIDENCE_THRESHOLD_PCT` in `analyst_agent.py`), the agent treats
   your net-income figure as a known fact and lets the resulting beat/miss
   drive its price prediction at face value, rather than hedging the move
   because it doubts a single estimate. Below that threshold, it treats your
   forecast as one plausible scenario and hedges accordingly. Either way, the
   agent's own `confidence` output reflects uncertainty in the *market's
   reaction* to the beat (mix/guidance/macro noise) — never doubt in the
   number you supplied. The agent also
   researches Street consensus via `bullcallspread/consensus.py` from two
   independent sources:
   - **yfinance**: consensus EPS/revenue range, the last 8 quarters' EPS
     estimate/actual/surprise%, and analyst price targets.
   - **Nasdaq's public analyst-forecast API**
     (`api.nasdaq.com/api/analyst/<symbol>/earnings-forecast`, the same data
     backing https://www.nasdaq.com/market-activity/stocks/ms/earnings) —
     consensus/high/low EPS for the nearest upcoming fiscal quarter, number
     of estimates, and recent upward/downward revisions. This is a
     best-effort, unauthenticated public endpoint, not a licensed feed; any
     failure (network, shape change, empty data) returns `None` and is
     reported in the prompt as "unavailable for this run" — it never blocks
     the pipeline, since yfinance alone is still a usable consensus snapshot.

   and computes your implied EPS and implied surprise % vs. (yfinance)
   consensus from your net-income figure and shares outstanding. It calls
   Claude (`claude-opus-5-5`) to predict MS's price on the earnings release
   day — a price, a range, a confidence level, and a reasoning list
   explaining the call, grounded in the historical beat/miss pattern, analyst
   targets, and whether the two consensus sources agree or diverge. This
   agent never trades; its only output is a price prediction.
2. **Bull call spread trading agent** (`bullcallspread/trading_agent.py`).
   Takes the analyst's predicted price as `target_price` and the earnings
   date as `target_date`, and runs the **same deterministic strike-selection
   and payoff math described below** against live IBKR quotes — the LLM
   never invents strikes, prices, or sizing. It then calls Claude with the
   resulting real structure (strikes, debit, max profit/loss, breakeven) and
   asks it to explain, like a trader briefing a client, why that structure
   is the best way to express the predicted move, what alternative
   structures were implicitly rejected (a single long call, a narrower/wider
   spread) and why, and the single biggest risk to the thesis.

Both agents require `ANTHROPIC_API_KEY` in the environment (same pattern as
`SEC_USER_AGENT` for newstrading's SEC EDGAR feed). A missing key or any
Claude API failure degrades to `status: "data_unavailable"`, the same way an
IBKR market-data failure does — it never falls back to a guessed price.

## Instrument and expiration cycle

- Underlying: MS equity call options only (`bullcallspread/config.py`).
- Expiration search is restricted to the **quarterly cycle months**
  (January, April, July, October). Given a target date, the tool picks the
  nearest quarterly expiration at or after that date, within a
  `min_days_to_expiry`/`max_days_to_expiry` window (default 14-120 days).

## Strike selection

- **Long call**: the strike closest to (but not above) the current spot
  price.
- **Short call**: a strike at or above your target price, within a width
  band of `min_width_pct`-`max_width_pct` of spot above the long strike. If
  no strike at/above the target price falls inside that band, the tool falls
  back to the widest strike inside the band so a priceable spread is still
  returned (and says so in `reasons`).
- Among short-strike candidates, the tool picks the pair with the highest
  return-on-debit (`max_profit / net_debit`).

## Sizing

```
net_debit = long_call_ask - short_call_bid
cost_per_contract = net_debit * 100 + round_trip_cost_per_contract
contracts = floor(amount / cost_per_contract)
```

The requested notional (`net_debit * 100 * contracts`) is also capped at
`max_notional_pct_of_excess_liquidity` (default 100%) of excess liquidity
(IBKR's `ExcessLiquidity`: buying power left after margin requirements,
converted to USD regardless of the account's base currency); exceeding
either bound returns `HOLD`.

## Payoff structure

```
max_profit = (short_strike - long_strike - net_debit) * 100 * contracts
max_loss   = net_debit * 100 * contracts
breakeven  = long_strike + net_debit
```

The recommendation includes a payoff ladder (P&L at spot -10%/-5%/current,
both strikes, your target price, and target +5%).

## Suggested exit plan (printed only, not enforced)

Since a vertical spread's max loss is already capped at the entry debit,
there is no single stock stop-loss price. The tool instead suggests:

- **Premium-based stop**: close the spread if its market value falls to
  `stop_loss_pct_of_debit` (default 50%) of the entry net debit.
- **Time-based exit**: close by `exit_days_before_expiry` (default 7) days
  before expiry regardless of P&L, to avoid late-cycle theta decay and
  assignment risk on the short leg.

This is advisory text only — `bullcallspread/monitor.py` checks whether a
suggested-exit condition has been reached and records it alongside each
unrealized-P&L point, but never closes a position automatically.

## Scheduler and defaults

`bullcallspread/scheduler.py` runs every 30 minutes, Mon-Fri during US
options trading hours only (`bullcallspread/schedule.py`, matching
`wheeltrading`'s pattern). Each cycle it refreshes unrealized P&L for any
open position (`monitor.py`), then:

- If `bullcallspread/my_earnings_view.json` exists, it runs the full agentic
  pipeline. The analyst agent's prediction is **cached** by a SHA-256 hash of
  the earnings-view file's contents
  (`bullcallspread/data/analyst_prediction_cache.json`) — it only re-runs
  the (costed) LLM call when you edit your forecast, not every 30 minutes.
  The trading agent still re-runs every cycle, since live quotes (and so the
  best structure/payoff) can shift intraday even with a fixed target price.
- Otherwise it falls back to the static defaults in `BullCallSpreadConfig`
  (`target_price`, `target_date`, `default_amount_usd` — currently $202 by
  2026-10-16 with $6,000), unchanged from before the agentic redesign.

The scheduler **never places an order**; it is research- and
monitoring-only. Runs are written to `bullcallspread/data/automated_runs/`.

## CLI

```bash
# Agentic pipeline (uses my_earnings_view.json)
/usr/local/bin/python3 -m bullcallspread.run_earnings_strategy

# Static-target pipeline (no earnings view needed)
/usr/local/bin/python3 -m bullcallspread.run_bullcallspread
# or override the defaults:
/usr/local/bin/python3 -m bullcallspread.run_bullcallspread \
  --target-price 110 --target-date 2027-01-15 --amount 2000
```

Without `--confirm`, either tool only fetches live IBKR paper quotes, prints
the recommendation (plus, for `run_earnings_strategy.py`, both agents'
reasoning), payoff ladder, and exit plan, and writes a JSON artifact to
`bullcallspread/data/recommendations/`. With `--confirm`, it re-qualifies
the contracts, re-runs cash/margin/duplicate-position gates
(`bullcallspread/execution.py`), and submits a two-leg `BAG` combo limit
order to IBKR paper trading (port 7497), recording the open position in
`bullcallspread/data/bullcallspread_state.json` and writing an execution
report to `bullcallspread/data/execution_reports/`.

Running `bullcallspread/scheduler.py` is the only way to get recommendations
on a cadence; placing an order from them is always a separate, manual
`--confirm` step on one of the two CLIs above.

## Limitations

- Research and monitoring are scheduled; execution and position exit are not
  — both remain explicit, manual actions. Enabling either would require an
  explicit, separately-approved design.
- The analyst agent's prediction is only as good as the net-income figure
  you provide and the LLM's reasoning over it — it is not a second,
  independent forecasting model, and it is never used to invent option
  prices or strikes (those always come from live IBKR quotes).
- Paper trading only (`PAPER_PORT = 7497` hardcoded); enabling live
  execution would require an explicit, separately-approved design.
- Single symbol (MS) hardcoded in `config.py`.
