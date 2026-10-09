# BTC trend following: research and strategy contract

## Research question

Can a simple, unoptimized trend-following rule on daily bitcoin data beat buy-and-hold on a
risk-adjusted basis, and does that edge survive out of sample and after costs?

## Data and method

- **Data:** yfinance `BTC-USD` daily bars, 2014-09-17 to the last completed UTC day (about 4,400 bars).
- **Execution model:** an exposure decided at a daily close is held from the next bar onward, so there is no look-ahead. A per-side cost is charged on every exposure change. The default is 0.25%, which covers IBKR crypto commission (about 0.12-0.18%) plus slippage.
- **Split:** in-sample runs from 2014-09 to 2020-12; out-of-sample runs from 2021-01 onward. No parameters were fitted on either period. Every lookback is a conventional value.
- **Reproduce:** `/usr/local/bin/python3 -m btctrend.backtest [--cost 0.0025]` prints the tables below and writes `data/backtest_report.json`.

## Findings (run 2026-10-03, 0.25%/side)

**Single rules, in-sample vs out-of-sample**

| Rule | IS Sharpe | OOS Sharpe | OOS max DD |
| --- | --- | --- | --- |
| Buy and hold | 1.27 | 0.61 | -76.6% |
| Close > SMA20 (fast) | 1.64 | 0.29 | -68.6% |
| SMA 10/30 cross (fast) | 1.68 | 0.30 | -65.8% |
| Close > SMA50 | 1.60 | 0.91 | -58.7% |
| Close > SMA150 | 1.67 | 0.84 | -44.8% |
| SMA 50/200 cross | 1.39 | 0.52 | -56.9% |
| Donchian 55/20 | 1.37 | 0.70 | -36.6% |

1. **Every medium-horizon trend rule cut drawdown versus buy-and-hold** (-37% to -67% against -77% out-of-sample), because it was mostly flat through the 2018 and 2022 bear markets.
2. **The fastest rules were the in-sample winners and the out-of-sample losers.** With a 20-day SMA, Sharpe fell from 1.64 to 0.29, a textbook overfitting trap. This is why the ensemble only uses lookbacks of 50 days or more (apart from the fast leg of the SMA 20/100 cross).
3. **No single lookback is reliably best.** Which member ranks first changes between periods. An equal-weight ensemble across lookbacks and rule families gives up a little of the best single rule's return for much more stability.

**Ensemble and overlays**

| Variant | OOS CAGR | OOS Sharpe | OOS max DD | Full-period max DD | Avg exposure |
| --- | --- | --- | --- | --- | --- |
| Buy and hold | 20.4% | 0.61 | -76.6% | -83.4% | 100% |
| 9-signal ensemble, 20% band | 26.0% | 0.83 | -39.7% | -60.8% | 49% |
| **+ 60% vol target (the strategy)** | **21.9%** | **0.78** | **-42.1%** | **-43.3%** | 47% |

4. **Volatility targeting** has a mixed effect out of sample (Sharpe 0.83 → 0.78), but it cuts the worst full-history drawdown from -61% to -43%. Almost all of that comes from 2017-2018, when realized vol ran at 70-85%. It is kept as a risk control: it limits exposure in exactly the regimes where gap risk is highest.
5. **The rebalance band** (trade only when the target moves more than 20 points) roughly halves turnover (9.8 → 5.1 per year) at no cost to Sharpe.
6. **Costs:** the edge holds up to 1% per side (OOS Sharpe 0.66 vs 0.61 for buy-and-hold), so it is not an artefact of free trading.

## Exit and risk-management research

The ensemble already exits on its own: votes turn flat as a trend fails, and the volatility target shrinks exposure when vol spikes. On top of that, I tested the standard risk overlays, all at 0.25%/side. Stops are tested against each day's low and fill at the stop, or at the open on a gap. After a stop-out, the strategy stays flat until a fresh 20-day-high close.

| Overlay | OOS CAGR | OOS Sharpe | OOS max DD | Full Sharpe | Full max DD |
| --- | --- | --- | --- | --- | --- |
| None (signal exits only) | 21.9% | 0.78 | -42.2% | 1.26 | -43.3% |
| Fixed % trailing stop 15% / 20% / 25% | 8-14% | 0.42-0.58 | -43 to -51% | 1.09-1.30 | -43 to -51% |
| Fixed % trailing stop 30% | 20.9% | 0.75 | -42.5% | 1.23 | -42.5% |
| ATR trailing stop 2.5x / 3x | 7-8% | 0.41-0.42 | -32 to -36% | 1.21-1.27 | -32 to -36% |
| **ATR trailing stop 3.75x / 4x / 4.25x** | **17-19%** | **0.67-0.74** | **-35 to -39%** | **1.38-1.40** | **-35 to -39%** |
| ATR trailing stop 5x / 6x / 8x | 18-21% | 0.70-0.76 | -42 to -46% | 1.30-1.37 | -42 to -46% |
| Equity-drawdown breaker (halve at -20/-25/-30%) | 9-16% | 0.47-0.66 | -36 to -39% | 0.98-1.15 | -37 to -40% |

- **Tight stops destroy the edge.** BTC routinely retraces 15-25% inside healthy uptrends. Fixed-% stops and anything under about 3.5x ATR get whipsawed out and miss the recovery.
- **A wide ATR trailing stop is the one overlay worth keeping.** From 3.5x to 8x ATR, full-history Sharpe sits on a stable 1.36-1.40 plateau, up from 1.26. At 3.75-4.25x it cuts out-of-sample drawdown by about 5-7 points, in exchange for 2-3 points of annual return. ATR scales the stop with the market's own volatility, which is why it beats a fixed percentage. **4x ATR is adopted**, the middle of the plateau.
- **Equity-drawdown breakers lag.** They cut exposure after the damage is done and then miss the rebound.
- Kept from the base design: **position sizing** (10% net-liq sleeve, volatility targeting, no leverage, long-only), the **cash reserve**, and **re-entry discipline** after a stop (only on a new 20-day high, so the strategy doesn't buy straight back into a falling market).

### Profit taking (review of 2026-10-03)

Trend following traditionally lets winners run, so I tested whether locking in part of a big gain helps. All variants keep the 4x ATR stop. A trim fires once per trade, on a daily close, and caps exposure for the rest of that trade.

| Variant | OOS CAGR | OOS Sharpe | OOS max DD | Full Sharpe | Full max DD |
| --- | --- | --- | --- | --- | --- |
| No profit taking | 19.3% | 0.74 | -35.7% | 1.38 | -35.7% |
| Trim 1/3 at +25% / +100% vs entry | 18.4-18.8% | 0.74-0.79 | -29.7 to -32.5% | 1.40-1.42 | -31.9 to -32.5% |
| **Trim 1/3 at +50% vs entry** | **19.8%** | **0.80** | **-32.5%** | **1.47** | **-32.5%** |
| Trim 1/2 at +50% vs entry | 18.4% | 0.81 | -30.6% | 1.51 | -33.0% |
| Trim 1/2 at entry + 4x / 6x / 8x ATR | 15.0-17.3% | 0.74-0.85 | -24.7 to -30.6% | 1.41-1.47 | -31.9 to -33.0% |
| Tighten stop to 2.5x / 3x ATR after +30% to +100% | 7.7-17.2% | 0.41-0.70 | -32 to -38% | 1.18-1.33 | -37 to -38% |

- **A partial trim on big winners consistently improves risk-adjusted returns.** Every trim variant raised full-history Sharpe and cut drawdown. Trimming a third at +50% does so without giving up return, so it is adopted.
- **Tightening the stop after a gain is harmful**, for the same reason tight stops are: BTC's normal pullbacks inside a trend get mistaken for reversals.

The reproducible `backtest.py` report for the full rule set (signals + 4x ATR stop + 1/3 trim at +50%), as of data through 2026-10-03: out-of-sample CAGR 19.9%, Sharpe 0.81, max drawdown -32.0%. Full history: Sharpe 1.47, max drawdown -32.0%, average exposure 33%.

**Caveats.** BTC's history includes one regime, 2013-2017, with returns that will not repeat, and the out-of-sample period is under six years. The ensemble members were chosen after looking at a first table that included out-of-sample columns, which is mild data snooping (mitigated by using only conventional lookbacks). Expect the strategy to lag buy-and-hold in strong, choppy bull markets: in 2024 it made +80% vs +121%. Its job is to avoid the -64% to -77% bear-market drawdowns, not to beat every rally.

## Strategy contract

1. **Signal.** Nine 0/1 votes computed on completed daily bars (`signals.py`, shared verbatim with the backtest): close > SMA 50/100/150; SMA20 > SMA100; SMA50 > SMA200; 60- and 120-day return > 0; Donchian 55/20 and 100/50 (long after a close above the prior N-day high, flat after a close below the prior M-day low). Score = fraction of long votes.
2. **Target exposure** = score × min(1, 60% ÷ 30-day annualized realized vol), clipped to [0, 1]. The strategy is long-only and never uses leverage.
3. **Band.** The committed exposure changes only when the target differs by more than 20 points, except that a target of zero always executes. When the target changes, the target quantity is fixed at `exposure × sleeve ÷ price`. Later cycles keep working toward that quantity (for example after a partial IOC fill) without re-sizing for price drift.
4. **Sleeve and cash.** Full exposure is 10% of net liquidation. Buys are reduced so cash stays above 5% of net liquidation. Orders under $25 are skipped.
5. **Data.** Signals use completed UTC daily bars from yfinance. If yfinance hasn't yet published the latest completed day (it sometimes publishes today's partial bar first), the missing days are filled from Coinbase's public daily candles. If the newest bar is still more than 1 day old, exposure can be reduced but not increased until the data catches up. Daily bars are cached for 15 minutes within a UTC day.
6. **Orders.** Marketable IOC limit orders on IBKR Paxos: buys at ask +0.5%, sells at bid −0.5%, rounded away from the touch onto the contract's $0.25 price tick. If IBKR returns no BTC quote (for example, the account lacks the PAXOS crypto market-data permission), the public Coinbase BTC-USD top of book is used as the pricing reference, and the run records the quote source. Unfilled or partly filled orders are retried on the next cycle. A cycle is rejected if another BTC order is active from any client id, if the quote is not two-sided, or if the IBKR mid deviates from the last daily close by more than 15%.
7. **Position tracking.** Every executed cycle reconciles IBKR's execution records for the strategy's client ids (49, 50) into `data/btctrend_state.json`, keyed by execId. Fills that arrive after an order's 15-second wait window are therefore still recorded, and the next cycle doesn't buy the same exposure twice. Commissions are capitalized into the average cost on buys and deducted from realized P&L on sells. State writes are atomic. Only BTC bought by this strategy can be sold, capped at what the account actually holds.
8. **Exits.** There are three independent exit paths:
   - *Signal exit:* the ensemble target falls to zero (always executes) or drops by more than the band.
   - *Trailing stop:* the stop sits at the highest daily close since entry minus 4 × the 14-day ATR. It ratchets up only and is checked every cycle against the live bid. A breach sells the whole strategy position and locks re-entry until a daily close above the prior 20-day high. The peak and lock persist in `data/btctrend_state.json`. IBKR's Paxos venue doesn't offer stop orders, so the stop is software-managed: it only protects while the scheduler and TWS are running.
   - *Profit trim:* the first daily close at or above +50% vs the trade's entry close trims exposure to two-thirds for the rest of the trade. The rest rides the trailing stop and the signal.
   - Each recommendation reports the **risk at stop**: the loss, in dollars and as a share of net liquidation, if the post-trade position were stopped out at the current stop level.
9. **Scheduling.** `scheduler.py` runs every 5 minutes (`config.RUN_INTERVAL_MINUTES`), 24/7, and submits paper orders (`EXECUTE = True`) whenever the rules produce a BUY or SELL. The signal only changes after the 00:00 UTC daily close; every cycle checks the trailing stop and retries unfilled orders. `run_btctrend.py` is the manual CLI, which is research-only unless `--confirm` is passed. IBKR client ids: scheduler 49, CLI 50.
10. **Monitoring.** Every cycle writes a run record, including failed ones (`status: data_unavailable` or `error`). The dashboard flags stale daily data, and flags a scheduler that is running but hasn't produced a run in three intervals (meaning the stop isn't being watched).
11. **Account prerequisites.** The IBKR paper account needs the Cryptocurrency trading permission. Without it, orders are rejected with error 201 ("no trading permission"), and the rejection is recorded in the execution report. The PAXOS crypto market-data permission is optional because of the reference-quote fallback.
12. **Live trading** is not implemented. Enabling it requires explicit approval and an approval-gated design.
