#!/usr/bin/env python3
"""ORACLE V6 formal point-in-time weekly count null model.

For every term observed in the latest completed week, fit a null using ONLY the
104 prior weeks. Missing weeks are explicit zeroes.

Model selection:
- sparse histories: Gamma-Poisson posterior predictive (proper non-zero prior),
- overdispersed histories: Negative Binomial method-of-moments,
- otherwise: Poisson MLE.

The Poisson dispersion-index test is used to decide overdispersion. All output
p-values are one-sided upper-tail probabilities and are suitable for the
production Benjamini-Hochberg family.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from scipy.stats import chi2, nbinom, poisson
from sqlalchemy import create_engine, text

MODEL_VERSION = "FORMAL_COUNT_NULL_V1"
TRAIN_WEEKS = 104
MIN_TRAIN_WEEKS = 52
SPARSE_TOTAL_THRESHOLD = 8
DISPERSION_ALPHA = 0.05
PRIOR_SHAPE = 0.5
PRIOR_RATE = 1.0


@dataclass(frozen=True)
class Fit:
    family: str
    observed: int
    expected: float
    dispersion: float
    surprise_z: float
    p_value: float
    diagnostics: dict


def _engine_url(db_url: str) -> str:
    if db_url.startswith("postgres://"):
        return "postgresql+psycopg://" + db_url[len("postgres://"):]
    if db_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + db_url[len("postgresql://"):]
    raise ValueError("ORACLE_SUPABASE_DB_URL must be a PostgreSQL URL")


def _sample_variance(values: list[int], mean: float) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    return sum((x - mean) ** 2 for x in values) / (n - 1)


def fit_count_null(history: list[int], observed: int) -> Fit:
    n = len(history)
    if n < MIN_TRAIN_WEEKS:
        raise ValueError(f"need >= {MIN_TRAIN_WEEKS} training weeks, got {n}")
    if observed < 0 or any(x < 0 for x in history):
        raise ValueError("counts must be non-negative")

    total = int(sum(history))
    mean = total / n
    variance = _sample_variance(history, mean)
    zero_fraction = sum(1 for x in history if x == 0) / n

    if mean > 0:
        dispersion_index = (n - 1) * variance / mean
        dispersion_test_p = float(chi2.sf(dispersion_index, n - 1))
    else:
        dispersion_index = 0.0
        dispersion_test_p = 1.0

    if total < SPARSE_TOTAL_THRESHOLD:
        # Gamma(a,b) prior on lambda, with b expressed as a rate.
        a = PRIOR_SHAPE + total
        b = PRIOR_RATE + n
        expected = a / b
        predictive_var = expected + a / (b * b)
        prob = b / (b + 1.0)
        p_value = float(nbinom.sf(observed - 1, a, prob)) if observed > 0 else 1.0
        family = "GAMMA_POISSON_SPARSE_104W"
        fitted_dispersion = predictive_var / max(expected, 1e-12)
        extra = {"posterior_shape": a, "posterior_rate": b}
    elif variance > mean and dispersion_test_p < DISPERSION_ALPHA:
        alpha = max((variance - mean) / max(mean * mean, 1e-12), 1e-10)
        size = 1.0 / alpha
        prob = size / (size + mean)
        expected = mean
        predictive_var = mean + alpha * mean * mean
        p_value = float(nbinom.sf(observed - 1, size, prob)) if observed > 0 else 1.0
        family = "NEGATIVE_BINOMIAL_ROLLING_104W"
        fitted_dispersion = predictive_var / max(expected, 1e-12)
        extra = {"nb_alpha": alpha, "nb_size": size, "nb_probability": prob}
    else:
        expected = mean
        predictive_var = max(mean, 1e-12)
        p_value = float(poisson.sf(observed - 1, mean)) if observed > 0 else 1.0
        family = "POISSON_ROLLING_104W"
        fitted_dispersion = 1.0
        extra = {}

    p_value = min(1.0, max(1e-300, p_value))
    surprise_z = (observed - expected) / math.sqrt(max(predictive_var, 1e-12))
    diagnostics = {
        "formal_p_value": True,
        "temporary": False,
        "point_in_time": True,
        "training_weeks": n,
        "training_total": total,
        "training_mean": mean,
        "training_variance": variance,
        "zero_fraction": zero_fraction,
        "poisson_dispersion_index": dispersion_index,
        "poisson_dispersion_test_p": dispersion_test_p,
        "model_selection_rule": "sparse_gamma_poisson_else_dispersion_test_nb_else_poisson",
        "sparse_total_threshold": SPARSE_TOTAL_THRESHOLD,
        "dispersion_alpha": DISPERSION_ALPHA,
        **extra,
    }
    return Fit(
        family=family,
        observed=observed,
        expected=float(expected),
        dispersion=float(fitted_dispersion),
        surprise_z=float(surprise_z),
        p_value=float(p_value),
        diagnostics=diagnostics,
    )


def run(db_url: str) -> dict:
    engine = create_engine(_engine_url(db_url), pool_pre_ping=True)
    with engine.begin() as conn:
        as_of = conn.execute(text("select max(week_start) from public.oracle_v4_term_history_weekly")).scalar_one()
        if as_of is None:
            raise RuntimeError("term history is empty")
        if isinstance(as_of, datetime):
            as_of = as_of.date()

        train_start = as_of - timedelta(weeks=TRAIN_WEEKS)
        train_end = as_of - timedelta(days=7)

        candidates = conn.execute(text("""
            select d.term_id, d.term_key, h.event_count
            from public.oracle_v4_term_history_weekly h
            join public.oracle_v4_term_dictionary d on d.term_id=h.term_id
            where h.week_start=:as_of and h.event_count > 0
            order by d.term_id
        """), {"as_of": as_of}).mappings().all()
        if not candidates:
            raise RuntimeError(f"no observed terms for {as_of}")

        history_rows = conn.execute(text("""
            with c as (
              select term_id
              from public.oracle_v4_term_history_weekly
              where week_start=:as_of and event_count > 0
            )
            select h.term_id,h.week_start,h.event_count
            from public.oracle_v4_term_history_weekly h
            join c using(term_id)
            where h.week_start >= :train_start
              and h.week_start < :as_of
            order by h.term_id,h.week_start
        """), {"as_of": as_of, "train_start": train_start}).mappings().all()

        by_term: dict[int, dict[date, int]] = defaultdict(dict)
        for r in history_rows:
            by_term[int(r["term_id"])][r["week_start"]] = int(r["event_count"])

        weeks = [train_start + timedelta(weeks=i) for i in range(TRAIN_WEEKS)]
        results = []
        family_counts: dict[str, int] = defaultdict(int)
        for c in candidates:
            term_id = int(c["term_id"])
            hist = [by_term[term_id].get(w, 0) for w in weeks]
            fit = fit_count_null(hist, int(c["event_count"]))
            family_counts[fit.family] += 1
            results.append({
                "signal_key": str(c["term_key"]),
                "as_of": datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc),
                "null_family": fit.family,
                "observed_value": float(fit.observed),
                "expected_value": fit.expected,
                "dispersion": fit.dispersion,
                "surprise_z": fit.surprise_z,
                "p_value": fit.p_value,
                "model_version": MODEL_VERSION,
                "training_window": json.dumps({
                    "start": train_start.isoformat(),
                    "end": train_end.isoformat(),
                    "weeks": TRAIN_WEEKS,
                    "excludes_test_week": True,
                }, sort_keys=True),
                "diagnostics": json.dumps(fit.diagnostics, sort_keys=True),
            })

        experiment_key = f"v6_formal_count_null_{as_of.isoformat()}"
        spec = {
            "model_version": MODEL_VERSION,
            "train_weeks": TRAIN_WEEKS,
            "test_week": as_of.isoformat(),
            "candidate_rule": "terms with event_count > 0 in test week",
            "missing_week_rule": "explicit_zero",
            "lookahead": False,
            "model_selection": "Gamma-Poisson sparse; NB when formal dispersion test rejects Poisson; otherwise Poisson",
        }
        experiment_id = conn.execute(text("""
            insert into public.oracle_v6_experiments
              (experiment_key,model_family,model_version,target_name,train_start,train_end,
               test_start,test_end,holdout,specification,metrics)
            values
              (:key,'COUNT_NULL_MODEL',:version,'weekly_term_event_count',:train_start,:train_end,
               :test_start,:test_end,false,cast(:spec as jsonb),'{}'::jsonb)
            on conflict (experiment_key) do update set
              model_family=excluded.model_family,
              model_version=excluded.model_version,
              target_name=excluded.target_name,
              train_start=excluded.train_start,
              train_end=excluded.train_end,
              test_start=excluded.test_start,
              test_end=excluded.test_end,
              specification=excluded.specification,
              invalidated_at=null,
              invalidation_reason=null
            returning id
        """), {
            "key": experiment_key,
            "version": MODEL_VERSION,
            "train_start": train_start,
            "train_end": train_end,
            "test_start": as_of,
            "test_end": as_of,
            "spec": json.dumps(spec, sort_keys=True),
        }).scalar_one()

        conn.execute(text("""
            delete from public.oracle_v6_signal_null_models
            where as_of=:as_of and model_version=:version
        """), {
            "as_of": datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc),
            "version": MODEL_VERSION,
        })

        insert_sql = text("""
            insert into public.oracle_v6_signal_null_models
              (signal_key,as_of,null_family,observed_value,expected_value,dispersion,
               surprise_z,p_value,model_version,training_window,diagnostics)
            values
              (:signal_key,:as_of,:null_family,:observed_value,:expected_value,:dispersion,
               :surprise_z,:p_value,:model_version,cast(:training_window as jsonb),cast(:diagnostics as jsonb))
        """)
        for i in range(0, len(results), 500):
            conn.execute(insert_sql, results[i:i+500])

        pvals = [r["p_value"] for r in results]
        metrics = {
            "family_size": len(results),
            "as_of": as_of.isoformat(),
            "min_p_value": min(pvals),
            "median_p_value": sorted(pvals)[len(pvals)//2],
            "model_family_counts": dict(family_counts),
            "formal_p_value": True,
            "temporary": False,
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=cast(:metrics as jsonb)
            where id=:id
        """), {"metrics": json.dumps(metrics, sort_keys=True), "id": experiment_id})

    return {"ok": True, "experiment_id": int(experiment_id), **metrics}


def main() -> None:
    result = run(os.environ.get("ORACLE_SUPABASE_DB_URL", ""))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
