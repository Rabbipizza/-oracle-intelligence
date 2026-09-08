# ORACLE V6 — Scientific Architecture

## Executive synthesis of the two audits

Both reviews agree on the same diagnosis: ORACLE has a defensible economic intuition but its current implementation risks converting plausible stories into apparently precise scores. V6 therefore separates three independent engines and makes all outputs testable against explicit null models and baselines.

### Engine 1 — Signal Discovery
Goal: detect abnormal emergence without predefined themes.

Core methods:
- seasonal Poisson / negative-binomial baseline for event counts;
- Hawkes process where self-excitation matters;
- change-point / structural-break detection;
- temporal clustering / embeddings / novelty;
- calibrated `P(structural trend)`.

Key outputs:
- `first_detected_at`
- `signal_surprise_z`
- `null_model_pvalue`
- `p_structural_trend`
- calibration diagnostics.

### Engine 2 — Economic Transmission
Goal: turn detected trends into falsifiable economic hypotheses.

LLM role: hypothesis generation and structured extraction only.
Validation role: econometric/statistical evidence.

Core methods:
- distributed-lag regressions;
- local projections;
- panel regressions with fixed effects;
- event studies;
- IV / natural experiments when defensible;
- survival models for time-to-bottleneck;
- Bayesian updating of edge confidence.

Core outputs:
- signed economic graph edges;
- estimated lags / effect ranges;
- `p_bottleneck_{6,12,24,36m}`;
- economic-capture distributions.

### Engine 3 — Market Expectations / Pricing
Goal: estimate whether validated economic information is already priced.

Core methods:
- reverse DCF / reverse multiple decomposition;
- point-in-time analyst estimates/revisions when available;
- factor model residual returns;
- hierarchical logistic/Bayesian models or regularised regressions for entry probability;
- macro regime interactions only if they improve OOS performance.

Key outputs:
- market-implied fundamentals;
- independent fundamental forecast distribution;
- `p_fundamentals_exceed_expectations`;
- expected factor-adjusted residual return;
- decision.

## Python stack

Recommended packages:
- data: `pandas`, `numpy`, `polars`, `pyarrow`;
- stats: `statsmodels`, `scipy`;
- ML: `scikit-learn`;
- Bayesian: `pymc`, `arviz`;
- survival: `lifelines` or `scikit-survival`;
- change points: `ruptures`;
- Hawkes: `tick` if maintainable in environment, otherwise custom likelihood / alternative maintained implementation;
- graphs: `networkx` for research, PostgreSQL tables for production persistence;
- NLP: `sentence-transformers`, `transformers`, vector search via existing store;
- validation: `arch` where useful, custom bootstrap / multiple-testing utilities;
- orchestration: preserve existing workers first, then isolate into deterministic modules.

## Statistical null models

### Count surprise
For topic/entity count `N_t` under expected intensity `lambda_t`:

`N_t ~ Poisson(lambda_t)`

Use negative-binomial when over-dispersion is material.

Store:
- expected count;
- observed count;
- z/surprise;
- tail probability;
- model family;
- model version.

### Hawkes alternative
For clustered/self-exciting events:

`lambda(t) = mu(t) + sum(alpha * exp(-beta*(t-ti)))`

Compare held-out likelihood against the simpler null. Do not default to Hawkes if it does not improve predictive fit.

### Structural breaks
Use `ruptures` / Bai-Perron-style multiple-break procedures to flag level/slope changes. A break is evidence of a regime change, not proof of an investable trend.

## Bottleneck model

At horizon h, define outcome:
`B_j,t,h = 1` if realized effective demand materially exceeds effective supply and the constraint produces an observable economic consequence (price spike, utilization stress, backlog/delay, rationing, margin transfer or equivalent pre-specified criterion).

Candidate covariates:
- demand growth;
- utilization;
- inventories;
- announced capacity pipeline;
- lead time;
- producer/geographic concentration;
- import dependence;
- substitution elasticity;
- recycling response;
- geopolitical disruption probability.

Models:
1. regularised logistic regression baseline;
2. hierarchical Bayesian logistic model for sparse categories;
3. Cox / parametric survival model for time-to-constraint;
4. calibration measured with Brier score, log loss and reliability curves.

## Economic graph validation

Each LLM-generated edge begins as `HYPOTHESIS`.

Promotion levels:
- `HYPOTHESIS`
- `SUPPORTED_DESCRIPTIVE`
- `SUPPORTED_PREDICTIVE`
- `SUPPORTED_CAUSAL`
- `REJECTED`

`SUPPORTED_CAUSAL` requires a defensible identification strategy; predictive timing alone is insufficient.

## Economic capture

For company i exposed to node j, estimate:

`DeltaRevenue ~ exposed_revenue * demand_sensitivity * deliverable_capacity`

`DeltaFCF ~ DeltaRevenue * incremental_margin - incremental_capex - working_capital_effect`

Store distributions, not only point estimates.

## Expectation gap

Build two independent distributions:

1. `F_fundamental`: fundamental outcomes implied by ORACLE's economic model;
2. `F_market`: outcomes implicit in price / consensus.

Core output:
`P(F_fundamental > F_market)`

Reverse DCF should infer combinations of growth, margin, reinvestment and discount-rate assumptions consistent with price. Historical-multiple comparisons are secondary diagnostics only.

## Target variable

Primary market target:

`Y_i,t,h = realized_return_i,t:t+h - expected_factor_return_i,t:t+h`

for h in {3m,6m,12m,24m}.

Factor controls should include, depending on market coverage:
- market;
- size;
- value;
- momentum;
- profitability/quality;
- investment;
- industry;
- country.

Secondary targets:
- future revenue revision;
- future EPS revision;
- future margin change;
- future FCF revision;
- backlog change where observable.

Structural modules must prove value on fundamental targets before being credited for stock-selection alpha.

## Baselines

Mandatory comparator:
`Momentum + Earnings Revisions + Valuation + Quality`

Additional comparators:
- broad benchmark;
- sector benchmark;
- equal-weight universe;
- pure momentum;
- pure revisions;
- multifactor model;
- sector/size/momentum matched random portfolios.

The primary research comparison is:
`BASELINE` vs `BASELINE + ORACLE`.

## Point-in-time protocol

Every observation requires `available_at`.
Historical simulation at T may use only rows with `available_at <= T`.

For revised datasets store vintages. For equities store historical universe membership and delisting outcomes.

LLM historical runs must use frozen evidence packs and persist:
- model identifier/version;
- prompt hash;
- source-document ids;
- max available_at;
- output hash.

## Walk-forward protocol

Example:
- train: expanding historical window;
- validation: next fixed block;
- test: immediately following block;
- roll forward;
- final untouched holdout never inspected during tuning.

Any model change made after reading a holdout invalidates that holdout.

## Failure cases / anti-hindsight sample

Historical evaluation must automatically sample both winners and losers from the full contemporaneous trend universe. It must contain:
- failed technologies;
- temporary shortages;
- overbuilt capacity cycles;
- popular narratives with poor shareholder returns;
- exposed firms whose margins deteriorated;
- delisted / bankrupt names.

Do not define the test set from famous ex-post winners.

## Multiple testing

Maintain an experiment registry recording every model/specification/horizon tried.

Apply as appropriate:
- Benjamini-Hochberg FDR;
- White Reality Check;
- Hansen SPA;
- Deflated Sharpe Ratio;
- Probability of Backtest Overfitting;
- bootstrap confidence intervals.

## Ablation

Every major module must justify its existence with OOS incremental value. Test full model versus removal of:
- discovery;
- bottleneck;
- graph;
- economic capture;
- expectation gap;
- macro;
- geopolitics.

## Refactor strategy

Do not delete V5 workers immediately.

1. Freeze current V5 as legacy benchmark.
2. Add V6 scientific tables and pure research functions.
3. Produce V6 outputs in parallel with V5.
4. Compare calibration and OOS performance.
5. Only then migrate cockpit decisions to V6.

This avoids losing historical data and gives ORACLE a clean benchmark against its own prior heuristic architecture.
