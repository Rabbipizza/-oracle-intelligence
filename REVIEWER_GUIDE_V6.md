# ORACLE V6 — Reviewer Guide

## Purpose
ORACLE V6 is a research system for long-horizon structural investment intelligence. Its goal is not to output trades from narratives, but to test whether early structural signals add out-of-sample information beyond a conventional baseline.

Core research chain:

`raw sources -> statistical signal discovery -> replicated signal -> semantic concept -> economic transmission hypothesis -> bottleneck -> supplier/pick-and-shovel -> economic capture -> market expectations -> forward residual return -> decision`

The contractual research comparison is:

`BASELINE = Momentum + Earnings Revisions + Valuation + Quality`

versus

`BASELINE + ORACLE`.

A valid conclusion is `NO_EDGE` or `NO_ACTION`.

## Repository and runtime
- Repository: https://github.com/Rabbipizza/-oracle-intelligence
- Default branch: `main`
- Public cockpit: https://rabbipizza.github.io/-oracle-intelligence/
- Production database: Supabase/PostgreSQL. Credentials are intentionally not committed.
- Main workflow: `.github/workflows/oracle-v6-discovery-fdr.yml`
- Python requirements: `requirements-v6.txt`

## Main architecture

### 1. Discovery
`analytics/oracle_v6_formal_nulls.py`
`analytics/oracle_v6_sequential_fdr.py`
`analytics/oracle_v6_discovery_pipeline.py`
`analytics/oracle_v6_trend_probability.py`
`analytics/oracle_v6_signal_lifecycle.py`

The current count-null family uses rolling Poisson / negative-binomial / gamma-Poisson variants. Benjamini-Hochberg controls within-run multiplicity. Inter-run error spending is fixed ex ante with a summable schedule. Signals are lifecycle-gated:

`EPHEMERAL_SIGNAL -> REPLICATED_SIGNAL -> CANDIDATE_FOR_SEMANTIC_BRIDGE`

A replication must come from a sufficiently distinct temporal/corpus window. Current production policy requires at least seven calendar days plus corpus novelty conditions. Ephemeral signals cannot enter the Semantic Bridge.

### 2. Semantic and economic transmission
`analytics/oracle_v6_semantic_bridge.py`
`analytics/oracle_v6_transmission_graph.py`

The Semantic Bridge maps lexical anomalies into canonical concepts. It is descriptive, not causal. Economic edges have explicit epistemic status. Causal claims require a defensible identification strategy.

### 3. Demography
`analytics/oracle_v6_demographic_context.py`
`analytics/oracle_v6_demographic_trends.py`

Demography is treated as a first-class structural family. Current World Bank/WDI observations are explicitly marked as revised current series, not historical PIT vintages; therefore they cannot be used for a strict historical predictive backtest.

### 4. Structural bottlenecks
`analytics/oracle_v6_structural_bottlenecks.py`
`analytics/oracle_v6_bottleneck_tension.py`
`analytics/oracle_v6_bottleneck_gate.py`

Structural dependencies begin as hypotheses/candidates. The tension extractor uses contextual rules rather than simple keyword presence. Current benchmark version is `TENSION_CONTEXT_RULES_V2_BENCHMARK`. The system does not synthesize a bottleneck probability until calibration requirements are met.

### 5. Company exposure and Economic Capture
`analytics/oracle_v6_structural_company_bridge.py`
`analytics/oracle_v6_economic_capture_evidence.py`
`analytics/oracle_v6_capture_calibration_gate.py`
`analytics/oracle_v6_company_capture_gate.py`

This layer distinguishes thematic exposure from economic capture. Supplier relations and issuer evidence are persisted, but capture probabilities remain null until calibrated on sufficient historical outcomes.

### 6. Financial fundamentals and pricing
`analytics/oracle_v6_sec_edge_trigger.py`
`analytics/oracle_v6_sec_materialize.py`
`analytics/oracle_v6_reverse_dcf.py`
`analytics/oracle_v6_fundamental_forecast.py`
`analytics/oracle_v6_market_expectations_gate.py`

Reverse DCF estimates the five-year constant FCF growth rate implied by enterprise value under explicit assumptions. It is a market-expectation measurement, not a target price. The fundamental model is currently `FCF5Y_RIDGE_PIT_V1` and is evaluated walk-forward. Its predictive calibration gate remains separate from point forecast accuracy.

### 7. Decision and forward validation
`analytics/oracle_v6_decision_gate.py`
`analytics/oracle_v6_forward_validation.py`
`analytics/oracle_v6_end_to_end_edge_audit.py`

The decision layer can emit `WATCH`, `NO_ACTION`, or a buy state only when upstream prerequisites are satisfied. Forward validation freezes every production decision and matures 3/6/12/24-month outcomes. SPY residual returns are recorded as a transparent benchmark only; SPY is not the contractual factor baseline.

### 8. Analyst Memory
The LLM analyst is not the trend detector. ORACLE detects; the analyst interprets detected trends and persists structured hypotheses. Memory relations are atomic and versioned. Each edge has its own epistemic status:

- `HYPOTHESIS`
- `DESCRIPTIVE_EVIDENCE`
- `PREDICTIVE_EVIDENCE`
- `CAUSAL_VALIDATED`

Confidence is not inherited from neighboring edges. Historical versions are append-only.

## Scientific safeguards
- point-in-time `available_at` discipline where source vintages permit it;
- explicit revised-series warning where true historical vintages do not exist;
- historical investable universe with lifecycle events and known non-exhaustive delisting debt;
- BH-FDR within run;
- bounded online alpha spending across runs;
- no ephemeral signal in semantic/trend research;
- immutable evaluation clock;
- no probability written when calibration is missing;
- no BUY simply to populate the cockpit;
- forward 3/6/12/24-month validation;
- explicit distinction between descriptive, predictive, causal and investment claims.

## Current scientific status (10 Sep 2026)
The correct top-level state is `EDGE_UNTESTABLE`, not `EDGE_PROVEN` and not `NO_EDGE`.

The currently frozen discovery family contains 3,430 tests. At the current sequential alpha allocation, 1,124 lexical signals survive BH, but they are all still `EPHEMERAL_SIGNAL`; therefore zero lexical discovery signals are currently allowed to enter the Semantic Bridge under the P0-7 lifecycle rule.

The structural/demographic research pipeline can still produce descriptive hypotheses, but this does not count as proof of incremental equity-return edge.

The fundamental forecast has historical walk-forward observations and has beaten a naive benchmark on the frozen development/holdout split, but expectation-gap probabilities remain blocked because calibration diagnostics are not yet accepted.

Forward-return validation does not yet have matured production observations. The required `Momentum + Earnings Revisions + Valuation + Quality` baseline is also not historically complete because true point-in-time analyst-revision history is only now being accumulated prospectively.

## Known debts / caveats
1. Historical US delisting coverage is controlled on the current research perimeter but not an exhaustive CRSP-style market census.
2. WDI demographic data are current revised series, not historical PIT vintages.
3. The P0-8 tension benchmark is currently an internal single-model-expert validation, not independent dual-human annotation.
4. The full contractual factor baseline lacks historical PIT analyst revisions.
5. No live alpha claim should be made before enough replicated signals and matured forward outcomes exist.

## How to inspect without database credentials
1. Open the cockpit: https://rabbipizza.github.io/-oracle-intelligence/
2. Open the repository: https://github.com/Rabbipizza/-oracle-intelligence
3. Read `ORACLE_V6_ARCHITECTURE.md`.
4. Inspect `.github/workflows/oracle-v6-discovery-fdr.yml` for the exact production execution order.
5. Inspect `analytics/oracle_v6_end_to_end_edge_audit.py` for the machine-verifiable edge gate.
6. Inspect `sql/tests/` for database invariants and P0 gates.
7. Open GitHub Actions and inspect the latest `ORACLE V6 Discovery FDR` run step by step.

## How to reproduce the Python side locally
Requires Python 3.12 and a PostgreSQL connection string to a schema containing the ORACLE tables.

```bash
git clone https://github.com/Rabbipizza/-oracle-intelligence.git
cd=-oracle-intelligence
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements-v6.txt
export ORACLE_SUPABASE_DB_URL='postgresql://...'
python -m py_compile analytics/oracle_v6_*.py
```

Then execute the same sequence as the GitHub workflow, for example:

```bash
python analytics/oracle_v6_formal_nulls.py
python analytics/oracle_v6_sequential_fdr.py
python analytics/oracle_v6_discovery_pipeline.py
python analytics/oracle_v6_trend_probability.py
python analytics/oracle_v6_signal_lifecycle.py
python analytics/oracle_v6_semantic_bridge.py
python analytics/oracle_v6_transmission_graph.py
```

Continue in the exact order defined in `.github/workflows/oracle-v6-discovery-fdr.yml`. Do not bypass lifecycle or calibration gates to obtain non-empty output.

Note: the shell command after clone should be `cd -oracle-intelligence` if the repository is cloned with its native leading-hyphen name; many shells interpret leading-hyphen arguments as options, so a safer form is `cd ./-oracle-intelligence`.

## Database review queries
A reviewer with read access can start with:

```sql
select lifecycle_state, count(*)
from oracle_v6_signal_lifecycle
group by 1 order by 1;

select epistemic_status, count(*)
from oracle_v6_analyst_memory_links
group by 1 order by 1;

select *
from oracle_v6_edge_audit_runs
order by audited_at desc
limit 10;

select decision, count(*)
from oracle_v6_decisions
where as_of=(select max(as_of) from oracle_v6_decisions)
group by 1;

select *
from oracle_v6_forward_signals
order by as_of desc
limit 50;

select *
from oracle_v6_forward_outcomes
order by target_month, signal_id
limit 100;
```

## What the reviewer should try to falsify
The key question is not whether ORACLE tells convincing stories. The key empirical test is whether `BASELINE + ORACLE` improves point-in-time out-of-sample prediction of fundamental revisions and factor-adjusted residual equity returns relative to `BASELINE` alone, after costs and multiple-testing control.

Recommended audit targets:
- leakage through `available_at` or revised data;
- survivorship/delisting bias;
- temporal multiple testing and correlated replications;
- LLM hypothesis contamination;
- calibration quality of bottleneck/capture/expectation probabilities;
- dependence between training, validation and holdout windows;
- whether improvements survive ablation of discovery, bottleneck, capture and pricing modules;
- whether alpha survives sector/size/momentum matched controls;
- whether negative and failed trends are represented, not only famous winners.

## Expected reviewer conclusion today
The scientifically defensible conclusion today is:

> ORACLE V6 has a substantially more rigorous architecture than a thematic stock screener and contains several real empirical safeguards, but it has not yet demonstrated an investable out-of-sample edge. The system is currently in the evidence-accumulation and forward-validation phase.

That is intentional: the architecture is designed to permit `NO_EDGE` rather than manufacture a positive result.
