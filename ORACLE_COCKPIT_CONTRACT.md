# ORACLE-IA Cockpit UI Contract — v1.0

STATUS: LOCKED
LOCKED_AT: 2026-09-21
PURPOSE: Daily scientific runs update DATA ONLY. They must never redesign the cockpit.

## Immutable section order
01 Executive Pulse
02 Billboard — Top 20 Companies
03 ORACLE vs QQQ — 1,000 CHF
04 Top 5 Trends
05 Causal Chains & Bottlenecks
06 Raw Materials Map
07 Early Compounders — Fit != Timing
08 Scientific Evidence — FACT / INFERENCE / HYPOTHESIS / INVALIDATION
09 J-1 Change Log
10 History
11 Rejected / Noise
12 Data Quality & Run Health

## Immutable Billboard columns
Rank | Delta rank | Ticker | Company | Trend | Fit | Timing | Perf J-1 | Benchmark | Gap/progress

## Immutable semantics
Fit and Timing are separate.
Timing labels: TOO_EARLY | WATCH | ATTRACTIVE_TIMING | WAIT_FOR_PULLBACK | TOO_EXPENSIVE | REJECT.
Leader convergence: CLOSING | STABLE | WIDENING | UNDEFINED.
Daily change: NEW | RISING | STABLE | FALLING | DROPPED.
Unknown/unjustified numeric values MUST remain NULL.
ORACLE vs QQQ uses the same time window and 1,000 CHF fully invested; do not introduce a cash benchmark unless methodology explicitly changes.

## Daily-run permissions
Allowed: values, rows, dates, ranks, deltas, evidence, status, history, sources, health indicators.
Forbidden: changing section order, adding/removing core sections, renaming columns, changing semantic labels, changing navigation, redesigning colors/layout, or changing benchmark methodology.

## Migration rule
Any structural/UI change requires an explicit cockpit migration requested separately from a daily research run. Increment UI contract version and document the migration. Never silently change presentation during a daily run.
