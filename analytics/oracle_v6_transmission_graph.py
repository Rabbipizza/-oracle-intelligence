#!/usr/bin/env python3
"""ORACLE V6 point-in-time descriptive economic-transmission graph.

This stage does NOT claim causality. It aggregates structured signal links that
were actually available by the latest scientific decision time. Edges with
support from >=2 distinct information-independence groups are
SUPPORTED_DESCRIPTIVE; otherwise they remain HYPOTHESIS. Predictive/causal
promotion belongs to later tests.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import create_engine, text

MODEL_VERSION = "TRANSMISSION_DESCRIPTIVE_V1"
MAX_EVIDENCE_IDS = 50


@dataclass
class EdgeEvidence:
    src_type: str
    src_name: str
    relation_type: str
    dst_type: str
    dst_name: str
    first_available: datetime | None = None
    last_available: datetime | None = None
    confidences: list[float] = field(default_factory=list)
    document_ids: set[str] = field(default_factory=set)
    independence_groups: set[str] = field(default_factory=set)
    link_ids: list[str] = field(default_factory=list)

    def add(self, row) -> None:
        available = row["available_at"]
        if self.first_available is None or available < self.first_available:
            self.first_available = available
        if self.last_available is None or available > self.last_available:
            self.last_available = available
        self.confidences.append(float(row["confidence"]))
        self.document_ids.add(str(row["document_id"]))
        self.independence_groups.add(str(row["independence_group"]))
        if len(self.link_ids) < MAX_EVIDENCE_IDS:
            self.link_ids.append(str(row["id"]))


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
                   (e.metrics->'fdr'->>'as_of')::timestamptz as decision_as_of
            from public.oracle_v6_experiments e
            where e.model_family='COUNT_NULL_MODEL'
              and e.model_version='FORMAL_COUNT_NULL_V1'
              and e.invalidated_at is null
              and e.metrics ? 'fdr'
              and e.metrics ? 'test_week'
            order by e.created_at desc,e.id desc limit 1
        """)).mappings().one_or_none()
        if not exp or exp["decision_as_of"] is None:
            raise RuntimeError("latest PIT scientific decision time unavailable")
        experiment_id = int(exp["id"])
        test_week = exp["test_week"]
        decision_as_of = exp["decision_as_of"]

        rows = conn.execute(text("""
            select l.id,l.document_id,l.src_type,l.src_name,l.relation_type,
                   l.dst_type,l.dst_name,l.confidence,l.available_at,
                   coalesce(sf.independence_group,
                            'unmapped:' || coalesce(src.source_type,'unknown')) as independence_group
            from public.oracle_signal_links l
            join public.oracle_raw_documents d on d.id=l.document_id
            left join public.oracle_sources src on src.id=d.source_id
            left join public.oracle_source_family_map sm on sm.source_type=src.source_type
            left join public.oracle_source_families sf on sf.family=sm.family
            where l.available_at is not null
              and l.available_at <= :decision_as_of
              and d.fetched_at <= :decision_as_of
            order by l.available_at,l.id
        """), {"decision_as_of": decision_as_of}).mappings().all()

        grouped: dict[tuple[str,str,str,str,str], EdgeEvidence] = {}
        for r in rows:
            key = (
                str(r["src_type"]), str(r["src_name"]), str(r["relation_type"]),
                str(r["dst_type"]), str(r["dst_name"]),
            )
            if key not in grouped:
                grouped[key] = EdgeEvidence(*key)
            grouped[key].add(r)

        payload = []
        descriptive = 0
        hypotheses = 0
        for e in grouped.values():
            independent_sources = len(e.independence_groups)
            status = "SUPPORTED_DESCRIPTIVE" if independent_sources >= 2 else "HYPOTHESIS"
            if status == "SUPPORTED_DESCRIPTIVE":
                descriptive += 1
            else:
                hypotheses += 1
            stats = {
                "experiment_id": experiment_id,
                "test_week": test_week.isoformat() if test_week else None,
                "decision_as_of": decision_as_of.isoformat(),
                "availability_quality": "KNOWN",
                "relation_type": e.relation_type,
                "document_count": len(e.document_ids),
                "independent_source_family_count": independent_sources,
                "independence_groups": sorted(e.independence_groups),
                "mean_extractor_confidence": sum(e.confidences) / len(e.confidences),
                "support_policy": ">=2 independence groups => SUPPORTED_DESCRIPTIVE; never causal",
                "causal_claim": False,
            }
            payload.append({
                "source_node": f"{e.src_type}:{e.src_name}",
                "target_node": f"{e.dst_type}:{e.dst_name}",
                "valid_from": e.first_available,
                "valid_to": None,
                "sign": None,
                "mechanism": e.relation_type,
                "expected_lag_days": None,
                "elasticity_low": None,
                "elasticity_high": None,
                "status": status,
                "posterior_probability": None,
                "independent_source_count": independent_sources,
                "evidence_ids": json.dumps(e.link_ids),
                "validation_method": "MULTI_INDEPENDENCE_GROUP_REPLICATION" if independent_sources >= 2 else "SINGLE_GROUP_HYPOTHESIS",
                "validation_stats": json.dumps(stats, sort_keys=True),
                "generated_by_model": MODEL_VERSION,
                "prompt_hash": None,
                "evidence_cutoff_at": decision_as_of,
            })

        conn.execute(
            text("delete from public.oracle_v6_graph_edges where generated_by_model=:model"),
            {"model": MODEL_VERSION},
        )
        if payload:
            conn.execute(text("""
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
            """), payload)

        summary = {
            "model_version": MODEL_VERSION,
            "edges": len(payload),
            "supported_descriptive": descriptive,
            "hypotheses": hypotheses,
            "predictive": 0,
            "causal": 0,
            "test_week": test_week.isoformat() if test_week else None,
            "decision_as_of": decision_as_of.isoformat(),
            "availability_quality": "KNOWN",
            "independence_unit": "oracle_source_families.independence_group",
        }
        conn.execute(text("""
            update public.oracle_v6_experiments
            set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{transmission_graph}',cast(:summary as jsonb),true)
            where id=:experiment_id
        """), {"summary": json.dumps(summary, sort_keys=True), "experiment_id": experiment_id})

    return {"ok": True, "experiment_id": experiment_id, **summary}


def main() -> None:
    print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL", "")), sort_keys=True))


if __name__ == "__main__":
    main()
