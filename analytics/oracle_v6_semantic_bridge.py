#!/usr/bin/env python3
"""ORACLE V6 PIT semantic bridge: lexical anomaly -> structural concept.

The formal Discovery layer produces lexical SIGNALs. This worker links those
signals to canonical structural concepts only when the lexical occurrence and
the structural extraction coexist in the same source document and both were
available by decision_as_of.

Edges are descriptive association, never predictive or causal. A Beta(1,1)
posterior mean summarizes P(structural concept | lexical-signal document).
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import create_engine, text

MODEL_VERSION = "SEMANTIC_BRIDGE_V1"
ALLOWED_STRUCTURAL_TYPES = ("TREND", "TECHNOLOGY", "PARADIGM", "BOTTLENECK", "NEED", "RESOURCE")
MAX_EVIDENCE_IDS = 50


@dataclass
class Evidence:
    signal_key: str
    signal_type: str
    canonical_name: str
    linked_docs: set[str] = field(default_factory=set)
    independence_groups: set[str] = field(default_factory=set)
    availabilities: list[datetime] = field(default_factory=list)


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
        exp = conn.execute(text("""
            select e.id,
                   (e.metrics->>'test_week')::date as test_week,
                   (e.metrics->>'test_last_event_date')::date as test_last_event_date,
                   (e.metrics->'fdr'->>'as_of')::timestamptz as decision_as_of
            from public.oracle_v6_experiments e
            where e.model_family='COUNT_NULL_MODEL'
              and e.model_version='FORMAL_COUNT_NULL_V1'
              and e.invalidated_at is null
              and e.metrics ? 'fdr'
              and e.metrics ? 'test_week'
            order by e.created_at desc,e.id desc limit 1
        """)).mappings().one_or_none()
        if not exp or exp["decision_as_of"] is None or exp["test_week"] is None:
            raise RuntimeError("latest PIT Discovery experiment unavailable")

        experiment_id = int(exp["id"])
        test_week = exp["test_week"]
        test_last_event_date = exp["test_last_event_date"] or test_week
        decision_as_of = exp["decision_as_of"]

        # Only current formal FDR survivors may seed semantic concepts.
        keys = [str(x) for x in conn.execute(text("""
            select trend_key
            from public.oracle_v6_trend_probabilities
            where experiment_id=:experiment_id
              and model_version='TREND_PERSISTENCE_V1'
              and state='SIGNAL'
              and as_of=:decision_as_of
            order by trend_key
        """), {"experiment_id": experiment_id, "decision_as_of": decision_as_of}).scalars().all()]
        if not keys:
            raise RuntimeError("no current PIT lexical SIGNALs")

        # Eligible lexical documents form the denominator for descriptive
        # association. They must belong to this test bucket and be genuinely
        # available by the scientific decision time.
        eligible_rows = conn.execute(text("""
            select lower(o.canonical_term) signal_key,
                   o.document_id,
                   greatest(o.created_at,d.fetched_at) lexical_available_at,
                   coalesce(sf.independence_group,
                            'unmapped:' || coalesce(src.source_type,'unknown')) independence_group
            from public.oracle_v4_retro_term_occurrences o
            join public.oracle_raw_documents d on d.id=o.document_id
            left join public.oracle_sources src on src.id=d.source_id
            left join public.oracle_source_family_map sm on sm.source_type=src.source_type
            left join public.oracle_source_families sf on sf.family=sm.family
            where lower(o.canonical_term)=any(:keys)
              and o.event_date between :test_week and :test_last_event_date
              and o.created_at <= :decision_as_of
              and d.fetched_at <= :decision_as_of
        """), {
            "keys": [k.lower() for k in keys],
            "test_week": test_week,
            "test_last_event_date": test_last_event_date,
            "decision_as_of": decision_as_of,
        }).mappings().all()

        eligible_docs: dict[str, set[str]] = defaultdict(set)
        for r in eligible_rows:
            eligible_docs[str(r["signal_key"])].add(str(r["document_id"]))

        if not eligible_docs:
            raise RuntimeError("no PIT-eligible lexical documents for current signals")

        link_rows = conn.execute(text("""
            select lower(o.canonical_term) signal_key,
                   o.document_id,
                   s.signal_type,
                   s.canonical_name,
                   greatest(o.created_at,d.fetched_at,s.available_at) available_at,
                   coalesce(sf.independence_group,
                            'unmapped:' || coalesce(src.source_type,'unknown')) independence_group
            from public.oracle_v4_retro_term_occurrences o
            join public.oracle_raw_documents d on d.id=o.document_id
            join public.oracle_structural_signals s on s.document_id=o.document_id
            left join public.oracle_sources src on src.id=d.source_id
            left join public.oracle_source_family_map sm on sm.source_type=src.source_type
            left join public.oracle_source_families sf on sf.family=sm.family
            where lower(o.canonical_term)=any(:keys)
              and o.event_date between :test_week and :test_last_event_date
              and o.created_at <= :decision_as_of
              and d.fetched_at <= :decision_as_of
              and s.available_at <= :decision_as_of
              and s.observed_at <= :decision_as_of
              and s.signal_type=any(:allowed_types)
              and s.canonical_name is not null
              and btrim(s.canonical_name) <> ''
        """), {
            "keys": [k.lower() for k in keys],
            "test_week": test_week,
            "test_last_event_date": test_last_event_date,
            "decision_as_of": decision_as_of,
            "allowed_types": list(ALLOWED_STRUCTURAL_TYPES),
        }).mappings().all()

        grouped: dict[tuple[str,str,str], Evidence] = {}
        for r in link_rows:
            key = (str(r["signal_key"]), str(r["signal_type"]), str(r["canonical_name"]))
            ev = grouped.setdefault(key, Evidence(*key))
            ev.linked_docs.add(str(r["document_id"]))
            ev.independence_groups.add(str(r["independence_group"]))
            ev.availabilities.append(r["available_at"])

        payload = []
        descriptive = 0
        hypotheses = 0
        for (signal_key, signal_type, canonical_name), ev in grouped.items():
            denominator = len(eligible_docs.get(signal_key, set()))
            linked = len(ev.linked_docs)
            if denominator <= 0 or linked <= 0:
                continue
            # Beta(1,1) posterior mean for a descriptive conditional
            # co-occurrence probability; this is not a causal probability.
            posterior = (linked + 1.0) / (denominator + 2.0)
            independent_count = len(ev.independence_groups)
            status = "SUPPORTED_DESCRIPTIVE" if independent_count >= 2 else "HYPOTHESIS"
            descriptive += int(status == "SUPPORTED_DESCRIPTIVE")
            hypotheses += int(status == "HYPOTHESIS")
            evidence_ids = sorted(ev.linked_docs)[:MAX_EVIDENCE_IDS]
            validation_stats = {
                "experiment_id": experiment_id,
                "test_week": test_week.isoformat(),
                "test_last_event_date": test_last_event_date.isoformat(),
                "decision_as_of": decision_as_of.isoformat(),
                "availability_quality": "KNOWN",
                "eligible_lexical_documents": denominator,
                "linked_documents": linked,
                "independence_groups": sorted(ev.independence_groups),
                "posterior_prior": "Beta(1,1)",
                "posterior_mean_semantics": "P(structural concept | PIT lexical-signal document)",
                "predictive_claim": False,
                "causal_claim": False,
            }
            payload.append({
                "source_node": f"LEXICAL_SIGNAL:{signal_key}",
                "target_node": f"{signal_type}:{canonical_name}",
                "valid_from": min(ev.availabilities),
                "valid_to": None,
                "sign": 1,
                "mechanism": "SAME_DOCUMENT_STRUCTURAL_COOCCURRENCE",
                "expected_lag_days": None,
                "elasticity_low": None,
                "elasticity_high": None,
                "status": status,
                "posterior_probability": posterior,
                "independent_source_count": independent_count,
                "evidence_ids": json.dumps(evidence_ids),
                "validation_method": "PIT_SAME_DOCUMENT_BETA_BINOMIAL",
                "validation_stats": json.dumps(validation_stats, sort_keys=True),
                "generated_by_model": MODEL_VERSION,
                "prompt_hash": None,
                "evidence_cutoff_at": decision_as_of,
            })

        conn.execute(text("delete from public.oracle_v6_graph_edges where generated_by_model=:model"), {"model": MODEL_VERSION})
        if payload:
            insert_sql = text("""
                insert into public.oracle_v6_graph_edges
                  (source_node,target_node,valid_from,valid_to,sign,mechanism,expected_lag_days,
                   elasticity_low,elasticity_high,status,posterior_probability,
                   independent_source_count,evidence_ids,validation_method,validation_stats,
                   generated_by_model,prompt_hash,evidence_cutoff_at)
                values
                  (:source_node,:target_node,:valid_from,:valid_to,:sign,:mechanism,:expected_lag_days,
                   :elasticity_low,:elasticity_high,:status,:posterior_probability,
                   :independent_source_count,cast(:evidence_ids as jsonb),:validation_method,
                   cast(:validation_stats as jsonb),:generated_by_model,:prompt_hash,:evidence_cutoff_at)
            """)
            for i in range(0, len(payload), 500):
                conn.execute(insert_sql, payload[i:i+500])

        concept_rows = len({p["target_node"] for p in payload})
        summary = {
            "model_version": MODEL_VERSION,
            "lexical_signal_count": len(keys),
            "eligible_lexical_signal_count": len(eligible_docs),
            "edges": len(payload),
            "canonical_concepts": concept_rows,
            "supported_descriptive": descriptive,
            "hypotheses": hypotheses,
            "predictive": 0,
            "causal": 0,
            "test_week": test_week.isoformat(),
            "decision_as_of": decision_as_of.isoformat(),
            "availability_quality": "KNOWN",
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{semantic_bridge}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {"ok": True, "experiment_id": experiment_id, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
