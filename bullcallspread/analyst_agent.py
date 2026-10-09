"""MS stock analyst agent: predicts the earnings-day stock price from the
user's own net-income forecast plus researched Street consensus, and explains
its reasoning. Never trades - its only output is a price prediction."""
from __future__ import annotations

from bullcallspread.consensus import ConsensusSnapshot
from bullcallspread.llm_client import call_agent_json
from bullcallspread.models import AnalystPrediction

# Above this, the user's net-income figure is treated as given fact rather
# than a probabilistic estimate to be hedged against.
HIGH_CONFIDENCE_THRESHOLD_PCT = 95

SYSTEM_PROMPT = """You are a senior sell-side equity research analyst covering Morgan Stanley (MS).
You are given the user's own proprietary net-income forecast for the upcoming quarter, a stated
confidence level for that forecast, and researched Street consensus data.

Trust the user's stated confidence level as given - it is not yours to second-guess. If the user
states high confidence (95% or above), treat their net-income figure as a known fact, not an
estimate: compute the implied EPS and the surprise vs. consensus directly from it, and let that
beat/miss magnitude drive your price prediction at face value. Do NOT discount or water down the
predicted move on the grounds that "no single estimate warrants that certainty" - the user has
already told you how certain the input is; your job is to translate a beat/miss of that size into a
price move, not to re-litigate whether the beat will happen. Your own confidence rating should
reflect uncertainty in the market's reaction to a beat of this size (mix/guidance/macro noise), not
doubt about the user's EPS number. If the user states a lower confidence instead, treat the forecast
as one plausible scenario among others and hedge your prediction accordingly.

You are given consensus from two independent sources (yfinance and Nasdaq's public analyst-forecast
API) - note explicitly whether they agree or diverge, since agreement strengthens confidence in the
consensus baseline and divergence is itself a signal worth flagging.
Your job is to predict where MS stock will trade on the earnings release day and explain your
reasoning like an analyst would in a research note: compare the user's implied EPS to consensus,
weigh the historical pattern of beats/misses and how the stock has reacted, and factor in analyst
price targets as a sanity check on the magnitude of the move.
Respond with ONLY a JSON object (no markdown fences, no prose outside the JSON) with exactly these
keys: predicted_price (number), price_range_low (number), price_range_high (number),
confidence ("low"|"medium"|"high"), predicted_eps (number), implied_surprise_pct (number),
consensus_summary (one-paragraph string), reasoning (array of short strings, each one discrete
point in your analysis, 4-8 items)."""


def _build_user_prompt(
    predicted_net_income_usd_billion: float, quarter: str, confidence_pct: float, notes: str,
    consensus: ConsensusSnapshot, predicted_net_revenue_usd_billion: float | None = None,
) -> str:
    implied_eps = None
    if consensus.shares_outstanding:
        implied_eps = round((predicted_net_income_usd_billion * 1_000_000_000) / consensus.shares_outstanding, 2)
    implied_surprise_pct = None
    if implied_eps is not None and consensus.consensus_eps:
        implied_surprise_pct = round(((implied_eps - consensus.consensus_eps) / consensus.consensus_eps) * 100, 1)

    revenue_lines = ""
    if predicted_net_revenue_usd_billion is not None:
        implied_margin_pct = round((predicted_net_income_usd_billion / predicted_net_revenue_usd_billion) * 100, 1)
        revenue_vs_consensus_pct = None
        if consensus.revenue_average:
            revenue_vs_consensus_pct = round(
                ((predicted_net_revenue_usd_billion * 1_000_000_000 - consensus.revenue_average) / consensus.revenue_average) * 100, 1
            )
        revenue_lines = (
            f"\nUser's own net revenue forecast: ${predicted_net_revenue_usd_billion}B "
            f"(implied net margin {implied_margin_pct}%"
            + (f", {revenue_vs_consensus_pct}% vs. consensus revenue" if revenue_vs_consensus_pct is not None else "")
            + "). Use this to sanity-check the net-income forecast: an implied margin far outside MS's "
            "recent historical range is a flag worth noting in your reasoning, even at high stated confidence."
        )

    history_lines = "\n".join(
        f"- {q.report_date}: estimate {q.eps_estimate}, actual {q.eps_actual}, surprise {q.surprise_pct}%"
        for q in consensus.history
    ) or "No recent history available."

    if consensus.nasdaq_forecast:
        nf = consensus.nasdaq_forecast
        nasdaq_lines = (
            f"- Nasdaq consensus EPS (fiscal quarter end {nf.fiscal_quarter_end}): {nf.consensus_eps} "
            f"(range {nf.eps_low} - {nf.eps_high}, {nf.num_estimates} estimates, "
            f"{nf.revisions_up} upward / {nf.revisions_down} downward revisions in the last 4 weeks)"
        )
    else:
        nasdaq_lines = "- Nasdaq consensus data was unavailable for this run; rely on yfinance consensus only."

    confidence_instruction = (
        f"Treat this net-income figure as a known fact (confidence {confidence_pct}% >= "
        f"{HIGH_CONFIDENCE_THRESHOLD_PCT}% threshold) - do not hedge the predicted move on the "
        "grounds that the input itself might be wrong."
        if confidence_pct >= HIGH_CONFIDENCE_THRESHOLD_PCT
        else f"The user's stated confidence in this figure is {confidence_pct}% - treat it as one "
        "plausible scenario and hedge your prediction accordingly."
    )

    return f"""User's own forecast for {quarter}: net income ${predicted_net_income_usd_billion}B, stated confidence {confidence_pct}%.
{confidence_instruction}{revenue_lines}
User's notes: {notes or "(none)"}

Derived: implied EPS ${implied_eps} on {consensus.shares_outstanding} shares outstanding,
implied surprise vs. consensus EPS (${consensus.consensus_eps}) of {implied_surprise_pct}%.

Street consensus for {consensus.symbol}, next earnings date {consensus.next_earnings_date}:
- yfinance consensus EPS: {consensus.consensus_eps} (range {consensus.eps_low} - {consensus.eps_high})
{nasdaq_lines}
- Consensus revenue: {consensus.revenue_average} (range {consensus.revenue_low} - {consensus.revenue_high})
- Analyst price targets: mean {consensus.analyst_target_mean}, median {consensus.analyst_target_median}, range {consensus.analyst_target_low} - {consensus.analyst_target_high}
- Current price: {consensus.current_price}

Last {len(consensus.history)} quarters' EPS surprise history:
{history_lines}

Predict where {consensus.symbol} will trade on the earnings release day ({consensus.next_earnings_date})
given this implied beat/miss, and explain your reasoning."""


def run_analyst_agent(
    predicted_net_income_usd_billion: float, quarter: str, confidence_pct: float, notes: str,
    consensus: ConsensusSnapshot, predicted_net_revenue_usd_billion: float | None = None,
) -> AnalystPrediction:
    user_prompt = _build_user_prompt(
        predicted_net_income_usd_billion, quarter, confidence_pct, notes, consensus, predicted_net_revenue_usd_billion
    )
    result = call_agent_json(SYSTEM_PROMPT, user_prompt)
    return AnalystPrediction(
        symbol=consensus.symbol,
        earnings_date=consensus.next_earnings_date or "",
        predicted_price=float(result["predicted_price"]),
        price_range_low=float(result["price_range_low"]),
        price_range_high=float(result["price_range_high"]),
        confidence=result["confidence"],
        predicted_eps=result.get("predicted_eps"),
        implied_surprise_pct=result.get("implied_surprise_pct"),
        consensus_summary=result["consensus_summary"],
        reasoning=list(result["reasoning"]),
        input_confidence_pct=confidence_pct,
    )
