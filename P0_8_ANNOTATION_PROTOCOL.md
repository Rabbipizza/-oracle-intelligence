# P0-8 — Independent Human Annotation Protocol

This protocol is part of the scientific closure gate for Evidence-Backed Tension. It is not an optional review step.

## Frozen sample

Use rows from `public.oracle_v6_tension_annotation_sample` where `sample_version='TENSION_SAMPLE_V1'`.
The sample was selected before human labels were collected. Do not resample based on observed labels.

## Independent annotation requirement

Each sampled excerpt must be labelled by exactly two independent human annotators before either person can see the other person's label. Store labels in `public.oracle_v6_tension_annotations` with two distinct `annotator_id` values.

Allowed labels:

- `REAL_TENSION`: the excerpt affirmatively states a current or materially relevant economic/operational constraint, scarcity, backlog, capacity bottleneck, shortage, allocation, lead-time problem, supply limitation, or unresolved demand/capacity imbalance for the relevant bottleneck.
- `RESOLVED_TENSION`: tension existed or is mentioned, but the excerpt says it has been mitigated, resolved, normalized, is no longer constraining, or clearly belongs only to a past condition that is not currently operative.
- `NO_TENSION`: the excerpt does not assert a relevant economic constraint. Mere occurrence of vocabulary such as supply, demand, capacity or backlog is insufficient.
- `AMBIGUOUS`: the excerpt does not contain enough context to distinguish current real tension from resolution/no tension.

## Independence / leakage controls

Annotators must not see:
- the other annotator's label;
- benchmark precision/recall results during annotation;
- model tuning changes made after the sample was frozen.

They may see the raw excerpt, ticker, evidence key and bottleneck context.

## Agreement gate

After all rows have two labels, run `analytics/oracle_v6_tension_benchmark.py`.
Cohen's kappa is computed before adjudication. If kappa < 0.60, the class definitions must be clarified and the annotation repeated; do not tune the extractor against a low-agreement benchmark.

For disagreements with acceptable overall kappa, add an explicit row to `public.oracle_v6_tension_adjudications` with the final label and reason. No silent adjudication is allowed.

## Frozen downstream threshold

The active config `TENSION_VALIDATION_V1` requires:
- at least 200 double-annotated examples;
- Cohen's kappa >= 0.60;
- precision on `REAL_TENSION` >= 0.90;
- all disagreements used in scoring adjudicated.

Until all conditions pass, `oracle_v6_bottleneck_forecasts` is fail-closed by a database trigger.

## Reproducible closure

Run:

```bash
python analytics/oracle_v6_tension_benchmark.py
psql "$ORACLE_SUPABASE_DB_URL" -f sql/tests/p0_8_tension_validation_closure.sql
```

P0-8 is CLOSED only if both commands exit successfully.