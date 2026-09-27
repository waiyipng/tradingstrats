# Improving News-Signal Predictiveness

## Main finding

The first 20-trading-day result was not a valid test of the intended strategy. The backtest asked Finnhub for 2023-2025 news in one request, but the API returned only late-December 2025 articles:

- AAPL: 240 articles across 13 dates, with coverage from 2025-12-19 to 2025-12-31.
- JPM: 238 articles across 15 dates, with coverage from 2025-12-17 to 2025-12-31.
- Most symbols therefore had only 3-45 news days across 748 daily observations.
- The remaining observations were forced `HOLD`, so the reported correlation mostly measured an incomplete data feed rather than the strategy.

A bounded Polygon request returned 532 AAPL articles for January 2023. A short Polygon replay produced 1,413 articles across 97 days for the first quarter of 2023. The backtest now defaults to Polygon monthly historical requests and records news coverage in its report. Finnhub remains available with `--news-provider finnhub`, but its historical retention must be verified before use.

The backtest also now regresses forward returns against the continuous aggregate score. Previously it used only `BUY=+confidence`, `SELL=-confidence`, and `HOLD=0`, which discarded information and produced very sparse explanatory values.

## What financial-news research suggests

### 1. News effects are event-shaped, not necessarily 20-day trends

Media sentiment can affect prices and trading activity around news arrival, but the reaction can be rapid, followed by continuation or reversal depending on attention, surprise, liquidity, and the type of news. A 20-day close-to-close return can dilute a real one-day reaction with unrelated market movement.

Relevant work:

- [Tetlock, Giving Content to Investor Sentiment](https://doi.org/10.1111/j.1540-6261.2007.01234.x): newspaper pessimism contains information about short-horizon market returns and later reversal.
- [Engelberg and Parsons, The Causal Impact of Media in Financial Markets](https://doi.org/10.1257/aer.101.5.1510): media exposure and geographic variation matter for market reactions.
- [Da, Engelberg, and Gao, In Search of Attention](https://doi.org/10.1093/rfs/hhr069): investor attention is related to trading activity and subsequent return behavior.

**Implication:** measure 1-, 2-, 5-, 10-, and 20-day abnormal returns separately. Do not optimize only for 20-day correlation.

### 2. Generic word counts are weak financial sentiment features

The current analyzer counts words such as `strong`, `growth`, `risk`, `regulatory`, and `beat`. It does not understand negation, who made the claim, whether the article is about the target company, or whether the news is already anticipated by the market. Generic sentiment dictionaries also misclassify financial language.

Relevant work:

- [Loughran and McDonald, When Is a Liability Not a Liability?](https://doi.org/10.1111/j.1540-6261.2010.01625.x): financial text needs domain-specific language measurement because ordinary sentiment dictionaries perform poorly in financial filings.

**Implication:** use a financial-domain sentiment model or a labeled, time-split classifier, and add entity relevance, negation, modality, novelty, and event-type features.

### 3. The relevant target is abnormal return

A stock can rise after positive news simply because the market or sector rose. Raw forward returns mix the news response with market beta, sector rotation, earnings season, rates, and broad risk appetite.

Relevant method:

- [MacKinlay, Event Studies in Economics and Finance](https://doi.org/10.1086/296833): estimate the return attributable to an event relative to an expected-return model.

**Implication:** compare each stock with a benchmark such as SPY plus QQQ for technology or XLF for financials. Report market-adjusted and sector-adjusted returns, not only raw returns.

### 4. Backtest observations are not independent

Daily 20-day forward returns overlap heavily. A signal on Monday and a signal on Tuesday share 19 of 20 return days. The apparent sample size is therefore much larger than the effective independent sample size.

**Implication:** use event-level samples, non-overlapping evaluation windows, or block-bootstrap/Newey-West inference. Do not interpret ordinary correlation significance from 748 overlapping observations.

### 5. Out-of-sample discipline matters

Trying multiple providers, horizons, thresholds, keyword sets, sectors, and model parameters can produce a high historical result by chance.

Relevant warning:

- [Bailey et al., The Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253).

**Implication:** freeze the feature and threshold specification on a training period, select parameters once, and report a completely untouched validation period. Keep a final holdout that is not used for iteration.

## Highest-impact improvement sequence

### Priority 1: Make the data test valid

1. Use Polygon or another provider with verified historical retention.
2. Store the raw historical news response and a normalized cache so reruns use identical data.
3. Record article count, unique news dates, earliest/latest publication, provider, and API errors in every report.
4. Stop or mark a symbol invalid when coverage does not span the requested test interval.
5. Deduplicate across providers using canonical title and URL, while retaining the best source metadata.

### Priority 2: Use event-study targets

For each article or news cluster:

1. Define the event timestamp in the exchange timezone.
2. Enter at the next tradable price after publication, not always the next daily close.
3. Calculate raw return and abnormal return at 1, 2, 5, 10, and 20 trading days.
4. Include a pre-event window, such as `[-5, -1]`, to check whether the move already started before publication.
5. Cluster articles published within the same 24-hour window so one news cycle is not counted as many independent events.

### Priority 3: Preserve continuous information

The model should expose and evaluate:

- Continuous sentiment score.
- Positive and negative intensity separately.
- Confidence and source agreement.
- Novelty relative to recent articles.
- Event type: earnings, guidance, product, legal, regulatory, management, analyst action, or macro.
- Source reliability and independent-source count.
- Publication time and whether the market was open.

The current implementation now exposes `evidence.combined_score` and uses it for regression. The discrete decision should remain a trade policy layer, not the only research feature.

### Priority 4: Improve language understanding

A practical progression is:

1. Add phrase-level negation handling, such as `not profitable` and `no growth`.
2. Require target-entity relevance using the configured symbol and aliases.
3. Add novelty checks against recent headlines so repeated syndication does not count as new information.
4. Replace or augment keyword scoring with a finance-specific sentiment model.
5. Calibrate sentiment against a labeled sample of articles and freeze the label rules before the holdout period.
6. Separate event classification from sentiment. `Regulatory` is not always negative, and `cloud` or `AI` is not always positive.

### Priority 5: Validate as a strategy, not only as a correlation

The next report should include:

- Event count and effective independent event count.
- Mean and median abnormal return by signal bucket.
- Return distribution, hit rate, turnover, maximum drawdown, Sharpe-like risk-adjusted statistics, and exposure.
- Commissions, spread, slippage, and delayed execution.
- Sector and market benchmark comparisons.
- Training, validation, and untouched holdout periods.
- Results by event type, source, market regime, and publication time.
- Confidence intervals from event-level bootstrap or robust time-series inference.

## Suggested experiment matrix

| Experiment | Feature | Target | Purpose |
| --- | --- | --- | --- |
| A | Continuous keyword score | 1/2/5/10/20-day abnormal return | Establish the event horizon |
| B | Finance sentiment model | Same abnormal-return horizons | Test whether language quality adds signal |
| C | Sentiment plus novelty and attention | Same targets | Separate fresh information from repeated coverage |
| D | Event type plus sentiment | Type-specific abnormal returns | Find catalysts that work for each sector |
| E | Frozen model, untouched holdout | Portfolio P&L after costs | Test whether the effect survives implementation |

## Current recommendation

Do not tune the keyword thresholds or claim profitability from the original Finnhub result. First rerun the complete 2023-2025 test using the Polygon-backed provider, inspect coverage, and compare continuous-score abnormal returns at multiple horizons. Only after a stable event-level effect appears should the strategy add a portfolio simulator or more complex language model.
