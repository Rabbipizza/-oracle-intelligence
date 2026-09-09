#!/usr/bin/env python3
"""P0-7 sequential/temporal multiple-testing control.

This stage runs *before* BH. It allocates a pre-registered run-level FDR alpha
using a summable online alpha-spending schedule:
    gamma_t = 6 / (pi^2 * t^2),  sum_t gamma_t = 1
    alpha_t = target_alpha * gamma_t

Therefore cumulative allocated alpha is bounded by target_alpha over an
unbounded sequence of distinct test families. Re-runs of an identical formal
p-value family reuse the same family_fingerprint and spend no additional alpha.

This is intentionally conservative. It is an online alpha-spending procedure,
not post-hoc threshold tuning, and it complements (rather than replaces) BH
within each run.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from sqlalchemy import create_engine, text

CONFIG_VERSION = "ONLINE_ALPHA_SPENDING_BH_V1"
FORMAL_MODEL_VERSION = "FORMAL_COUNT_NULL_V1"


def engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("PostgreSQL URL required")
    return create_engine(db_url, pool_pre_ping=True)


def run(db_url: str) -> dict:
    with engine(db_url).begin() as conn:
        exp = conn.execute(text("""
          select id,(metrics->>'test_week')::date test_week,
                 (metrics->'fdr'->>'as_of')::timestamptz prior_fdr_as_of
          from public.oracle_v6_experiments
          where model_family='COUNT_NULL_MODEL' and model_version=:v and invalidated_at is null
          order by created_at desc,id desc limit 1
        """), {"v": FORMAL_MODEL_VERSION}).mappings().one()
        experiment_id = int(exp["id"])
        test_week = exp["test_week"]

        as_of = conn.execute(text("""
          select max(as_of) from public.oracle_v6_signal_null_models
          where model_version=:v and p_value is not null
            and coalesce((diagnostics->>'formal_p_value')::boolean,false)=true
        """), {"v": FORMAL_MODEL_VERSION}).scalar_one()

        rows = conn.execute(text("""
          select signal_key,p_value from public.oracle_v6_signal_null_models
          where as_of=:a and model_version=:v and p_value is not null
            and coalesce((diagnostics->>'formal_p_value')::boolean,false)=true
          order by signal_key
        """), {"a": as_of, "v": FORMAL_MODEL_VERSION}).mappings().all()
        if not rows:
            raise RuntimeError("formal p-value family is empty")

        material = "\n".join(f"{r['signal_key']}\t{float(r['p_value']):.17g}" for r in rows)
        fingerprint = hashlib.sha256(material.encode()).hexdigest()

        existing = conn.execute(text("""
          select * from public.oracle_v6_sequential_run_budget where family_fingerprint=:f
        """), {"f": fingerprint}).mappings().one_or_none()

        if existing:
            allocated = float(existing["allocated_alpha"])
            sequence_index = int(existing["sequence_index"])
            cumulative = float(existing["cumulative_allocated_alpha"])
            gamma = float(existing["gamma_weight"])
            reused = True
        else:
            cfg = conn.execute(text("""
              select * from public.oracle_v6_sequential_fdr_config
              where config_version=:c and active=true
            """), {"c": CONFIG_VERSION}).mappings().one()
            target = float(cfg["target_alpha"])
            sequence_index = int(conn.execute(text("select coalesce(max(sequence_index),0)+1 from public.oracle_v6_sequential_run_budget")).scalar_one())
            gamma = 6.0 / (math.pi * math.pi * sequence_index * sequence_index)
            allocated = target * gamma
            prior = float(conn.execute(text("select coalesce(max(cumulative_allocated_alpha),0) from public.oracle_v6_sequential_run_budget")).scalar_one())
            cumulative = prior + allocated
            if cumulative > target + 1e-10:
                raise RuntimeError(f"sequential alpha budget overflow: {cumulative}>{target}")

            doc_count = int(conn.execute(text("""
              select count(distinct o.document_id)
              from public.oracle_v4_retro_term_occurrences o
              join public.oracle_raw_documents d on d.id=o.document_id
              where o.event_date between :w and (:w + interval '6 days')::date
                and o.created_at<=:a and d.fetched_at<=:a
            """), {"w": test_week, "a": as_of}).scalar_one())

            conn.execute(text("""
              insert into public.oracle_v6_sequential_run_budget
                (config_version,experiment_id,test_week,decision_as_of,family_fingerprint,
                 sequence_index,gamma_weight,allocated_alpha,cumulative_allocated_alpha,family_size,document_count)
              values(:c,:e,:w,:a,:f,:t,:g,:alpha,:cum,:n,:docs)
            """), {"c": CONFIG_VERSION, "e": experiment_id, "w": test_week, "a": as_of,
                       "f": fingerprint, "t": sequence_index, "g": gamma, "alpha": allocated,
                       "cum": cumulative, "n": len(rows), "docs": doc_count})
            reused = False

        summary = {
          "config_version": CONFIG_VERSION,
          "family_fingerprint": fingerprint,
          "sequence_index": sequence_index,
          "gamma_weight": gamma,
          "allocated_alpha": allocated,
          "cumulative_allocated_alpha": cumulative,
          "target_alpha": 0.05,
          "reused_existing_family_budget": reused,
          "test_week": test_week.isoformat(),
          "decision_as_of": as_of.isoformat(),
          "family_size": len(rows),
          "bounded_budget_claim": "sum(alpha_t)<=target_alpha because sum 6/(pi^2*t^2)=1",
        }
        conn.execute(text("""
          update public.oracle_v6_experiments
          set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{sequential_fdr}',cast(:s as jsonb),true)
          where id=:e
        """), {"s": json.dumps(summary, sort_keys=True), "e": experiment_id})

    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a", encoding="utf-8") as fh:
            fh.write(f"ORACLE_V6_FDR_ALPHA_ALLOCATED={allocated:.17g}\n")
    return {"ok": True, **summary}


if __name__ == "__main__":
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))
