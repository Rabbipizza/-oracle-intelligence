# ORACLE V6 — P0-6 / P0-7 / P0-8 scientific status report

Date: 2026-09-10

## P0-6 — Analyst Memory epistemic integrity

**Status: CLOSED**

Implemented:
- Atomic table `oracle_v6_analyst_memory_links` with per-link epistemic status.
- Allowed statuses: `HYPOTHESIS`, `DESCRIPTIVE_EVIDENCE`, `PREDICTIVE_EVIDENCE`, `CAUSAL_VALIDATED`.
- Append-only audit table `oracle_v6_analyst_memory_link_versions`.
- Link-local promotion guard: a status change requires changed evidence on that same link.
- Explicit reason required for any epistemic regression.
- Existing Aging Acceleration memory migrated into atomic links.
- Existing Structural Bottleneck evidence materialized independently per link.
- Cockpit displays epistemic badges per Analyst Memory link.

Executable evidence:
- `sql/tests/p0_6_memory_link_independence.sql`
- Direct production test result: `P0-6 PASS`.
- Production query on Aging Acceleration: 24 `HYPOTHESIS` links and 1 `DESCRIPTIVE_EVIDENCE` link.
- GitHub Pages deployment containing per-link badges completed successfully.

## P0-7 — Sequential / temporal multiple testing

**Status: CLOSED for the requested guardrail**

Implemented:
- Pre-registered online alpha-spending configuration `ONLINE_ALPHA_SPENDING_BH_V1`.
- Run-level schedule: `gamma_t = 6/(pi^2*t^2)`; because `sum gamma_t = 1`, cumulative allocated alpha is bounded by `target_alpha=0.05` for an unbounded sequence of distinct test families.
- Identical formal p-value families are fingerprinted and reuse the previous budget instead of spending alpha again.
- Within each run, BH uses the allocated `alpha_t` rather than a fixed 0.05.
- Signal lifecycle states: `EPHEMERAL_SIGNAL`, `REPLICATED_SIGNAL`, `CANDIDATE_FOR_SEMANTIC_BRIDGE`.
- Independent temporal replication requires BOTH at least 7 calendar days and corpus novelty of at least 3 new documents and at least 25% new-document ratio.
- Two qualifying windows are required for `REPLICATED_SIGNAL`; three for `CANDIDATE_FOR_SEMANTIC_BRIDGE`.
- Semantic Bridge processes only replicated/candidate signals.
- Statistical Discovery branch of `oracle_v6_trend_universe` excludes ephemeral signals.
- Replication dates and alpha trace are persisted per signal.

Executable evidence:
- `sql/tests/p0_7_sequential_fdr_gate.sql`.
- Production direct gate result: `P0-7 PASS`.
- Current production family: 3,430 hypotheses; allocated alpha `0.0303963550927013`; cumulative spend `0.0303963550927013 <= 0.05`.
- 1,124 real current signals were classified `EPHEMERAL_SIGNAL` on the first qualifying window.
- Production query: zero ephemeral signals in `oracle_v6_trend_universe`.
- Production query: zero ephemeral signals in Semantic Bridge edges.

Methodological note: this is a conservative **summable online alpha-spending + within-run BH** design. It is not LORD or SAFFRON. The schedule is fixed before observing sequential outcomes and provides a hard cumulative alpha bound.

## P0-8 — Evidence-Backed Tension extraction benchmark

**Status: OPEN — fail-closed, waiting on the required independent human annotation**

Implemented:
- Frozen validation config `TENSION_VALIDATION_V1`:
  - minimum double-annotated sample = 200;
  - minimum Cohen's kappa = 0.60;
  - minimum precision on `REAL_TENSION` = 0.90.
- Frozen stratified sample `TENSION_SAMPLE_V1`: 244 SEC evidence excerpts.
- Tables for two independent annotations and explicit adjudication.
- Reproducible benchmark script `analytics/oracle_v6_tension_benchmark.py` computing Cohen's kappa before adjudication and precision/recall/F1 by class.
- Closure gate `sql/tests/p0_8_tension_validation_closure.sql`.
- Automatic database trigger blocks any insert/update into `oracle_v6_bottleneck_forecasts` unless the benchmark passes.
- Safety test `sql/tests/p0_8_tension_validation_safety.sql`.
- Human protocol: `P0_8_ANNOTATION_PROTOCOL.md`.

Current evidence:
- Sample size: 244.
- Double-annotated examples: 0.
- `downstream_allowed=false`.
- Direct production safety test: `P0-8 SAFETY PASS: downstream blocked`.

P0-8 cannot honestly be declared CLOSED until two independent human annotators label at least 200 frozen examples and the resulting benchmark passes the frozen kappa and REAL_TENSION precision thresholds. AI-generated duplicate labels are not accepted as substitutes for the required human annotations.

## Feature freeze

No new intelligent layer, new LLM interpretation engine, or new investment feature is authorized while P0-8 remains open. Data collection and forward validation may continue.
