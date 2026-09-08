#!/usr/bin/env python3
"""ORACLE V6 formal PIT nulls for canonical structural concepts.

Concept counts are distinct supporting documents per observed week. Only
structural extractions actually available by decision_as_of are admissible.
The test bucket is the same frozen bucket used by lexical Discovery.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import create_engine, text

from oracle_v6_formal_nulls import _fit_count_null, WINDOW_WEEKS

MODEL_VERSION = "FORMAL_CONCEPT_NULL_V1"
MODEL_FAMILY = "STRUCTURAL_CONCEPT_NULL"
ALLOWED_TYPES = ("TREND", "TECHNOLOGY", "PARADIGM", "BOTTLENECK", "NEED", "RESOURCE")


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
        parent = conn.execute(text("""
            select e.id,
                   (e.metrics->>'test_week')::date as test_week,
                   coalesce((e.metrics->>'test_last_event_date')::date,
                            (e.metrics->>'test_week')::date) as test_last_event_date,
                   (e.metrics->'fdr'->>'as_of')::timestamptz as decision_as_of
            from public.oracle_v6_experiments e
            where e.model_family='COUNT_NULL_MODEL'
              and e.model_version='FORMAL_COUNT_NULL_V1'
              and e.invalidated_at is null
              and e.metrics ? 'fdr'
              and e.metrics ? 'test_week'
            order by e.created_at desc,e.id desc limit 1
        """)).mappings().one_or_none()
        if not parent or parent["decision_as_of"] is None:
            raise RuntimeError("parent PIT Discovery experiment unavailable")

        parent_experiment_id = int(parent["id"])
        test_week: date = parent["test_week"]
        test_last_event_date: date = parent["test_last_event_date"]
        decision_as_of = parent["decision_as_of"]
        train_start = test_week - timedelta(weeks=WINDOW_WEEKS)
        train_end = test_week - timedelta(weeks=1)

        candidates = conn.execute(text("""
            select s.signal_type,s.canonical_name,count(distinct s.document_id) observed_docs
            from public.oracle_structural_signals s
            join public.oracle_raw_documents d on d.id=s.document_id
            where s.signal_type=any(:allowed_types)
              and s.canonical_name is not null and btrim(s.canonical_name)<>''
              and s.available_at<=:decision_as_of
              and d.fetched_at<=:decision_as_of
              and s.observed_at<=:decision_as_of
              and s.observed_at::date between :test_week and :test_last_event_date
            group by s.signal_type,s.canonical_name
            order by s.signal_type,s.canonical_name
        """), {
            "allowed_types": list(ALLOWED_TYPES),
            "decision_as_of": decision_as_of,
            "test_week": test_week,
            "test_last_event_date": test_last_event_date,
        }).mappings().all()
        if not candidates:
            raise RuntimeError("no PIT structural concepts in test bucket")

        concept_keys = [f"{r['signal_type']}:{r['canonical_name']}" for r in candidates]
        history_rows = conn.execute(text("""
            select s.signal_type,s.canonical_name,
                   date_trunc('week',s.observed_at)::date as week_start,
                   count(distinct s.document_id) as doc_count
            from public.oracle_structural_signals s
            join public.oracle_raw_documents d on d.id=s.document_id
            where (s.signal_type || ':' || s.canonical_name)=any(:concept_keys)
              and s.available_at<=:decision_as_of
              and d.fetched_at<=:decision_as_of
              and s.observed_at<=:decision_as_of
              and s.observed_at::date>=:train_start
              and s.observed_at::date<:test_week
            group by s.signal_type,s.canonical_name,date_trunc('week',s.observed_at)::date
            order by s.signal_type,s.canonical_name,week_start
        """), {
            "concept_keys": concept_keys,
            "decision_as_of": decision_as_of,
            "train_start": train_start,
            "test_week": test_week,
        }).mappings().all()

        by_key: dict[str, dict[date,int]] = defaultdict(dict)
        for r in history_rows:
            key = f"{r['signal_type']}:{r['canonical_name']}"
            by_key[key][r["week_start"]] = int(r["doc_count"])
        weeks = [train_start + timedelta(weeks=i) for i in range(WINDOW_WEEKS)]

        payload = []
        family_counts: dict[str,int] = defaultdict(int)
        for c in candidates:
            key = f"{c['signal_type']}:{c['canonical_name']}"
            train = [by_key[key].get(w,0) for w in weeks]
            observed = int(c["observed_docs"])
            fit = _fit_count_null(train, observed)
            family_counts[fit.family] += 1
            diagnostics = {
                **fit.diagnostics,
                "formal_p_value": True,
                "temporary": False,
                "point_in_time": True,
                "availability_quality": "KNOWN",
                "parent_experiment_id": parent_experiment_id,
                "concept_signal_type": str(c["signal_type"]),
                "concept_canonical_name": str(c["canonical_name"]),
                "count_unit": "distinct_supporting_documents",
                "test_week": test_week.isoformat(),
                "test_last_event_date": test_last_event_date.isoformat(),
                "decision_as_of": decision_as_of.isoformat(),
            }
            payload.append({
                "signal_key": key,
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
                    "test_last_event_date": test_last_event_date.isoformat(),
                    "decision_as_of": decision_as_of.isoformat(),
                    "zero_filled_missing_weeks": True,
                    "excludes_test_week": True,
                }, sort_keys=True),
                "diagnostics": json.dumps(diagnostics, sort_keys=True),
            })

        experiment_key = f"v6_formal_concept_null_{test_week.isoformat()}"
        specification = json.dumps({
            "parent_experiment_id": parent_experiment_id,
            "window_weeks": WINDOW_WEEKS,
            "strict_pre_test_training": True,
            "count_unit": "distinct_supporting_documents",
            "allowed_structural_types": list(ALLOWED_TYPES),
            "test_week": test_week.isoformat(),
            "test_last_event_date": test_last_event_date.isoformat(),
            "decision_as_of": decision_as_of.isoformat(),
            "statistical_core": "oracle_v6_formal_nulls._fit_count_null",
        }, sort_keys=True)
        exp_id = conn.execute(text("""
            insert into public.oracle_v6_experiments
              (experiment_key,model_family,model_version,target_name,train_start,train_end,
               test_start,test_end,holdout,specification,metrics)
            values
              (:key,:family,:version,'weekly_structural_concept_document_count',
               :train_start,:train_end,:test_week,:test_last,false,cast(:spec as jsonb),'{}'::jsonb)
            on conflict (experiment_key) do update set
              model_family=excluded.model_family,model_version=excluded.model_version,
              target_name=excluded.target_name,train_start=excluded.train_start,
              train_end=excluded.train_end,test_start=excluded.test_start,test_end=excluded.test_end,
              specification=excluded.specification,invalidated_at=null,invalidation_reason=null
            returning id
        """), {
            "key": experiment_key,"family": MODEL_FAMILY,"version": MODEL_VERSION,
            "train_start": train_start,"train_end": train_end,"test_week": test_week,
            "test_last": test_last_event_date,"spec": specification,
        }).scalar_one()

        conn.execute(text("""
            delete from public.oracle_v6_signal_null_models
            where model_version=:version
              and training_window->>'test_week'=:test_week
        """), {"version": MODEL_VERSION,"test_week": test_week.isoformat()})
        insert_sql = text("""
            insert into public.oracle_v6_signal_null_models
              (signal_key,as_of,null_family,observed_value,expected_value,dispersion,
               surprise_z,p_value,model_version,training_window,diagnostics)
            values
              (:signal_key,:as_of,:null_family,:observed_value,:expected_value,:dispersion,
               :surprise_z,:p_value,:model_version,cast(:training_window as jsonb),cast(:diagnostics as jsonb))
        """)
        conn.execute(insert_sql,payload)

        pvals = sorted(float(p["p_value"]) for p in payload)
        metrics = json.dumps({
            "parent_experiment_id": parent_experiment_id,
            "rows": len(payload),
            "family_counts": dict(family_counts),
            "min_p_value": pvals[0],
            "median_p_value": pvals[len(pvals)//2],
            "formal_p_value": True,
            "temporary": False,
            "test_week": test_week.isoformat(),
            "test_last_event_date": test_last_event_date.isoformat(),
            "decision_as_of": decision_as_of.isoformat(),
            "availability_quality": "KNOWN",
        }, sort_keys=True)
        conn.execute(text("update public.oracle_v6_experiments set metrics=cast(:metrics as jsonb) where id=:id"), {"metrics":metrics,"id":exp_id})

    return {
        "ok": True,"experiment_id":int(exp_id),"parent_experiment_id":parent_experiment_id,
        "test_week":test_week.isoformat(),"decision_as_of":decision_as_of.isoformat(),
        "concepts":len(payload),"families":dict(family_counts),
    }


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
