#!/usr/bin/env python3
"""ORACLE V6 market-expectations prerequisite gate.

A reverse DCF must not be synthesized without PIT free-cash-flow and capex
inputs. This worker audits current company-capture candidates and records a
NO_EXPECTATION_MODEL state when required inputs are unavailable. It writes no
oracle_v6_market_expectations rows in that case.
"""
from __future__ import annotations

import json
import os
from sqlalchemy import create_engine, text

MODEL_VERSION = "MARKET_EXPECTATIONS_GATE_V1"
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
            select id,(metrics->>'decision_as_of')::timestamptz decision_as_of
            from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL'
              and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null
              and metrics ? 'decision_as_of'
            order by created_at desc,id desc limit 1
        """)).mappings().one_or_none()
        if not exp or exp["decision_as_of"] is None:
            raise RuntimeError("latest PIT Discovery experiment unavailable")

        experiment_id = int(exp["id"])
        cutoff = exp["decision_as_of"]

        candidates = conn.execute(text("""
            select count(*) n,count(distinct ticker) tickers
            from public.oracle_v6_company_capture
            where model_version=:capture_model and as_of=:cutoff
        """), {"capture_model": CAPTURE_MODEL, "cutoff": cutoff}).mappings().one()

        # Current schema audit: require an actual PIT source column/table for
        # free cash flow / operating cash flow and capex. Do not infer these
        # from net income, revenue, or narrative evidence.
        required_input_columns = conn.execute(text("""
            select table_name,column_name
            from information_schema.columns
            where table_schema='public'
              and (
                lower(column_name) like '%free%cash%'
                or lower(column_name) like '%fcf%'
                or lower(column_name) like '%operating%cash%'
                or lower(column_name) like '%cash_flow%'
                or lower(column_name) like '%capital_expenditure%'
                or lower(column_name)='capex'
              )
              and table_name not in ('oracle_v6_company_capture','oracle_v6_market_expectations')
            order by table_name,column_name
        """)).mappings().all()

        # Conservative rule: presence of similarly named score fields does not
        # qualify. We need raw/derived financial observations suitable for PIT.
        usable_inputs = [dict(r) for r in required_input_columns if r["table_name"] not in {"oracle_v4_opportunity_map"}]

        if usable_inputs:
            state = "INPUT_SCHEMA_PRESENT_REQUIRES_MODEL_IMPLEMENTATION"
        else:
            state = "NO_EXPECTATION_MODEL_MISSING_FCF_INPUTS"

        # Until a calibrated reverse-DCF model exists, no rows are allowed for
        # this gate's model version.
        conn.execute(text("delete from public.oracle_v6_market_expectations where model_version=:model"), {"model": MODEL_VERSION})

        summary = {
            "model_version": MODEL_VERSION,
            "decision_as_of": cutoff.isoformat(),
            "company_capture_candidate_pairs": int(candidates["n"] or 0),
            "company_capture_tickers": int(candidates["tickers"] or 0),
            "usable_fcf_capex_input_columns": usable_inputs,
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
