#!/usr/bin/env python3
"""ORACLE V6 Discovery production FDR gate.

Consumes only formal null-model p-values, applies the canonical
Benjamini-Hochberg selector, and persists the entire hypothesis family before
any downstream trend can be inserted.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Sequence

from sqlalchemy import create_engine, text

from oracle_v6_scientific_core import benjamini_hochberg

METHOD = "BENJAMINI_HOCHBERG"
DEFAULT_ALPHA = 0.05
FORMAL_MODEL_VERSION = "FORMAL_COUNT_NULL_V1"


@dataclass(frozen=True)
class FDRResult:
    experiment_id: int
    as_of: datetime
    family_size: int
    alpha: float
    selected_count: int


def _bh_adjusted_p_values(p_values: Sequence[float]) -> list[float]:
    n = len(p_values)
    if n == 0:
        return []
    for p in p_values:
        if not 0.0 <= p <= 1.0:
            raise ValueError("p-values must be in [0,1]")
    ordered = sorted(enumerate(p_values), key=lambda x: x[1], reverse=True)
    adjusted = [1.0] * n
    running = 1.0
    for reverse_rank, (idx, p) in enumerate(ordered, start=1):
        rank = n - reverse_rank + 1
        candidate = min(1.0, p * n / rank)
        running = min(running, candidate)
        adjusted[idx] = running
    return adjusted


def run_fdr(db_url: str, alpha: float = DEFAULT_ALPHA) -> FDRResult:
    if not db_url.startswith(("postgres://", "postgresql://")):
        raise ValueError("db_url must be a PostgreSQL connection URL")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0,1)")

    engine_url = db_url
    if db_url.startswith("postgres://"):
        engine_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        engine_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]

    engine = create_engine(engine_url, pool_pre_ping=True)
    with engine.begin() as conn:
        as_of = conn.execute(text("""
            select max(as_of)
            from public.oracle_v6_signal_null_models
            where p_value is not null
              and model_version = :version
              and coalesce((diagnostics->>'formal_p_value')::boolean,false)=true
        """), {"version": FORMAL_MODEL_VERSION}).scalar_one_or_none()
        if as_of is None:
            raise RuntimeError("No formal null-model p-values available")

        rows = conn.execute(text("""
            select signal_key, p_value
            from public.oracle_v6_signal_null_models
            where as_of = :as_of
              and p_value is not null
              and model_version = :version
              and coalesce((diagnostics->>'formal_p_value')::boolean,false)=true
            order by signal_key
        """), {"as_of": as_of, "version": FORMAL_MODEL_VERSION}).mappings().all()
        if not rows:
            raise RuntimeError("Latest formal null-model family is empty")

        experiment_id = conn.execute(text("""
            select id
            from public.oracle_v6_experiments
            where model_family = 'COUNT_NULL_MODEL'
              and model_version = :version
              and invalidated_at is null
            order by created_at desc, id desc
            limit 1
        """), {"version": FORMAL_MODEL_VERSION}).scalar_one_or_none()
        if experiment_id is None:
            raise RuntimeError("No formal COUNT_NULL_MODEL experiment registered")

        p_values = [float(r["p_value"]) for r in rows]
        selected = benjamini_hochberg(p_values, alpha=alpha)
        adjusted = _bh_adjusted_p_values(p_values)
        family_size = len(rows)

        conn.execute(text("""
            delete from public.oracle_v6_multiple_testing
            where experiment_id = :experiment_id
              and as_of = :as_of
              and method = :method
        """), {"experiment_id": experiment_id, "as_of": as_of, "method": METHOD})

        payload = [{
            "experiment_id": experiment_id,
            "hypothesis_key": str(row["signal_key"]),
            "raw_p_value": p_values[i],
            "adjusted_p_value": adjusted[i],
            "method": METHOD,
            "selected": bool(selected[i]),
            "as_of": as_of,
            "fdr_alpha": alpha,
            "family_size": family_size,
        } for i, row in enumerate(rows)]

        conn.execute(text("""
            insert into public.oracle_v6_multiple_testing
              (experiment_id, hypothesis_key, raw_p_value, adjusted_p_value,
               method, selected, as_of, fdr_alpha, family_size)
            values
              (:experiment_id, :hypothesis_key, :raw_p_value, :adjusted_p_value,
               :method, :selected, :as_of, :fdr_alpha, :family_size)
        """), payload)

        selected_count = sum(selected)
        summary = {
            "method": METHOD,
            "formal_null_model_version": FORMAL_MODEL_VERSION,
            "as_of": as_of.isoformat(),
            "alpha": alpha,
            "family_size": family_size,
            "selected_count": selected_count,
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics = jsonb_set(coalesce(metrics, '{}'::jsonb), '{fdr}', cast(:summary as jsonb), true)
            where id = :experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return FDRResult(int(experiment_id), as_of, family_size, alpha, selected_count)


def main() -> None:
    db_url = os.environ.get("ORACLE_SUPABASE_DB_URL", "")
    alpha = float(os.environ.get("ORACLE_V6_FDR_ALPHA", str(DEFAULT_ALPHA)))
    result = run_fdr(db_url, alpha)
    print(json.dumps({
        "ok": True,
        "experiment_id": result.experiment_id,
        "as_of": result.as_of.isoformat(),
        "family_size": result.family_size,
        "alpha": result.alpha,
        "selected_count": result.selected_count,
        "formal_null_model_version": FORMAL_MODEL_VERSION,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
