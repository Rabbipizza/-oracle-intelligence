#!/usr/bin/env python3
"""ORACLE V6 final decision prerequisite gate.

Writes explicit NO_ACTION decisions for evidence-supported company candidates
when required calibrated layers are missing. Numeric probabilities and expected
returns remain NULL; data_gaps explain why action is blocked.
"""
from __future__ import annotations

import json
import os
from sqlalchemy import create_engine, text

MODEL_VERSION = "DECISION_PREREQUISITE_GATE_V1"
CAPTURE_MODEL = "COMPANY_CAPTURE_EVIDENCE_GATE_V1"


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
            select id,(metrics->>'decision_as_of')::timestamptz decision_as_of,
                   metrics->'market_expectations_gate'->>'state' expectation_state,
                   metrics->'bottleneck_gate'->>'state' bottleneck_state
            from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL'
              and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null
              and metrics ? 'decision_as_of'
            order by created_at desc,id desc limit 1
        """)).mappings().one_or_none()
        if not exp or exp["decision_as_of"] is None:
            raise RuntimeError("latest PIT experiment unavailable")

        experiment_id = int(exp["id"])
        cutoff = exp["decision_as_of"]
        tickers = [str(x) for x in conn.execute(text("""
            select distinct ticker
            from public.oracle_v6_company_capture
            where model_version=:capture_model and as_of=:cutoff
            order by ticker
        """), {"capture_model": CAPTURE_MODEL, "cutoff": cutoff}).scalars().all()]

        gaps = []
        if conn.execute(text("""
            select count(*) from public.oracle_v6_company_capture
            where model_version=:capture_model and as_of=:cutoff and capture_probability is not null
        """), {"capture_model": CAPTURE_MODEL, "cutoff": cutoff}).scalar_one() == 0:
            gaps.append("UNCALIBRATED_ECONOMIC_CAPTURE")

        if conn.execute(text("select count(*) from public.oracle_v6_market_expectations where as_of=:cutoff"), {"cutoff": cutoff}).scalar_one() == 0:
            gaps.append("MISSING_EXPECTATION_GAP")

        if conn.execute(text("select count(*) from public.oracle_v6_bottleneck_forecasts where as_of=:cutoff"), {"cutoff": cutoff}).scalar_one() == 0:
            gaps.append("NO_VALIDATED_BOTTLENECK_FORECAST")

        # No validated expected residual-return model exists yet.
        gaps.append("NO_OOS_INCREMENTAL_RETURN_MODEL")
        gaps = sorted(set(gaps))

        conn.execute(text("delete from public.oracle_v6_decisions where model_version=:model and as_of=:cutoff"), {
            "model": MODEL_VERSION, "cutoff": cutoff,
        })

        payload = [{
            "ticker": ticker,
            "as_of": cutoff,
            "decision": "NO_ACTION",
            "uncertainty": json.dumps({
                "probabilities_calibrated": False,
                "expected_residual_return_calibrated": False,
            }, sort_keys=True),
            "data_gaps": json.dumps(gaps),
            "invalidation_conditions": json.dumps([]),
            "model_version": MODEL_VERSION,
        } for ticker in tickers]

        if payload:
            conn.execute(text("""
                insert into public.oracle_v6_decisions
                  (ticker,as_of,decision,p_structural,p_bottleneck,p_economic_capture,
                   p_fundamentals_exceed_expectations,expected_residual_return,uncertainty,
                   invalidation_conditions,data_gaps,model_version)
                values
                  (:ticker,:as_of,:decision,null,null,null,null,null,cast(:uncertainty as jsonb),
                   cast(:invalidation_conditions as jsonb),cast(:data_gaps as jsonb),:model_version)
            """), payload)

        summary = {
            "model_version": MODEL_VERSION,
            "decision_as_of": cutoff.isoformat(),
            "candidate_tickers": len(tickers),
            "decision_rows_written": len(payload),
            "decision": "NO_ACTION",
            "data_gaps": gaps,
            "numeric_probabilities_written": 0,
            "expected_returns_written": 0,
            "state": "NO_ACTION_PREREQUISITES_INCOMPLETE",
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{decision_gate}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {"ok": True, "experiment_id": experiment_id, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
