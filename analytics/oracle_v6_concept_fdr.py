#!/usr/bin/env python3
"""ORACLE V6 BH-FDR for canonical structural concepts."""
from __future__ import annotations

import json
import os
from typing import Sequence

from sqlalchemy import create_engine, text

from oracle_v6_scientific_core import benjamini_hochberg

MODEL_VERSION = "FORMAL_CONCEPT_NULL_V1"
MODEL_FAMILY = "STRUCTURAL_CONCEPT_NULL"
METHOD = "BENJAMINI_HOCHBERG"
DEFAULT_ALPHA = 0.05


def _engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url, pool_pre_ping=True)


def _adjusted(p_values: Sequence[float]) -> list[float]:
    n = len(p_values)
    if n == 0:
        return []
    order = sorted(range(n), key=lambda i: p_values[i])
    out = [1.0] * n
    running = 1.0
    for pos in range(n - 1, -1, -1):
        i = order[pos]
        rank = pos + 1
        running = min(running, min(1.0, p_values[i] * n / rank))
        out[i] = running
    return out


def run(db_url: str, alpha: float = DEFAULT_ALPHA) -> dict:
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0,1)")
    engine = _engine(db_url)
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select id,(metrics->>'decision_as_of')::timestamptz as decision_as_of,
                   (metrics->>'test_week')::date as test_week
            from public.oracle_v6_experiments
            where model_family=:family and model_version=:version and invalidated_at is null
            order by created_at desc,id desc limit 1
        """), {"family":MODEL_FAMILY,"version":MODEL_VERSION}).mappings().one_or_none()
        if not exp or exp["decision_as_of"] is None:
            raise RuntimeError("formal concept-null experiment unavailable")
        experiment_id = int(exp["id"])
        decision_as_of = exp["decision_as_of"]
        test_week = exp["test_week"]

        rows = conn.execute(text("""
            select signal_key,p_value
            from public.oracle_v6_signal_null_models
            where model_version=:version and as_of=:as_of
              and coalesce((diagnostics->>'formal_p_value')::boolean,false)=true
            order by signal_key
        """), {"version":MODEL_VERSION,"as_of":decision_as_of}).mappings().all()
        if not rows:
            raise RuntimeError("formal concept p-value family empty")
        pvals = [float(r["p_value"]) for r in rows]
        selected = benjamini_hochberg(pvals, alpha=alpha)
        adjusted = _adjusted(pvals)

        conn.execute(text("""
            delete from public.oracle_v6_multiple_testing
            where experiment_id=:exp and as_of=:as_of and method=:method
        """), {"exp":experiment_id,"as_of":decision_as_of,"method":METHOD})
        payload = [{
            "experiment_id":experiment_id,
            "hypothesis_key":str(r["signal_key"]),
            "raw_p_value":pvals[i],
            "adjusted_p_value":adjusted[i],
            "method":METHOD,
            "selected":bool(selected[i]),
            "as_of":decision_as_of,
            "fdr_alpha":alpha,
            "family_size":len(rows),
        } for i,r in enumerate(rows)]
        conn.execute(text("""
            insert into public.oracle_v6_multiple_testing
              (experiment_id,hypothesis_key,raw_p_value,adjusted_p_value,method,selected,
               as_of,fdr_alpha,family_size)
            values
              (:experiment_id,:hypothesis_key,:raw_p_value,:adjusted_p_value,:method,:selected,
               :as_of,:fdr_alpha,:family_size)
        """), payload)

        summary = {
            "method":METHOD,"alpha":alpha,"family_size":len(rows),
            "selected_count":sum(selected),"as_of":decision_as_of.isoformat(),
            "test_week":test_week.isoformat() if test_week else None,
            "formal_null_model_version":MODEL_VERSION,
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{fdr}',cast(:summary as jsonb),true)
            where id=:id
        """), {"summary":json.dumps(summary,sort_keys=True),"id":experiment_id})

    return {"ok":True,"experiment_id":experiment_id,**summary}


def main() -> None:
    alpha = float(os.environ.get("ORACLE_V6_FDR_ALPHA",str(DEFAULT_ALPHA)))
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", ""),alpha),sort_keys=True))


if __name__ == "__main__":
    main()
