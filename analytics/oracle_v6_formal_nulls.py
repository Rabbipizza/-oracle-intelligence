#!/usr/bin/env python3
"""ORACLE V6 formal count-null worker.

Reconstructs a complete weekly exposure grid, fits the null on a strictly
pre-decision rolling window, selects Poisson vs Negative Binomial by empirical
dispersion, and writes exact upper-tail p-values for downstream BH-FDR.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt

from scipy.stats import nbinom, poisson
from sqlalchemy import create_engine, text

MODEL_VERSION = "FORMAL_COUNT_NULL_V1"
WINDOW_WEEKS = 104
MIN_TRAIN_WEEKS = 26
OVERDISPERSION_RATIO = 1.25


@dataclass(frozen=True)
class Fit:
    family: str
    mean: float
    variance: float
    dispersion: float
    p_value: float
    z_score: float


def _fit_count_null(train: list[int], observed: int) -> Fit:
    if len(train) < MIN_TRAIN_WEEKS:
        raise ValueError("insufficient training weeks")
    mean = sum(train) / len(train)
    variance = sum((x - mean) ** 2 for x in train) / max(1, len(train) - 1)

    # A zero historical mean means no finite fitted count model can explain a
    # positive first observation. Use a conservative tiny Poisson rate derived
    # from one pseudo-event over the entire training exposure rather than p=0.
    if mean <= 0.0:
        lam = 1.0 / len(train)
        p = float(poisson.sf(observed - 1, lam))
        z = (observed - lam) / sqrt(lam)
        return Fit("POISSON_ZERO_HISTORY_REGULARIZED", lam, 0.0, 1.0, p, z)

    ratio = variance / mean if mean > 0 else 1.0
    if variance > mean and ratio >= OVERDISPERSION_RATIO:
        # Method-of-moments NB2: Var(Y)=mu+mu^2/r.
        r = (mean * mean) / max(variance - mean, 1e-12)
        prob = r / (r + mean)
        p = float(nbinom.sf(observed - 1, r, prob))
        z = (observed - mean) / sqrt(variance)
        return Fit("NEGATIVE_BINOMIAL_MOMENTS", mean, variance, ratio, p, z)

    p = float(poisson.sf(observed - 1, mean))
    z = (observed - mean) / sqrt(mean)
    return Fit("POISSON_ROLLING", mean, variance, ratio, p, z)


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
        as_of = conn.execute(text("select max(week_start) from public.oracle_v4_term_history_weekly")).scalar_one()
        if as_of is None:
            raise RuntimeError("term history empty")

        train_start = as_of - timedelta(weeks=WINDOW_WEEKS)
        rows = conn.execute(text("""
            select d.term_id, d.term_key, h.week_start, h.event_count
            from public.oracle_v4_term_dictionary d
            join public.oracle_v4_term_history_weekly h on h.term_id=d.term_id
            where h.week_start between :train_start and :as_of
              and exists (
                select 1 from public.oracle_v4_term_history_weekly z
                where z.term_id=d.term_id and z.week_start=:as_of and z.event_count>0
              )
            order by d.term_id,h.week_start
        """), {"train_start": train_start, "as_of": as_of}).mappings().all()

        by_term: dict[int, dict] = {}
        for r in rows:
            rec = by_term.setdefault(int(r["term_id"]), {"key": str(r["term_key"]), "counts": {}})
            rec["counts"][r["week_start"]] = int(r["event_count"])

        payload = []
        family_counts: dict[str, int] = {}
        for rec in by_term.values():
            observed = int(rec["counts"].get(as_of, 0))
            if observed <= 0:
                continue
            train = []
            for k in range(WINDOW_WEEKS, 0, -1):
                week = as_of - timedelta(weeks=k)
                train.append(int(rec["counts"].get(week, 0)))
            fit = _fit_count_null(train, observed)
            family_counts[fit.family] = family_counts.get(fit.family, 0) + 1
            payload.append({
                "signal_key": rec["key"],
                "as_of": as_of,
                "null_family": fit.family,
                "observed_value": observed,
                "expected_value": fit.mean,
                "dispersion": fit.dispersion,
                "surprise_z": fit.z_score,
                "p_value": max(0.0, min(1.0, fit.p_value)),
                "model_version": MODEL_VERSION,
                "training_window": json.dumps({
                    "weeks": WINDOW_WEEKS,
                    "train_start": train_start.isoformat(),
                    "train_end": (as_of - timedelta(weeks=1)).isoformat(),
                    "test_week": as_of.isoformat(),
                    "zero_filled_missing_weeks": True,
                }),
                "diagnostics": json.dumps({
                    "formal_p_value": True,
                    "temporary": False,
                    "variance": fit.variance,
                    "dispersion_ratio": fit.dispersion,
                    "overdispersion_threshold": OVERDISPERSION_RATIO,
                    "seasonality": "not_fitted_v1_weekly_sparse_counts",
                    "strict_pre_test_training": True,
                }),
            })

        if not payload:
            raise RuntimeError("no formal null models produced")

        # Keep legacy bootstrap rows for audit, but ensure FDR can target only
        # this formal model version/family set.
        conn.execute(text("""
            delete from public.oracle_v6_signal_null_models
            where as_of=:as_of and model_version=:model_version
        """), {"as_of": as_of, "model_version": MODEL_VERSION})
        conn.execute(text("""
            insert into public.oracle_v6_signal_null_models
              (signal_key,as_of,null_family,observed_value,expected_value,dispersion,
               surprise_z,p_value,model_version,training_window,diagnostics)
            values
              (:signal_key,:as_of,:null_family,:observed_value,:expected_value,:dispersion,
               :surprise_z,:p_value,:model_version,cast(:training_window as jsonb),cast(:diagnostics as jsonb))
        """), payload)

        experiment_key = f"v6_formal_count_null_{as_of.isoformat()}"
        specification = json.dumps({
            "window_weeks": WINDOW_WEEKS,
            "minimum_train_weeks": MIN_TRAIN_WEEKS,
            "overdispersion_ratio": OVERDISPERSION_RATIO,
            "zero_fill_sparse_history": True,
            "strict_pre_test_training": True,
            "families": ["POISSON_ROLLING", "NEGATIVE_BINOMIAL_MOMENTS", "POISSON_ZERO_HISTORY_REGULARIZED"],
        }, sort_keys=True)
        metrics = json.dumps({"rows": len(payload), "family_counts": family_counts}, sort_keys=True)
        exp_id = conn.execute(text("""
            insert into public.oracle_v6_experiments
              (experiment_key,model_family,model_version,target_name,train_start,train_end,test_start,test_end,holdout,specification,metrics)
            values
              (:key,'COUNT_NULL_MODEL',:version,'weekly_term_count',:train_start,:train_end,:test,:test,false,cast(:spec as jsonb),cast(:metrics as jsonb))
            on conflict (experiment_key) do update
              set model_version=excluded.model_version,specification=excluded.specification,metrics=excluded.metrics
            returning id
        """), {
            "key": experiment_key, "version": MODEL_VERSION,
            "train_start": train_start, "train_end": as_of - timedelta(weeks=1),
            "test": as_of, "spec": specification, "metrics": metrics,
        }).scalar_one()

    return {"ok": True, "experiment_id": int(exp_id), "as_of": as_of.isoformat(), "rows": len(payload), "families": family_counts}


def main() -> None:
    result = run(os.environ.get("ORACLE_SUPABASE_DB_URL", ""))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
