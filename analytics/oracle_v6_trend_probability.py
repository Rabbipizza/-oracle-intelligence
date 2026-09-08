#!/usr/bin/env python3
"""ORACLE V6 trend persistence probability worker.

Consumes only BH-FDR selected formal count anomalies. Statistical history is
indexed by the experiment's test_week, while all persisted as_of / detection
timestamps use the reconstructed decision_as_of from actual data availability.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

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


def _persistence_probability(positive_weeks: list[date], test_week: date) -> tuple[float, int, int]:
    weeks = sorted(w for w in positive_weeks if w < test_week)
    eligible_cutoff = test_week - timedelta(weeks=HORIZON_WEEKS)
    trials = 0
    successes = 0
    week_set = set(weeks)
    for w in weeks:
        if w > eligible_cutoff:
            continue
        trials += 1
        if any((w + timedelta(weeks=k)) in week_set for k in range(1, HORIZON_WEEKS + 1)):
            successes += 1
    return (successes + 1.0) / (trials + 2.0), successes, trials


def run(db_url: str) -> dict:
    engine = _engine(db_url)
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select e.id,
                   (e.metrics->'fdr'->>'as_of')::timestamptz as decision_as_of,
                   (e.metrics->>'test_week')::date as test_week
            from public.oracle_v6_experiments e
            where e.model_family='COUNT_NULL_MODEL'
              and e.model_version='FORMAL_COUNT_NULL_V1'
              and e.invalidated_at is null
              and e.metrics ? 'fdr'
              and e.metrics ? 'test_week'
            order by e.created_at desc,e.id desc limit 1
        """)).mappings().one_or_none()
        if not exp:
            raise RuntimeError("formal FDR experiment with PIT test_week unavailable")
        experiment_id = int(exp["id"])
        decision_as_of = exp["decision_as_of"]
        test_week = exp["test_week"]
        if decision_as_of is None or test_week is None:
            raise RuntimeError("decision_as_of/test_week missing")

        selected = conn.execute(text("""
            select m.hypothesis_key, m.adjusted_p_value
            from public.oracle_v6_multiple_testing m
            where m.experiment_id=:experiment_id
              and m.as_of=:decision_as_of
              and m.method='BENJAMINI_HOCHBERG'
              and m.selected=true
            order by m.hypothesis_key
        """), {"experiment_id": experiment_id, "decision_as_of": decision_as_of}).mappings().all()
        if not selected:
            raise RuntimeError("no FDR-selected candidates")

        keys = [str(r["hypothesis_key"]) for r in selected]
        q_by_key = {str(r["hypothesis_key"]): float(r["adjusted_p_value"]) for r in selected}
        history_start = test_week - timedelta(weeks=HISTORY_WEEKS)

        rows = conn.execute(text("""
            select d.term_key,h.week_start,h.event_count
            from public.oracle_v4_term_dictionary d
            join public.oracle_v4_term_history_weekly h on h.term_id=d.term_id
            where d.term_key = any(:keys)
              and h.week_start between :history_start and :test_week
              and h.event_count > 0
            order by d.term_key,h.week_start
        """), {"keys": keys, "history_start": history_start, "test_week": test_week}).mappings().all()

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
        payload = []
        for k in keys:
            p_persist, successes, trials = _persistence_probability(positive.get(k, []), test_week)
            current = counts.get((k, test_week), 0)
            prev4 = [counts.get((k, test_week - timedelta(weeks=i)), 0) for i in range(1,5)]
            prev12 = [counts.get((k, test_week - timedelta(weeks=i)), 0) for i in range(1,13)]
            mean4 = sum(prev4) / 4.0
            mean12 = sum(prev12) / 12.0
            acceleration = current / (mean4 + 1.0)
            prior_positive = sum(1 for w in positive.get(k, []) if w < test_week)
            novelty = 1.0 / (1.0 + prior_positive)
            evidence = {
                "formal_fdr_adjusted_p": q_by_key[k],
                "test_week": test_week.isoformat(),
                "decision_as_of": decision_as_of.isoformat(),
                "current_count": current,
                "previous_4w_mean": mean4,
                "previous_12w_mean": mean12,
                "persistence_successes": successes,
                "persistence_trials": trials,
                "posterior_prior": "Beta(1,1)",
                "persistence_horizon_weeks": HORIZON_WEEKS,
                "history_weeks": HISTORY_WEEKS,
                "availability_quality": "KNOWN",
            }
            payload.append({
                "trend_key": k,
                "as_of": decision_as_of,
                "first_detected_at": existing_first.get(k, decision_as_of),
                "state": "SIGNAL",
                "p_structural": p_persist,
                "novelty": novelty,
                "acceleration": acceleration,
                "persistence": p_persist,
                "model_version": MODEL_VERSION,
                "evidence_ids": json.dumps([evidence], sort_keys=True),
                "experiment_id": experiment_id,
            })

        # Replace all materializations for this experiment/model; this also
        # removes the earlier backdated as_of=week_start version.
        conn.execute(text("""
            delete from public.oracle_v6_trend_probabilities
            where experiment_id=:experiment_id and model_version=:version
        """), {"experiment_id": experiment_id, "version": MODEL_VERSION})
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
            "test_week": test_week.isoformat(),
            "decision_as_of": decision_as_of.isoformat(),
            "persistence_horizon_weeks": HORIZON_WEEKS,
            "history_weeks": HISTORY_WEEKS,
            "state_policy": "FDR survivors remain SIGNAL until lifecycle thresholds are calibrated",
            "availability_quality": "KNOWN",
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{trend_probability}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {
        "ok": True,
        "experiment_id": experiment_id,
        "test_week": test_week.isoformat(),
        "decision_as_of": decision_as_of.isoformat(),
        "candidates": len(payload),
    }


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
