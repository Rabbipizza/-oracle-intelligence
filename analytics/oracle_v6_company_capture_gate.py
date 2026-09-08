#!/usr/bin/env python3
"""ORACLE V6 PIT company-capture evidence gate.

Structural concepts are frozen at the signal's immutable availability time.
Company evidence is evaluated at the current evaluation-run timestamp, allowing
newly available SEC evidence without rewriting first detection history.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from sqlalchemy import create_engine, text

MODEL_VERSION = "COMPANY_CAPTURE_EVIDENCE_GATE_V1"
MAX_EVIDENCE = 50


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
    external_run_id = os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp = conn.execute(text("""
            select id,(metrics->>'decision_as_of')::timestamptz signal_available_at
            from public.oracle_v6_experiments
            where model_family='COUNT_NULL_MODEL'
              and model_version='FORMAL_COUNT_NULL_V1'
              and invalidated_at is null
              and metrics ? 'decision_as_of'
            order by created_at desc,id desc limit 1
        """)).mappings().one_or_none()
        if not exp or exp["signal_available_at"] is None:
            raise RuntimeError("latest PIT Discovery experiment unavailable")

        experiment_id = int(exp["id"])
        signal_available_at = exp["signal_available_at"]
        evaluation_as_of = signal_available_at
        if external_run_id:
            ev = conn.execute(text("""
                select evaluation_as_of from public.oracle_v6_evaluation_runs
                where external_run_id=:run_id and experiment_id=:experiment_id
            """), {"run_id": external_run_id, "experiment_id": experiment_id}).scalar_one_or_none()
            if ev is not None:
                evaluation_as_of = ev

        concepts = [str(x) for x in conn.execute(text("""
            select distinct split_part(g.target_node,':',2) concept
            from public.oracle_v6_graph_edges g
            where g.generated_by_model='SEMANTIC_BRIDGE_V1'
              and g.evidence_cutoff_at=:signal_cutoff
              and split_part(g.target_node,':',2)<>''
            order by 1
        """), {"signal_cutoff": signal_available_at}).scalars().all()]
        if not concepts:
            raise RuntimeError("no structural concepts from semantic bridge")

        rows = conn.execute(text("""
            select e.id,e.ticker,e.evidence_key,e.excerpt,e.source_url,
                   coalesce(e.available_at,e.known_at,e.created_at) available_at,
                   e.source_quality,c.concept
            from public.oracle_v4_sec_economic_evidence e
            cross join unnest(cast(:concepts as text[])) as c(concept)
            where coalesce(e.available_at,e.known_at,e.created_at)<=:evaluation_cutoff
              and lower(e.excerpt) like '%'||lower(c.concept)||'%'
            order by c.concept,e.ticker,e.id
        """), {"concepts": concepts, "evaluation_cutoff": evaluation_as_of}).mappings().all()

        grouped: dict[tuple[str,str], list[dict]] = defaultdict(list)
        for r in rows:
            grouped[(str(r["ticker"]), str(r["concept"]))].append(dict(r))

        payload = []
        for (ticker, concept), evidence_rows in sorted(grouped.items()):
            evidence = []
            for r in evidence_rows[:MAX_EVIDENCE]:
                evidence.append({
                    "sec_evidence_id": int(r["id"]),
                    "evidence_key": str(r["evidence_key"]),
                    "available_at": r["available_at"].isoformat(),
                    "source_quality": float(r["source_quality"]) if r["source_quality"] is not None else None,
                    "match_method": "EXACT_CANONICAL_CONCEPT_SUBSTRING",
                    "predictive_claim": False,
                    "causal_claim": False,
                    "capture_probability_calibrated": False,
                })
            payload.append({
                "ticker": ticker,
                "trend_key": concept,
                "as_of": evaluation_as_of,
                "model_version": MODEL_VERSION,
                "evidence_ids": json.dumps(evidence, sort_keys=True),
            })

        conn.execute(text("delete from public.oracle_v6_company_capture where model_version=:model and as_of=:cutoff"), {
            "model": MODEL_VERSION, "cutoff": evaluation_as_of,
        })
        if payload:
            conn.execute(text("""
                insert into public.oracle_v6_company_capture
                  (ticker,trend_key,as_of,revenue_exposure,expected_incremental_revenue,
                   expected_incremental_margin,pricing_power_probability,
                   deliverable_capacity_probability,expected_incremental_fcf,capex_required,
                   capture_probability,model_version,evidence_ids)
                values
                  (:ticker,:trend_key,:as_of,null,null,null,null,null,null,null,null,
                   :model_version,cast(:evidence_ids as jsonb))
            """), payload)

        summary = {
            "model_version": MODEL_VERSION,
            "signal_available_at": signal_available_at.isoformat(),
            "evaluation_as_of": evaluation_as_of.isoformat(),
            "structural_concepts_considered": len(concepts),
            "candidate_pairs": len(payload),
            "tickers": len({p["ticker"] for p in payload}),
            "concepts_with_sec_support": len({p["trend_key"] for p in payload}),
            "capture_probabilities_written": 0,
            "financial_impact_fields_written": 0,
            "state": "EVIDENCE_CANDIDATES_ONLY_UNCALIBRATED",
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{company_capture_gate}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {"ok": True, "experiment_id": experiment_id, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
