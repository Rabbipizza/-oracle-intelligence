# ORACLE Research Doctrine — V6

## Mission
ORACLE is an investment-research system whose only defensible purpose is to test whether newly detected structural information contains **incremental point-in-time predictive power** for future fundamentals and factor-adjusted returns.

A coherent economic story is not alpha. ORACLE must be allowed to return `NO_EDGE` and `NO_TRADE`.

## Non-negotiable null hypothesis

**H0:** ORACLE signals do not improve prediction of future fundamentals or factor-adjusted returns beyond simple observable baselines (momentum, valuation, quality/profitability, earnings revisions, sector/country factors).

**H1:** ORACLE adds statistically significant, stable, point-in-time, net-of-cost incremental predictive information.

Every module must exist to help test H0.

## Strict separation of engines

### 1. Discovery / Signal engine
Purpose: detect abnormal emergence without predefined themes.

Inputs may include scientific publications, patents, SEC/company filings, technical sources, industrial data, macro data, trade data and geopolitical evidence.

Required outputs:
- `first_detected_at`
- novelty
- acceleration
- persistence
- source diversity
- convergence
- explicit null-model surprise
- `p_structural_trend`

A frequency is not "abnormal" without a null model. Candidate null models include Poisson/negative-binomial baselines, Hawkes/self-exciting processes, seasonal baselines and change-point models.

### 2. Economic transmission / causal hypothesis engine
Purpose: convert trends into testable economic hypotheses.

The LLM is permitted to GENERATE hypotheses but never to VALIDATE them by narrative authority.

Each edge must contain:
- source_node
- target_node
- sign
- economic mechanism
- expected lag
- expected elasticity/range when estimable
- evidence references
- independent evidence count
- validation method
- posterior/confidence
- valid_from / valid_to

Preferred chain:
`Trend -> Demand Shock -> Required Inputs/Capacity -> Constraint -> Economic Capture -> Company Fundamentals`

Every important edge must be subsequently tested using observed data where possible (panel regressions, event studies, distributed-lag models, local projections, Granger-style predictive tests only when interpreted correctly, instrumental-variable/natural-experiment designs when available).

### 3. Market expectations / pricing engine
Purpose: determine whether the economically valid information is already priced.

This engine is independent of the structural engine and may use only point-in-time market-observable data and point-in-time fundamental estimates.

It must not contaminate Structural Early Bird.

Preferred outputs:
- market-implied growth/margins/FCF from reverse valuation
- independent fundamental forecast distribution
- `p_fundamentals_exceed_expectations`
- expected factor-adjusted excess return distribution
- entry decision

## Point-in-time rule
Every research observation must preserve, when applicable:
- `event_date`
- `published_at`
- `available_at`
- `ingested_at`
- `vintage_id` / revision information

Backtests may use only observations with `available_at <= decision_time`.

Delisted, bankrupt, merged and failed companies remain in historical universes.

## LLM temporal contamination rule
A contemporary LLM has post-event knowledge and therefore cannot be treated as a historically clean forecaster.

For historical simulations:
- the LLM may extract/normalize only from the frozen pre-T corpus supplied to it;
- generated causal hypotheses must be stored separately from validated evidence;
- no historical edge may be promoted merely because the LLM knows what happened later;
- all prompts, model versions, evidence packs and outputs must be logged.

## Trend model
Prefer calibrated probabilities over arbitrary scores.

States may include:
`NOISE -> SIGNAL -> EMERGING -> ACCELERATING -> CONFIRMED -> MATURE -> DECLINING`

Primary research output:
`P(Structural Trend | information available at t)`

Calibration must be evaluated out-of-sample (Brier score, log loss, reliability curves).

## Bottleneck definition
A bottleneck is not a semantic association. It is an economically consequential probability of future effective demand exceeding effective supply.

For resource/capacity j and horizon h:

`P(B_j,h = 1 | X_t) = P(Demand_j,t+h > EffectiveSupply_j,t+h AND economic impact is material)`

Approximate effective supply:
`ExistingCapacity * Utilization + Inventories + ExpectedNewCapacity + Imports + Recycling - ExpectedDisruptions`

Relevant covariates may include demand growth, capacity pipeline, utilization, inventories, lead times, concentration, geographic concentration, substitution, elasticity, permitting, trade restrictions and geopolitical risk.

Outputs must include 6m/12m/24m/36m probabilities and uncertainty intervals.

Calibration must be tested with Brier score/log loss. Time-to-materialisation may be modeled with survival methods (e.g. Cox / parametric survival / competing risks where appropriate).

## Commodities
Commodities are one possible bottleneck class, never automatically bottlenecks.

Trend dependence -> commodity exposure is only a hypothesis. Scarcity must be tested from demand, supply, inventories, capacity additions, recycling, substitution, quality and geography.

## Economic Capture
Narrative thematic exposure is insufficient.

For each company, estimate the mechanism by which the structural change affects:
- exposed revenue share
- incremental revenue
- incremental margins
- pricing power
- usable capacity
- backlog
- required CAPEX
- competitive intensity
- customer/supplier concentration
- barriers to entry
- balance-sheet risk

The preferred object is a probabilistic `economic_capture` estimate rather than a manually weighted score.

## Picks & Shovels
A company qualifies only when the chain is evidenced:
`Trend -> New Demand -> Constraint -> Required Investment -> Product/Service -> Company Revenue Exposure -> Deliverable Capacity -> Fundamental Impact`

Missing links remain hypotheses.

## Structural Early Bird
Structural Early Bird remains independent of current share-price performance and valuation.

It should be derived from statistically estimated or calibrated components such as:
- `p_structural_trend`
- economic-capture probability/magnitude
- novelty / recognition gap
- causal evidence strength

Avoid arbitrary 0–100 weights. If a display score is required for UX, derive it monotonically from calibrated model outputs and keep the underlying probabilities visible.

## Expectations Gap
Do not equate high multiples with "priced in".

Construct two independent objects:
1. a fundamental forecast distribution;
2. a market-implied fundamental distribution, preferably via reverse DCF / reverse multiples / implied growth-margin assumptions.

Primary output:
`P(Fundamentals_future > MarketImpliedFundamentals)`
plus magnitude and uncertainty.

A market-rerating proxy may be shown only as a fallback diagnostic and must never be labelled an Expectation Gap.

## Macro and geopolitics
Do not award arbitrary bonus/malus points.

Macro should primarily enter as regimes/interactions (rates, inflation, liquidity, credit, USD, industrial cycle, commodity cycle).

Geopolitics should modify graph variables such as disruption probability, supply loss, route dependence, costs, lead time, concentration and risk premia.

Retain only interactions that improve out-of-sample performance.

## Orthogonalisation / double counting
Before combining signals, test correlations and latent factors. Residualise/orthogonalise where needed.

Common latent factors include:
- ATTENTION
- MOMENTUM
- GROWTH
- QUALITY
- SCARCITY
- MACRO LIQUIDITY

Use regularisation, residualisation, PCA/factor methods or hierarchical models as justified. Do not reward the same information several times under different names.

## Primary targets
At horizons 3m/6m/12m/24m:

`Y_return(i,t,h) = realized_return(i,t->t+h) - expected_factor_return(i,t->t+h)`

Also predict future revisions/changes in:
- revenue
- EPS
- margins
- backlog
- FCF

The structural graph should predict fundamentals before it is credited for predicting prices.

## Baselines
ORACLE must be compared against at least:
- broad market
- sector benchmark
- equal weight
- momentum
- valuation
- quality/profitability
- earnings revisions
- simple multifactor model
- matched random portfolios

Critical baseline:
`Momentum + Earnings Revisions + Valuation + Quality`

ORACLE has value only if `BASELINE + ORACLE` materially and robustly improves on `BASELINE` out-of-sample.

## Backtesting
Backtests are strict point-in-time and walk-forward.

Rules:
- frozen research corpus by decision date
- vintage-aware macro data
- historical constituents, including failures/delistings
- transaction costs and liquidity constraints
- untouched true holdout periods
- experiment registry containing every tested specification
- no model alteration after observing a holdout result without invalidating that holdout

Evaluation must include successes and failures, not handpicked famous winners.

## Multiple testing and backtest overfitting
Because ORACLE searches many trends, constraints, companies and horizons, multiple testing is a first-class risk.

Use appropriate controls such as:
- False Discovery Rate
- White Reality Check
- Hansen SPA
- Deflated Sharpe Ratio
- Probability of Backtest Overfitting
- bootstrap confidence intervals

Never present only the best-performing specification.

## Ablation tests
Compare full ORACLE with versions excluding each major module:
- trend discovery
- economic graph
- bottleneck
- economic capture
- expectations gap
- macro
- geopolitics

A module that does not improve robust out-of-sample performance should be removed or downgraded.

## Falsification criteria
ORACLE is considered unsupported if its edge:
- disappears after known factor controls;
- disappears out-of-sample;
- does not predict future fundamental changes;
- is concentrated in a few famous historical winners;
- is unstable across regimes;
- disappears after realistic costs;
- fails to outperform simple baselines.

## Decision set
The system may return exactly one of:
- `BUY_CANDIDATE`
- `PILOT_BUY`
- `WATCH`
- `WAIT`
- `NO_EDGE`
- `NO_ACTION`
- `REJECT`

`NO_EDGE` and `NO_ACTION` are valid and preferred to fabricated confidence.

## Cockpit principle
The cockpit is a decision interface, but must expose scientific uncertainty.

For every candidate show:
1. What changed?
2. `P(structural trend)` and calibration status
3. Economic transmission chain and evidence strength
4. `P(bottleneck)` by horizon
5. Economic capture mechanism and expected fundamental impact
6. Market-implied expectations
7. Expectation gap probability/magnitude
8. Expected factor-adjusted return and uncertainty
9. Baseline comparison
10. Decision
11. Invalidation conditions
12. Data/evidence gaps

Priority order:
`VALIDATION > POINT-IN-TIME INTEGRITY > PREDICTIVE POWER > INTERFACE`.
