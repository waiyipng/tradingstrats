"""Bull call spread trading agent: takes the analyst agent's predicted price as
the target, selects the real structure via the existing deterministic
quant logic (never invents strikes/prices itself), and explains why that
structure is the best way to express the predicted move."""
from __future__ import annotations

from bullcallspread.config import BullCallSpreadConfig
from bullcallspread.llm_client import call_agent_json
from bullcallspread.models import AccountState, AnalystPrediction, CallLeg, TradingAgentReport
from bullcallspread.strategy import evaluate_bull_call_spread

SYSTEM_PROMPT = """You are an options trading agent specializing in bull call spreads. You have
already been given a specific, fully-priced bull call spread structure (real strikes, real bid/ask,
real payoff math) that a deterministic strategy engine selected to best express a given price target.
Your job is NOT to pick different numbers - the structure is fixed. Your job is to explain, like a
trader briefing a client, why this structure is the best way to profit from the predicted move: how
it captures the predicted move, why the strike width and sizing are sensible given the move's
magnitude and the trader's confidence, what alternative structures were implicitly rejected and why
(e.g. a single long call, a narrower or wider spread), and the single biggest risk to the thesis.
Respond with ONLY a JSON object (no markdown fences, no prose outside the JSON) with exactly these
keys: reasoning (array of 4-8 short strings), alternatives_considered (array of 2-4 short strings,
each naming an alternative structure and why it was not chosen), primary_risk (one string)."""


def _build_user_prompt(analyst_prediction: AnalystPrediction, amount: float, long_leg: CallLeg, short_leg: CallLeg, net_debit: float, contracts: int, max_profit: float, max_loss: float, breakeven: float) -> str:
    return f"""Analyst prediction: {analyst_prediction.symbol} will trade at ${analyst_prediction.predicted_price}
(range ${analyst_prediction.price_range_low}-${analyst_prediction.price_range_high}, confidence {analyst_prediction.confidence})
on the earnings release day {analyst_prediction.earnings_date}.
Analyst reasoning: {"; ".join(analyst_prediction.reasoning)}

Capital allocated: ${amount}

Selected structure (already priced against live quotes - do not change these numbers):
- Long call: strike {long_leg.strike}, ask {long_leg.ask}
- Short call: strike {short_leg.strike}, bid {short_leg.bid}
- Net debit: ${net_debit} per contract, {contracts} contract(s)
- Max profit: ${max_profit}, max loss: ${max_loss}, breakeven: ${breakeven}

Explain why this structure is the best way to profit from the predicted move."""


def run_trading_agent(
    config: BullCallSpreadConfig,
    analyst_prediction: AnalystPrediction,
    account: AccountState,
    spot: float,
    expiry: str,
    legs: list[CallLeg],
    amount: float,
) -> TradingAgentReport:
    recommendation = evaluate_bull_call_spread(
        config, account, spot, expiry, legs,
        analyst_prediction.predicted_price, analyst_prediction.earnings_date, amount,
    )

    if recommendation.action != "BUY_BULL_CALL_SPREAD" or recommendation.long_leg is None or recommendation.short_leg is None:
        return TradingAgentReport(
            recommendation=recommendation,
            reasoning=["No viable structure was found against live quotes; see the recommendation's own reasons."],
            alternatives_considered=[],
            primary_risk="No position - nothing is at risk.",
        )

    user_prompt = _build_user_prompt(
        analyst_prediction, amount, recommendation.long_leg, recommendation.short_leg,
        recommendation.net_debit, recommendation.contracts, recommendation.max_profit,
        recommendation.max_loss, recommendation.breakeven,
    )
    result = call_agent_json(SYSTEM_PROMPT, user_prompt)
    return TradingAgentReport(
        recommendation=recommendation,
        reasoning=list(result["reasoning"]),
        alternatives_considered=list(result["alternatives_considered"]),
        primary_risk=result["primary_risk"],
    )
