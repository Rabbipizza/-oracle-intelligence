#!/usr/bin/env python3
"""ORACLE V6 market-expectations prerequisite gate.

The signal detection timestamp is immutable, but valuation is evaluated at the
current evaluation-run timestamp. This gate audits whether PIT FCF inputs exist
for current company-capture candidates. It still writes no reverse-DCF row until
the valuation model itself is implemented and tested.
"""
from __future__ import annotations

import json
import os
from sqlalchemy import create_engine, text

MODEL_VERSION = "MARKET_EXPECTATIONS_GATE_V1"
CAPTURE_MODEL = "COMPANY_CAPTURE_EVIDENCE_GATE_V1"
FCF_MODEL = "SEC_FCF_ANNUAL_V1"


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
    run_id = os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select id,(metrics->>'decision_as_of')::timestamptz signal_available_at
            from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL'
              and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null
            order by created_at desc,id desc limit 1
        """)).mappings().one_or_none()
        if not exp:
            raise RuntimeError("latest PIT Discovery experiment unavailable")
        experiment_id = int(exp["id"])

        if run_id:
            cutoff = conn.execute(text("""
                select evaluation_as_of from public.oracle_v6_evaluation_runs
                where experiment_id=:experiment_id and external_run_id=:run_id
            """), {"experiment_id": experiment_id, "run_id": run_id}).scalar_one_or_none()
        else:
            cutoff = None
        if cutoff is None:
            cutoff = conn.execute(text("""
                select evaluation_as_of from public.oracle_v6_evaluation_runs
                where experiment_id=:experiment_id
                order by evaluation_as_of desc,id desc limit 1
            """), {"experiment_id": experiment_id}).scalar_one_or_none()
        if cutoff is None:
            raise RuntimeError("no evaluation clock for market expectations")

        candidates = conn.execute(text("""
            select count(*) n,count(distinct ticker) tickers
            from public.oracle_v6_company_capture
            where model_version=:capture_model and as_of=:cutoff
        """), {"capture_model": CAPTURE_MODEL, "cutoff": cutoff}).mappings().one()

        fcf = conn.execute(text("""
            select count(*) snapshots,count(distinct f.ticker) tickers
            from public.oracle_v6_fcf_snapshots f
            where f.model_version=:fcf_model
              and f.as_of<=:cutoff
              and exists (
                select 1 from public.oracle_v6_company_capture c
                where c.model_version=:capture_model and c.as_of=:cutoff and c.ticker=f.ticker
              )
        """), {"fcf_model": FCF_MODEL, "capture_model": CAPTURE_MODEL, "cutoff": cutoff}).mappings().one()

        if int(fcf["tickers"] or 0) > 0:
            state = "PIT_FCF_AVAILABLE_REVERSE_DCF_MODEL_PENDING"
        else:
            state = "NO_EXPECTATION_MODEL_MISSING_PIT_FCF_INPUTS"

        conn.execute(text("delete from public.oracle_v6_market_expectations where model_version=:model and as_of=:cutoff"), {
            "model": MODEL_VERSION, "cutoff": cutoff,
        })

        summary = {
            "model_version": MODEL_VERSION,
            "signal_available_at": exp["signal_available_at"].isoformat() if exp["signal_available_at"] else None,
            "evaluation_as_of": cutoff.isoformat(),
            "company_capture_candidate_pairs": int(candidates["n"] or 0),
            "company_capture_tickers": int(candidates["tickers"] or 0),
            "pit_fcf_snapshots_available": int(fcf["snapshots"] or 0),
            "pit_fcf_tickers_available": int(fcf["tickers"] or 0),
            "reverse_dcf_rows_written": 0,
            "probabilities_written": 0,
            "proxy_substitution_allowed": False,
            "state": state,
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{market_expectations_gate}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {"ok": True, "experiment_id": experiment_id, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
