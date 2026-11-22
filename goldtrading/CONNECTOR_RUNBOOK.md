# Running the gold strategy via the IBKR Connector (agent-driven)

This is the procedure an agent (not a script — see `STRATEGY.md`'s "Running
via the IBKR Connector" section for why) follows when the user asks to run or
evaluate the gold strategy using their connected IBKR Connector (MCP tools
named `mcp__Interactive_Brokers_IBKR__*`), rather than the TWS-based
`goldtrading/scheduler.py` / `run_gold.py` path. Every conversion step below
is implemented and unit-tested in `goldtrading/connector_adapter.py`.

1. **Check the flow type once per session**: call `get_flow_type`. If it ever
   reports `AUTONOMOUS` instead of `REVIEW_AND_APPROVE`, stop before step 7 —
   `AUTONOMOUS` live-order tools don't support `FUT` at all, so no instruction
   can be created either way; evaluation (steps 2-6) can still proceed.

2. **Account state**: call `get_account_summary` and `get_account_balances`,
   then `goldtrading.connector_adapter.account_state_from_connector(account_summary, account_balances)`.
   If no USD row exists in `account_balances`, the result falls back to the
   account's base-currency cash/net-liquidation figures unconverted — say so
   plainly when reporting the recommendation, since `GoldConfig`'s thresholds
   are USD-denominated.

3. **Resolve the futures contract**: call `search_contracts(config.futures_symbol)`
   (default `"MGC"`), then `goldtrading.connector_adapter.select_mgc_future_contract(results, config)`.
   This guards against the exchange/symbol collision confirmed live this
   session (searching "MGC" also returns an unrelated ARCA ETF) — never pick
   a row by symbol match alone.

4. **Futures term structure**: call `search_futures(underlying_contract_id)`
   from step 3's result, then
   `goldtrading.connector_adapter.select_near_far_contracts(contracts, config)`.

5. **Quotes**: call `get_price_snapshot` for the near and far futures
   (passing their native `exchange`, e.g. `"COMEX"` — omitting it returns no
   data for futures) and convert with
   `futures_quote_from_connector(contract_row, snapshot)`. For the spot leg,
   call `search_contracts(config.spot_symbol)` (default `"XAUUSD"`) to get its
   CMDTY row (confirmed live: exchange `"IBCMDTY"`), then `get_price_snapshot`
   and `spot_quote_from_connector(snapshot, config.spot_symbol)` — treat this
   as best-effort: a live test this session returned an empty snapshot for
   spot gold (inconclusive whether that's a data-entitlement gap or just no
   quote at that moment), and the adapter already degrades a missing quote
   into a clean `HOLD` downstream.

6. **Evaluate**: build a `MarketSnapshot(spot, near_future, far_future)` and
   call the **unmodified** `goldtrading.strategy.evaluate_cash_and_carry` /
   `evaluate_calendar_spread` (same functions the TWS path uses — same
   thresholds, same verdicts). Report both recommendations' `.verdict` to the
   user.

7. **Cash-and-carry is report-only here — never call `create_order_instruction`
   for it.** `create_order_instruction` supports STK, FUT, single-leg
   OPT/FOP, and OPT–OPT combos only; spot gold is CMDTY, which isn't in that
   list. If cash-and-carry is actionable, tell the user and point them at the
   TWS path (paper or live per `CLAUDE.md`'s Broker mode) instead.

8. **Calendar spread may execute, with the user's explicit confirmation each
   time:**
   - Run a coarse sanity gate first: `account_summary.excess_liquidity` (or
     `buying_power`) should comfortably exceed the estimated notional
     (`contracts * futures_multiplier_oz * near_future.mid_price`). This is
     weaker than the TWS path's live `whatIfOrder` margin-impact check — the
     connector exposes no margin-preview tool — so say so, don't present it
     as equivalent.
   - Call `build_calendar_spread_instructions(recommendation, near_contract_id_ex, far_contract_id_ex)`
     (the `contract_id_ex` values come from step 4's `search_futures` rows,
     e.g. `"751494403@COMEX"`) to get the two leg argument sets.
   - Call `create_order_instruction` twice, once per leg. **Always surface
     both returned deep-link URLs to the user** — nothing is live until they
     personally open and submit each one in the IBKR app/site.
   - This is two independent single-leg instructions, not an atomic combo
     (the connector doesn't support FUT–FUT combos via `get_combo_identifier`
     or `create_order_instruction`). Tell the user plainly: if only one leg is
     ultimately submitted and filled, they hold an unhedged outright future,
     not the hedged spread — the same leg-unwind risk already documented for
     TWS's own combo-rejection fallback in `goldtrading/execution.py`.

9. **After the user confirms both legs filled**, call
   `goldtrading.state.record_open_position` (no code change needed — it's
   already a plain function call) with the same `legs`/`entry_mispricing_magnitude`/
   `entry_net_edge` shape `execute_calendar_spread` writes, so the position
   shows up in `goldtrading/data/gold_state.json` and the regular TWS-based
   `run_monitor_cycle` picks it up for profit-take / stop-loss / last-trading-day
   exits later, even though it was opened through the connector.
