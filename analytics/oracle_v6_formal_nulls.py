#!/usr/bin/env python3
"""ORACLE V6 formal point-in-time weekly count null worker.

Fits each observed term using ONLY the 104 preceding weeks, zero-filling
missing weeks. Model selection is statistical rather than threshold-only:
- sparse histories -> Gamma-Poisson posterior predictive,
- formal Poisson dispersion test rejects -> Negative Binomial,
- otherwise -> Poisson MLE.

The statistical test week is distinct from decision_as_of. decision_as_of is
reconstructed from the actual availability of the retro occurrences and their
source documents, so a weekly bucket is never backdated to its week_start.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from scipy.stats import chi2, nbinom, poisson
from sqlalchemy import create_engine, text

MODEL_VERSION = "FORMAL_COUNT_NULL_V1"
WINDOW_WEEKS = 104
MIN_TRAIN_WEEKS = 52
SPARSE_TOTAL_THRESHOLD = 8
DISPERSION_ALPHA = 0.05
PRIOR_SHAPE = 0.5
PRIOR_RATE = 1.0


@dataclass(frozen=True)
class Fit:
    family: str
    expected: float
    variance: float
    dispersion: float
    p_value: float
    z_score: float
    diagnostics: dict


def _sample_variance(values: list[int], mean: float) -> float:
    if len(values) < 2:
        return 0.0
    return sum((x - mean) ** 2 for x in values) / (len(values) - 1)


def _fit_count_null(train: list[int], observed: int) -> Fit:
    n = len(train)
    if n < MIN_TRAIN_WEEKS:
        raise ValueError(f"insufficient training weeks: {n}")
    if observed < 0 or any(x < 0 for x in train):
        raise ValueError("counts must be non-negative")

    total = int(sum(train))
    mean = total / n
    variance = _sample_variance(train, mean)
    zero_fraction = sum(1 for x in train if x == 0) / n

    if mean > 0:
        dispersion_index = (n - 1) * variance / mean
        dispersion_test_p = float(chi2.sf(dispersion_index, n - 1))
    else:
        dispersion_index = 0.0
        dispersion_test_p = 1.0

    if total < SPARSE_TOTAL_THRESHOLD:
        a = PRIOR_SHAPE + total
        b = PRIOR_RATE + n
        expected = a / b
        predictive_variance = expected + a / (b * b)
        prob = b / (b + 1.0)
        p_value = float(nbinom.sf(observed - 1, a, prob)) if observed > 0 else 1.0
        family = "GAMMA_POISSON_SPARSE_104W"
        fitted_dispersion = predictive_variance / max(expected, 1e-12)
        extra = {"posterior_shape": a, "posterior_rate": b}
    elif variance > mean and dispersion_test_p < DISPERSION_ALPHA:
        alpha = max((variance - mean) / max(mean * mean, 1e-12), 1e-10)
        size = 1.0 / alpha
        prob = size / (size + mean)
        expected = mean
        predictive_variance = mean + alpha * mean * mean
        p_value = float(nbinom.sf(observed - 1, size, prob)) if observed > 0 else 1.0
        family = "NEGATIVE_BINOMIAL_ROLLING_104W"
        fitted_dispersion = predictive_variance / max(expected, 1e-12)
        extra = {"nb_alpha": alpha, "nb_size": size, "nb_probability": prob}
    else:
        expected = mean
        predictive_variance = max(mean, 1e-12)
        p_value = float(poisson.sf(observed - 1, mean)) if observed > 0 else 1.0
        family = "POISSON_ROLLING_104W"
        fitted_dispersion = 1.0
        extra = {}

    p_value = min(1.0, max(1e-300, p_value))
    z = (observed - expected) / math.sqrt(max(predictive_variance, 1e-12))
    diagnostics = {
        "formal_p_value": True,
        "temporary": False,
        "point_in_time": True,
        "strict_pre_test_training": True,
        "training_weeks": n,
        "training_total": total,
        "training_mean": mean,
        "training_variance": variance,
        "zero_fraction": zero_fraction,
        "poisson_dispersion_index": dispersion_index,
        "poisson_dispersion_test_p": dispersion_test_p,
        "dispersion_alpha": DISPERSION_ALPHA,
        "sparse_total_threshold": SPARSE_TOTAL_THRESHOLD,
        "model_selection_rule": "sparse_gamma_poisson_else_formal_dispersion_test_nb_else_poisson",
        **extra,
    }
    return Fit(family, float(expected), float(predictive_variance), float(fitted_dispersion), p_value, float(z), diagnostics)


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
        test_week = conn.execute(text("select max(week_start) from public.oracle_v4_term_history_weekly")).scalar_one()
        if test_week is None:
            raise RuntimeError("term history empty")
        if isinstance(test_week, datetime):
            test_week = test_week.date()

        last_event_date = conn.execute(text("""
            select max(last_event_date)
            from public.oracle_v4_term_history_weekly
            where week_start=:test_week
        """), {"test_week": test_week}).scalar_one()
        if last_event_date is None:
            raise RuntimeError("test-week last_event_date unavailable")

        # Conservative KNOWN availability: an occurrence can only be used once
        # both the source document has been fetched and the retrospective term
        # occurrence has actually been materialized.
        decision_as_of = conn.execute(text("""
            select max(greatest(o.created_at,d.fetched_at))
            from public.oracle_v4_retro_term_occurrences o
            join public.oracle_raw_documents d on d.id=o.document_id
            where o.event_date between :test_week and :last_event_date
        """), {"test_week": test_week, "last_event_date": last_event_date}).scalar_one()
        if decision_as_of is None:
            raise RuntimeError("cannot establish KNOWN decision_as_of for test week")

        train_start = test_week - timedelta(weeks=WINDOW_WEEKS)
        train_end = test_week - timedelta(weeks=1)

        candidates = conn.execute(text("""
            select d.term_id,d.term_key,h.event_count
            from public.oracle_v4_term_history_weekly h
            join public.oracle_v4_term_dictionary d on d.term_id=h.term_id
            where h.week_start=:test_week and h.event_count>0
            order by d.term_id
        """), {"test_week": test_week}).mappings().all()
        if not candidates:
            raise RuntimeError(f"no candidate terms for {test_week}")

        history_rows = conn.execute(text("""
            with c as (
              select term_id
              from public.oracle_v4_term_history_weekly
              where week_start=:test_week and event_count>0
            )
            select h.term_id,h.week_start,h.event_count
            from public.oracle_v4_term_history_weekly h
            join c using(term_id)
            where h.week_start>=:train_start and h.week_start<:test_week
            order by h.term_id,h.week_start
        """), {"test_week": test_week, "train_start": train_start}).mappings().all()

        by_term: dict[int, dict[date, int]] = defaultdict(dict)
        for r in history_rows:
            by_term[int(r["term_id"])][r["week_start"]] = int(r["event_count"])
        weeks = [train_start + timedelta(weeks=i) for i in range(WINDOW_WEEKS)]

        payload = []
        family_counts: dict[str, int] = defaultdict(int)
        for c in candidates:
            tid = int(c["term_id"])
            train = [by_term[tid].get(w, 0) for w in weeks]
            observed = int(c["event_count"])
            fit = _fit_count_null(train, observed)
            family_counts[fit.family] += 1
            diagnostics = {
                **fit.diagnostics,
                "availability_quality": "KNOWN",
                "decision_as_of": decision_as_of.isoformat(),
                "test_week": test_week.isoformat(),
                "test_last_event_date": last_event_date.isoformat(),
                "availability_rule": "max(greatest(retro_occurrence.created_at, raw_document.fetched_at))",
            }
            payload.append({
                "signal_key": str(c["term_key"]),
                "as_of": decision_as_of,
                "null_family": fit.family,
                "observed_value": float(observed),
                "expected_value": fit.expected,
                "dispersion": fit.dispersion,
                "surprise_z": fit.z_score,
                "p_value": fit.p_value,
                "model_version": MODEL_VERSION,
                "training_window": json.dumps({
                    "weeks": WINDOW_WEEKS,
                    "train_start": train_start.isoformat(),
                    "train_end": train_end.isoformat(),
                    "test_week": test_week.isoformat(),
                    "test_last_event_date": last_event_date.isoformat(),
                    "decision_as_of": decision_as_of.isoformat(),
                    "zero_filled_missing_weeks": True,
                    "excludes_test_week": True,
                }, sort_keys=True),
                "diagnostics": json.dumps(diagnostics, sort_keys=True),
            })

        experiment_key = f"v6_formal_count_null_{test_week.isoformat()}"
        specification = json.dumps({
            "window_weeks": WINDOW_WEEKS,
            "minimum_train_weeks": MIN_TRAIN_WEEKS,
            "strict_pre_test_training": True,
            "zero_fill_sparse_history": True,
            "sparse_model": "Gamma-Poisson posterior predictive",
            "overdispersion_test": "Pearson dispersion index, chi-square upper tail",
            "dispersion_alpha": DISPERSION_ALPHA,
            "test_week": test_week.isoformat(),
            "decision_as_of_rule": "KNOWN source/extraction availability",
            "families": ["GAMMA_POISSON_SPARSE_104W", "NEGATIVE_BINOMIAL_ROLLING_104W", "POISSON_ROLLING_104W"],
        }, sort_keys=True)
        experiment_id = conn.execute(text("""
            insert into public.oracle_v6_experiments
              (experiment_key,model_family,model_version,target_name,train_start,train_end,test_start,test_end,holdout,specification,metrics)
            values
              (:key,'COUNT_NULL_MODEL',:version,'weekly_term_event_count',:train_start,:train_end,:test,:test,false,cast(:spec as jsonb),'{}'::jsonb)
            on conflict (experiment_key) do update set
              model_family=excluded.model_family,model_version=excluded.model_version,
              target_name=excluded.target_name,train_start=excluded.train_start,
              train_end=excluded.train_end,test_start=excluded.test_start,test_end=excluded.test_end,
              specification=excluded.specification,invalidated_at=null,invalidation_reason=null
            returning id
        """), {"key": experiment_key, "version": MODEL_VERSION, "train_start": train_start, "train_end": train_end, "test": test_week, "spec": specification}).scalar_one()

        # Replace any prior materialization of this same test week, including
        # the old incorrectly backdated as_of=week_start rows.
        conn.execute(text("""
            delete from public.oracle_v6_signal_null_models
            where model_version=:version
              and training_window->>'test_week'=:test_week
        """), {"version": MODEL_VERSION, "test_week": test_week.isoformat()})

        insert_sql = text("""
            insert into public.oracle_v6_signal_null_models
              (signal_key,as_of,null_family,observed_value,expected_value,dispersion,surprise_z,p_value,model_version,training_window,diagnostics)
            values
              (:signal_key,:as_of,:null_family,:observed_value,:expected_value,:dispersion,:surprise_z,:p_value,:model_version,cast(:training_window as jsonb),cast(:diagnostics as jsonb))
        """)
        for i in range(0, len(payload), 500):
            conn.execute(insert_sql, payload[i:i+500])

        pvals = sorted(float(x["p_value"]) for x in payload)
        metrics = json.dumps({
            "rows": len(payload),
            "family_counts": dict(family_counts),
            "min_p_value": pvals[0],
            "median_p_value": pvals[len(pvals)//2],
            "formal_p_value": True,
            "temporary": False,
            "test_week": test_week.isoformat(),
            "test_last_event_date": last_event_date.isoformat(),
            "decision_as_of": decision_as_of.isoformat(),
            "availability_quality": "KNOWN",
        }, sort_keys=True)
        conn.execute(text("update public.oracle_v6_experiments set metrics=cast(:metrics as jsonb) where id=:id"), {"metrics": metrics, "id": experiment_id})

    return {
        "ok": True,
        "experiment_id": int(experiment_id),
        "test_week": test_week.isoformat(),
        "decision_as_of": decision_as_of.isoformat(),
        "rows": len(payload),
        "families": dict(family_counts),
    }


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
