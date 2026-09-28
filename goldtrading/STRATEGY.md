# Gold cash-and-carry and calendar-spread strategy

`goldtrading/` is an independent, automated IBKR paper-only strategy. It
runs two related, quantitative gold trades and only acts when a computed
carry-cost fair value is violated by more than transaction costs plus a
safety margin — never on a directional view of gold prices.

## Instruments

- **Futures leg: Micro Gold futures (MGC)**, COMEX. 10 troy oz per contract,
  $0.10/oz tick ($1/tick per contract). Chosen over full-size GC (100 oz,
  roughly 10x the margin) as the retail-appropriate size.
- **Spot leg: US Spot Gold**, IBKR's own retail spot-gold product
  (`secType="CMDTY"`, `symbol="XAUUSD"`, `exchange="SMART"`,
  `currency="USD"`), tradable from as little as 1 troy oz. Not available to
  legal residents of AZ, MT, NH, or RI — the module treats a failed
  qualification as `data_unavailable`, not an error.
- Calendar spreads trade two MGC contract months (front vs. next active
  month with at least `min_days_between_months` days of separation) via a
  native IBKR combo (`BAG`) order when possible.

## Carry-cost model

```
theoretical_futures_price = spot * (1 + (financing_rate + storage_rate - convenience_yield) * years_to_expiry)
basis = market_futures_price - theoretical_futures_price
theoretical_calendar_spread = theoretical_futures_price(far_expiry) - theoretical_futures_price(near_expiry)
```

Worked example: spot = $2,000/oz, financing + storage = 4.8%/yr, 90 days to
expiry -> theoretical futures price ≈ $2,023.67. If the market MGC price is
$2,050, the raw basis is +$26.33. After subtracting an assumed $1.00
round-trip cost (`round_trip_cost_pct` of spot notional), the net edge is
$25.33 — well above the $3.00 minimum edge floor (`min_net_edge_pct` × spot),
so the strategy enters a cash-and-carry trade.

### Assumptions (manually maintained, not live market data)

- `financing_rate_annual` (default 4.5%) is a static proxy for short-term
  financing cost. It is **not** fetched from a live rate feed — review and
  update it periodically against actual short-term rates (e.g. SOFR or
  T-bill yields).
- `storage_rate_annual` (default 0.3%) is an estimated vaulting/insurance
  cost for holding physical/unallocated gold.
- `convenience_yield_annual` (default 0%) — gold pays no dividend or lease
  yield to a retail holder in this design.

Both estimates directly determine the fair-value line the strategy trades
against; treat them as assumptions to revisit, not measured facts.

## Cash-and-carry: direction limitation

Only the **cash-and-carry direction (long spot, short futures)** is
tradable. The reverse (short spot, long futures) would require shorting
physical/unallocated gold, which is impractical for a retail account. When
the carry math favors the reverse direction (the futures price is at or
below fair value), the strategy returns `HOLD` with the reason
`"reverse cash-and-carry (short spot) is not supported"` — it never
attempts it.

## Risk gates (evaluated in order before any order is submitted)

1. **Contract qualification** — spot and futures contracts are re-qualified
   via `reqContractDetails` immediately before order submission; a failure
   rejects the trade rather than raising.
2. **Concurrent-position cap** — at most `max_concurrent_positions` (1)
   carry/spread position open at a time, checked against both
   `gold_state.json` and IBKR's own open orders/positions.
3. **Net-edge-after-costs threshold** — `min_net_edge_pct` (0.15% of spot
   notional) must be cleared after subtracting the estimated round-trip
   cost.
4. **Notional/margin cap** — the spot leg's cash cost and the futures (or
   combo) leg's live IBKR margin impact (via `whatIfOrder`) must each stay
   within `max_notional_pct_of_net_liq` (20%) of net liquidation.
5. **Cash sufficiency** — the spot leg is a full cash purchase (no margin);
   rejected if cash on hand is insufficient.
6. **Valid bid/ask** — every leg must have a live, positive bid/ask before
   a limit price is computed.

Any data-fetch failure (missing quote, contract not found, market closed)
is recorded as `data_unavailable`, not an exception — no order is submitted
and the cycle still writes an artifact.

## Calendar spread execution and its highest-risk step

A calendar spread is submitted as a single `BAG` combo order
(`ComboLeg` per contract month) so both legs fill atomically whenever
possible. If the combo order is rejected outright, the module falls back to
two sequential single-leg orders (near leg first, then far leg). **If the
far leg is then rejected after the near leg has already filled, the module
immediately submits an offsetting closing order for the filled near leg and
records the position as `leg_unwind_required`** rather than leaving a naked
futures position open silently. This asymmetric-fill path is the one place
in the module where execution risk is highest, since the unwind is itself
subject to slippage.

## Sizing

- **Cash-and-carry**: contracts are sized so the spot leg (in exact 10 oz
  multiples per MGC contract, to keep the hedge ratio exact) fits within
  both the notional cap and available cash — no partial-contract hedges.
- **Calendar spread**: fixed at `calendar_contracts_per_trade` (1), since
  spreads carry much lower margin than an outright future; the live
  `whatIfOrder` margin check is the real gate.

## Exit rules (checked every cycle, before new-trade evaluation)

A position is closed (offsetting orders submitted for every leg) when any
of the following holds:

- **Profit take**: the mispricing has shrunk by at least
  `profit_take_pct_of_edge` (70%) of the entry net edge.
- **Stop loss**: the mispricing has grown by at least
  `stop_loss_edge_multiple` (2x) of the entry net edge.
- **Delivery-window guard**: the near-month contract is within
  `last_trading_day_buffer` (3) days of its last trading day. MGC is
  physically settled — the module never holds a near-month contract into
  its notice/delivery window.

## Scheduler

`goldtrading/scheduler.py` runs every 30 minutes (matching `wheeltrading`'s
cadence, since carry mispricings are slow-moving relative to a 15-minute
equity-news cycle): it first runs the exit-condition monitor, then
evaluates and — if a genuine, cost-adjusted opportunity is found — executes
the cash-and-carry trade, then the calendar spread. `goldtrading/run_gold.py`
is a manual, read-only CLI that only produces a recommendation JSON and
never submits an order.

## Limitations

- Static financing/storage-rate assumptions (see above) need periodic
  manual review.
- The margin-impact check for the futures/combo leg relies on IBKR's
  `whatIfOrder` preview at submission time; it is not a substitute for
  checking real-time margin usage directly in TWS.
- US Spot Gold is unavailable in a handful of US states; the module
  degrades to `data_unavailable` there rather than failing loudly.
- Paper trading only. `PAPER_PORT = 7497` is hardcoded with no live-trading
  flag, matching `wheeltrading`'s precedent — enabling live execution would
  require an explicit, separately-approved design.
