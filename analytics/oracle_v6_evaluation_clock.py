#!/usr/bin/env python3
"""ORACLE V6 evaluation clock.

Separates immutable signal detection time from the time of a live investment
evaluation. Each GitHub run gets exactly one evaluation_as_of timestamp; all
later economic/market layers can use that timestamp without rewriting the
original signal_available_at.
"""
from __future__ import annotations

import json
import os
from sqlalchemy import create_engine, text

MODEL_VERSION = "EVALUATION_CLOCK_V1"


def _engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url, pool_pre_ping=True)


def run(db_url: str) -> dict:
    run_id = os.environ.get("GITHUB_RUN_ID") or os.environ.get("ORACLE_EVALUATION_RUN_ID")
    if not run_id:
        raise RuntimeError("GITHUB_RUN_ID or ORACLE_EVALUATION_RUN_ID required")

    engine = _engine(db_url)
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select id,(metrics->>'decision_as_of')::timestamptz signal_available_at
            from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL'
              and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null
              and metrics ? 'decision_as_of'
            order by created_at desc,id desc limit 1
        """)).mappings().one_or_none()
        if not exp or exp["signal_available_at"] is None:
            raise RuntimeError("latest formal Discovery experiment unavailable")

        row = conn.execute(text("""
            insert into public.oracle_v6_evaluation_runs
              (experiment_id,external_run_id,signal_available_at,evaluation_as_of,metadata)
            values
              (:experiment_id,:external_run_id,:signal_available_at,clock_timestamp(),
               jsonb_build_object('model_version',cast(:model_version as text),'source','github_actions'))
            on conflict (external_run_id) do update
              set external_run_id=excluded.external_run_id
            returning id,experiment_id,external_run_id,signal_available_at,evaluation_as_of
        """), {
            "experiment_id": int(exp["id"]),
            "external_run_id": str(run_id),
            "signal_available_at": exp["signal_available_at"],
            "model_version": MODEL_VERSION,
        }).mappings().one()

        summary = {
            "model_version": MODEL_VERSION,
            "evaluation_run_id": int(row["id"]),
            "external_run_id": str(row["external_run_id"]),
            "signal_available_at": row["signal_available_at"].isoformat(),
            "evaluation_as_of": row["evaluation_as_of"].isoformat(),
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{latest_evaluation_clock}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": int(row["experiment_id"])})

    return {"ok": True, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
