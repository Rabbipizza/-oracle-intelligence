#!/usr/bin/env python3
"""ORACLE V6 trend probability worker.

Consumes only BH-FDR selected formal count anomalies. For each candidate it
estimates an empirical posterior predictive probability that a positive weekly
occurrence is followed by another positive occurrence within four weeks.
This probability is distinct from anomaly significance and is intentionally
not an arbitrary weighted score.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import create_engine, text

MODEL_VERSION = "TREND_PERSISTENCE_V1"
HORIZON_WEEKS = 4
HISTORY_WEEKS = 260


def _engine(db_url: str):
    if db_url.startswith("postgres://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"):
        db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else:
        raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url, pool_pre_ping=True)


def _persistence_probability(positive_weeks: list[date], as_of: date) -> tuple[float, int, int]:
    weeks = sorted(w for w in positive_weeks if w < as_of)
    eligible_cutoff = as_of - timedelta(weeks=HORIZON_WEEKS)
    trials = 0
    successes = 0
    week_set = set(weeks)
    for w in weeks:
        if w > eligible_cutoff:
            continue
        trials += 1
        if any((w + timedelta(weeks=k)) in week_set for k in range(1, HORIZON_WEEKS + 1)):
            successes += 1
    # Beta(1,1) posterior predictive mean.
    return (successes + 1.0) / (trials + 2.0), successes, trials


def run(db_url: str) -> dict:
    engine = _engine(db_url)
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select e.id, (e.metrics->'fdr'->>'as_of')::timestamptz as as_of
            from public.oracle_v6_experiments e
            where e.model_family='COUNT_NULL_MODEL'
              and e.model_version='FORMAL_COUNT_NULL_V1'
              and e.invalidated_at is null
              and e.metrics ? 'fdr'
            order by e.created_at desc,e.id desc limit 1
        """)).mappings().one_or_none()
        if not exp:
            raise RuntimeError("formal FDR experiment unavailable")
        experiment_id = int(exp["id"])
        as_of_ts = exp["as_of"]
        as_of = as_of_ts.date()

        selected = conn.execute(text("""
            select m.hypothesis_key, m.adjusted_p_value
            from public.oracle_v6_multiple_testing m
            where m.experiment_id=:experiment_id
              and m.as_of=:as_of
              and m.method='BENJAMINI_HOCHBERG'
              and m.selected=true
            order by m.hypothesis_key
        """), {"experiment_id": experiment_id, "as_of": as_of_ts}).mappings().all()
        if not selected:
            raise RuntimeError("no FDR-selected candidates")

        keys = [str(r["hypothesis_key"]) for r in selected]
        q_by_key = {str(r["hypothesis_key"]): float(r["adjusted_p_value"]) for r in selected}
        history_start = as_of - timedelta(weeks=HISTORY_WEEKS)

        rows = conn.execute(text("""
            select d.term_key,h.week_start,h.event_count
            from public.oracle_v4_term_dictionary d
            join public.oracle_v4_term_history_weekly h on h.term_id=d.term_id
            where d.term_key = any(:keys)
              and h.week_start between :history_start and :as_of
              and h.event_count > 0
            order by d.term_key,h.week_start
        """), {"keys": keys, "history_start": history_start, "as_of": as_of}).mappings().all()

        positive: dict[str, list[date]] = defaultdict(list)
        counts: dict[tuple[str,date], int] = {}
        for r in rows:
            k = str(r["term_key"])
            w = r["week_start"]
            positive[k].append(w)
            counts[(k,w)] = int(r["event_count"])

        existing_first = {
            str(r["trend_key"]): r["first_detected_at"]
            for r in conn.execute(text("""
                select trend_key,min(first_detected_at) as first_detected_at
                from public.oracle_v6_trend_probabilities
                group by trend_key
            """)).mappings().all()
        }
        detection_now = datetime.now(timezone.utc)
        payload = []
        for k in keys:
            p_persist, successes, trials = _persistence_probability(positive.get(k, []), as_of)
            current = counts.get((k, as_of), 0)
            prev4 = [counts.get((k, as_of - timedelta(weeks=i)), 0) for i in range(1,5)]
            prev12 = [counts.get((k, as_of - timedelta(weeks=i)), 0) for i in range(1,13)]
            mean4 = sum(prev4) / 4.0
            mean12 = sum(prev12) / 12.0
            acceleration = current / (mean4 + 1.0)
            prior_positive = sum(1 for w in positive.get(k, []) if w < as_of)
            novelty = 1.0 / (1.0 + prior_positive)
            evidence = {
                "formal_fdr_adjusted_p": q_by_key[k],
                "current_count": current,
                "previous_4w_mean": mean4,
                "previous_12w_mean": mean12,
                "persistence_successes": successes,
                "persistence_trials": trials,
                "posterior_prior": "Beta(1,1)",
                "persistence_horizon_weeks": HORIZON_WEEKS,
                "history_weeks": HISTORY_WEEKS,
            }
            payload.append({
                "trend_key": k,
                "as_of": as_of_ts,
                "first_detected_at": existing_first.get(k, detection_now),
                "state": "DISCOVERY_CANDIDATE",
                "p_structural": p_persist,
                "novelty": novelty,
                "acceleration": acceleration,
                "persistence": p_persist,
                "model_version": MODEL_VERSION,
                "evidence_ids": json.dumps([evidence], sort_keys=True),
                "experiment_id": experiment_id,
            })

        conn.execute(text("""
            delete from public.oracle_v6_trend_probabilities
            where experiment_id=:experiment_id and as_of=:as_of and model_version=:version
        """), {"experiment_id": experiment_id, "as_of": as_of_ts, "version": MODEL_VERSION})
        conn.execute(text("""
            insert into public.oracle_v6_trend_probabilities
              (trend_key,as_of,first_detected_at,state,p_structural,novelty,acceleration,
               persistence,model_version,evidence_ids,experiment_id)
            values
              (:trend_key,:as_of,:first_detected_at,:state,:p_structural,:novelty,:acceleration,
               :persistence,:model_version,cast(:evidence_ids as jsonb),:experiment_id)
        """), payload)

        summary = {
            "model_version": MODEL_VERSION,
            "candidates": len(payload),
            "persistence_horizon_weeks": HORIZON_WEEKS,
            "history_weeks": HISTORY_WEEKS,
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{trend_probability}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {"ok": True, "experiment_id": experiment_id, "as_of": as_of_ts.isoformat(), "candidates": len(payload)}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
