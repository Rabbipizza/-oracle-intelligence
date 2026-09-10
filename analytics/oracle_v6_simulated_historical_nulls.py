#!/usr/bin/env python3
"""P0-9 strict simulated-historical Discovery reconstruction.

This module never reads the LIVE ingestion clock and never writes LIVE null/FDR
or sequential-alpha tables. For every cutoff T it rebuilds the 104-week count
history and test bucket from source documents whose available_at_simulated <= T,
then refits the same count null family used in production.

The occurrence extraction is document-local and frozen by extraction_version;
derived count statistics, null fits, BH selection and alpha spending are all
recomputed at every T. No all-history baseline is reused.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import create_engine, text

from oracle_v6_formal_nulls import _fit_count_null, WINDOW_WEEKS

TARGET_ALPHA = 0.05
MODEL_VERSION = "FORMAL_COUNT_NULL_V1_SIMULATED_P0_9"
DEFAULT_DATES = [
    "2018-12-31", "2019-06-30", "2019-12-31", "2020-06-30", "2020-12-31",
    "2021-12-31", "2022-06-30", "2022-12-31", "2023-06-30", "2023-12-31",
]


def _engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("PostgreSQL URL required")
    return create_engine(db_url, pool_pre_ping=True)


def _bh_adjusted(pvals: list[float]) -> list[float]:
    n = len(pvals)
    if not n:
        return []
    order = sorted(range(n), key=lambda i: pvals[i])
    out = [1.0] * n
    running = 1.0
    for rank in range(n, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * n / rank)
        out[i] = min(1.0, running)
    return out


def _cutoff(d: date) -> datetime:
    return datetime.combine(d, time(23, 59, 59), tzinfo=timezone.utc)


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _parse_dates() -> list[date]:
    raw = os.environ.get("ORACLE_V6_SIMULATED_DATES", ",".join(DEFAULT_DATES))
    dates = sorted({date.fromisoformat(x.strip()) for x in raw.split(",") if x.strip()})
    if not dates:
        raise ValueError("at least one simulated date required")
    return dates


def _family_at(conn, cutoff: datetime, test_week: date):
    train_start = test_week - timedelta(weeks=WINDOW_WEEKS)
    test_end = test_week + timedelta(days=6)
    rows = conn.execute(text("""
      select o.canonical_term,
             date_trunc('week',o.event_date::timestamp)::date week_start,
             count(distinct o.document_id) doc_count
      from public.oracle_v4_retro_term_occurrences o
      join public.oracle_raw_documents d on d.id=o.document_id
      where d.available_at_simulated is not null
        and d.available_at_simulated <= :cutoff
        and o.event_date >= :train_start
        and o.event_date <= :test_end
        and o.canonical_term is not null and btrim(o.canonical_term)<>''
      group by o.canonical_term,date_trunc('week',o.event_date::timestamp)::date
      order by o.canonical_term,week_start
    """), {"cutoff": cutoff, "train_start": train_start, "test_end": test_end}).mappings().all()

    by_term: dict[str, dict[date, int]] = defaultdict(dict)
    for r in rows:
        by_term[str(r["canonical_term"])][r["week_start"]] = int(r["doc_count"])
    weeks = [train_start + timedelta(weeks=i) for i in range(WINDOW_WEEKS)]
    payload = []
    for key, history in sorted(by_term.items()):
        observed = history.get(test_week, 0)
        if observed <= 0:
            continue
        train = [history.get(w, 0) for w in weeks]
        fit = _fit_count_null(train, observed)
        payload.append({
            "signal_key": key,
            "null_family": fit.family,
            "observed_value": observed,
            "expected_value": fit.expected,
            "dispersion": fit.dispersion,
            "surprise_z": fit.z_score,
            "p_value": fit.p_value,
            "training_window": {
                "weeks": WINDOW_WEEKS,
                "train_start": train_start.isoformat(),
                "train_end": (test_week - timedelta(weeks=1)).isoformat(),
                "test_week": test_week.isoformat(),
                "test_end": test_end.isoformat(),
                "cutoff": cutoff.isoformat(),
                "clock_mode": "simulated_historical",
                "source_filter": "raw_document.available_at_simulated<=T",
            },
            "diagnostics": {
                **fit.diagnostics,
                "point_in_time": True,
                "clock_mode": "simulated_historical",
                "recomputed_at_cutoff": True,
                "all_history_baseline_reused": False,
            },
        })
    return payload


def run(db_url: str) -> dict:
    dates = _parse_dates()
    run_material = ",".join(d.isoformat() for d in dates)
    reconstruction_run = os.environ.get("ORACLE_V6_RECONSTRUCTION_RUN") or (
        "P0_9_" + hashlib.sha256(run_material.encode()).hexdigest()[:16]
    )
    e = _engine(db_url)
    summaries = []
    cumulative = 0.0
    with e.begin() as conn:
        conn.execute(text("delete from public.oracle_v6_simulated_null_models where reconstruction_run=:r"), {"r": reconstruction_run})
        conn.execute(text("delete from public.oracle_v6_simulated_alpha_budget where reconstruction_run=:r"), {"r": reconstruction_run})
        for t, d in enumerate(dates, start=1):
            cutoff = _cutoff(d)
            test_week = _week_start(d)
            family = _family_at(conn, cutoff, test_week)
            gamma = 6.0 / (math.pi * math.pi * t * t)
            alpha_t = TARGET_ALPHA * gamma
            cumulative += alpha_t
            pvals = [float(x["p_value"]) for x in family]
            adjusted = _bh_adjusted(pvals)
            selected = [a <= alpha_t for a in adjusted]
            for i, row in enumerate(family):
                row.update({
                    "reconstruction_run": reconstruction_run,
                    "evaluation_date": d,
                    "decision_as_of": cutoff,
                    "training_window_json": json.dumps(row.pop("training_window"), sort_keys=True),
                    "diagnostics_json": json.dumps(row.pop("diagnostics"), sort_keys=True),
                    "bh_adjusted_p": adjusted[i],
                    "bh_selected": selected[i],
                    "alpha_t": alpha_t,
                })
            if family:
                conn.execute(text("""
                  insert into public.oracle_v6_simulated_null_models
                    (reconstruction_run,evaluation_date,decision_as_of,signal_key,null_family,
                     observed_value,expected_value,dispersion,surprise_z,p_value,training_window,
                     diagnostics,bh_adjusted_p,bh_selected,alpha_t)
                  values (:reconstruction_run,:evaluation_date,:decision_as_of,:signal_key,:null_family,
                     :observed_value,:expected_value,:dispersion,:surprise_z,:p_value,
                     cast(:training_window_json as jsonb),cast(:diagnostics_json as jsonb),
                     :bh_adjusted_p,:bh_selected,:alpha_t)
                """), family)
            discoveries = sum(selected)
            conn.execute(text("""
              insert into public.oracle_v6_simulated_alpha_budget
                (reconstruction_run,sequence_t,evaluation_date,gamma_t,alpha_t,cumulative_alpha_spend,family_size,discoveries)
              values(:r,:t,:d,:g,:a,:c,:n,:k)
            """), {"r": reconstruction_run, "t": t, "d": d, "g": gamma, "a": alpha_t,
                     "c": cumulative, "n": len(family), "k": discoveries})
            summaries.append({"date": d.isoformat(), "test_week": test_week.isoformat(),
                              "family_size": len(family), "discoveries": discoveries,
                              "gamma_t": gamma, "alpha_t": alpha_t})
    return {"ok": True, "clock_mode": "simulated_historical", "reconstruction_run": reconstruction_run,
            "dates": summaries, "target_alpha": TARGET_ALPHA, "cumulative_alpha_spend": cumulative,
            "live_budget_touched": False}


if __name__ == "__main__":
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))
