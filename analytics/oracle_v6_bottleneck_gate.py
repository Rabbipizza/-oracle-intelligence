#!/usr/bin/env python3
"""ORACLE V6 bottleneck forecast gate.

A descriptive CONSTRAINED_BY edge is not a forecast. This worker allows a
bottleneck probability only when (a) the candidate has independent descriptive
support and (b) a calibrated historical outcome model exists. Until then it
writes no forecast rows and records an explicit NO_FORECAST state in the
experiment metrics.
"""
from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, text

MODEL_VERSION = "BOTTLENECK_GATE_V1"
MIN_INDEPENDENT_GROUPS = 2
MIN_CALIBRATION_OUTCOMES = 20


def _engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url, pool_pre_ping=True)


def run(db_url: str) -> dict:
    engine = _engine(db_url)
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select e.id,(e.metrics->'fdr'->>'as_of')::timestamptz decision_as_of,
                   (e.metrics->>'test_week')::date test_week
            from public.oracle_v6_experiments e
            where e.model_family='COUNT_NULL_MODEL'
              and e.model_version='FORMAL_COUNT_NULL_V1'
              and e.invalidated_at is null
              and e.metrics ? 'fdr'
            order by e.created_at desc,e.id desc limit 1
        """)).mappings().one_or_none()
        if not exp or exp["decision_as_of"] is None:
            raise RuntimeError("latest scientific decision unavailable")
        experiment_id = int(exp["id"])
        decision_as_of = exp["decision_as_of"]
        test_week = exp["test_week"]

        candidates = conn.execute(text("""
            select target_node,status,independent_source_count,validation_method,validation_stats
            from public.oracle_v6_graph_edges
            where evidence_cutoff_at=:decision_as_of
              and mechanism='CONSTRAINED_BY'
              and target_node like 'BOTTLENECK:%'
              and status in ('SUPPORTED_DESCRIPTIVE','SUPPORTED_PREDICTIVE','SUPPORTED_CAUSAL')
              and independent_source_count>=:min_groups
            order by target_node
        """), {"decision_as_of": decision_as_of, "min_groups": MIN_INDEPENDENT_GROUPS}).mappings().all()

        calibration_outcomes = int(conn.execute(text("""
            select count(*)
            from public.oracle_v6_bottleneck_forecasts
            where realized_outcome is not null
              and realized_at is not null
              and model_version is not null
        """)).scalar_one())

        calibrated = calibration_outcomes >= MIN_CALIBRATION_OUTCOMES
        # V1 deliberately does not synthesize a probability from source counts.
        # Even supported candidates remain forecast-ineligible until the
        # historical calibration sample is large enough and a forecast model is
        # explicitly fitted/validated in a later stage.
        forecast_rows_written = 0
        if not candidates:
            state = "NO_FORECAST_INSUFFICIENT_INDEPENDENT_EVIDENCE"
        elif not calibrated:
            state = "NO_FORECAST_UNCALIBRATED"
        else:
            state = "NO_FORECAST_MODEL_NOT_YET_VALIDATED"

        summary = {
            "model_version": MODEL_VERSION,
            "state": state,
            "candidate_count": len(candidates),
            "calibration_outcomes": calibration_outcomes,
            "minimum_calibration_outcomes": MIN_CALIBRATION_OUTCOMES,
            "minimum_independent_groups": MIN_INDEPENDENT_GROUPS,
            "forecast_rows_written": forecast_rows_written,
            "test_week": test_week.isoformat() if test_week else None,
            "decision_as_of": decision_as_of.isoformat(),
            "probability_synthesized": False,
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{bottleneck_gate}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {"ok": True, "experiment_id": experiment_id, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
