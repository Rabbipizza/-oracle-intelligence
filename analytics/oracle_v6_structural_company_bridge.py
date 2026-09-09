#!/usr/bin/env python3
"""ORACLE V6 structural bottleneck -> company evidence bridge.

This stage does NOT score scarcity, capture, expected return, or investment merit.
It only links a STRUCTURAL_CANDIDATE dependency to a listed company when a
point-in-time SEC evidence excerpt already in ORACLE explicitly supports the
relevant product/capacity/infrastructure exposure under a controlled rule.
"""
from __future__ import annotations

import json
import os
import re
from sqlalchemy import create_engine, text

MODEL_VERSION = "STRUCTURAL_COMPANY_BRIDGE_V1"

# Rule = acceptable evidence keys + terms that must occur in the SEC excerpt.
# Keeping this explicit avoids opaque fuzzy/LLM matching in a PIT backtest path.
RULES = {
    "AI Accelerators": ({"AI","GPU"}, r"\b(accelerator|accelerators|gpu|graphics processing)\b"),
    "High Bandwidth Memory": ({"HBM","PACKAGING","CONSTRAINT"}, r"\b(hbm|high bandwidth memory|memory supply)\b"),
    "Advanced Semiconductor Packaging": ({"PACKAGING","HBM"}, r"\b(packag|3d stacking|wafer-level)"),
    "Grid Power Capacity": ({"POWER","DATA_CENTER","CAPACITY","DEMAND"}, r"\b(data center|electrical power|power distribution|grid|utility)\b"),
    "Power Transformers": ({"POWER","DATA_CENTER","CAPACITY"}, r"\b(transformer|electrical power|power distribution|modular power|data center)\b"),
    "Data Center Cooling": ({"COOLING","DATA_CENTER"}, r"\b(cooling|thermal|heat|data center)\b"),
    "High-Speed Networking": ({"DATA_CENTER"}, r"\b(network|switch|interconnect|connectivity|data center)\b"),
    "Semiconductors": ({"AI","SUPPLY","CONSTRAINT","CAPACITY"}, r"\b(semiconductor|chip|processor|foundry|wafer)\b"),
    "Lithography Equipment": ({"CAPACITY","SUPPLY"}, r"\b(lithograph|wafer fabrication|semiconductor manufacturing)\b"),
    "Cell Manufacturing Capacity": ({"CAPACITY"}, r"\b(cell|battery|production capacity|manufacturing capacity)\b"),
    "Grid Interconnection": ({"POWER","CAPACITY"}, r"\b(grid|interconnection|utility|electrical power)\b"),
    "Battery Materials": ({"SUPPLY","CONSTRAINT"}, r"\b(battery|lithium|nickel|graphite|cathode|anode)\b"),
    "Permanent Magnet Manufacturing": ({"CAPACITY","SUPPLY"}, r"\b(permanent magnet|magnet manufacturing|rare earth)\b"),
    "Rare Earth Separation and Refining": ({"CAPACITY","SUPPLY"}, r"\b(rare earth|separation|refining)\b"),
    "Semiconductor Materials and Gases": ({"SUPPLY","CONSTRAINT"}, r"\b(wafer|substrate|process gas|materials supplier|semiconductor)\b"),
    "Actuators and Motors": ({"AI","DEMAND","SUPPLY"}, r"\b(actuator|motor|robot|robotic)\b"),
    "Power Electronics": ({"POWER","AI"}, r"\b(power electronics|power conversion|robot|robotic)\b"),
    "Sensors": ({"AI","DEMAND"}, r"\b(sensor|perception|camera|robot|robotic)\b"),
    "Batteries": ({"SUPPLY","DEMAND","AI"}, r"\b(battery|batteries|robot|robotic)\b"),
    "Rare Earth Magnets": ({"SUPPLY","CONSTRAINT"}, r"\b(rare earth|permanent magnet|magnet)\b"),
}


def engine_for(url: str):
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    else:
        raise ValueError("PostgreSQL URL required")
    return create_engine(url, pool_pre_ping=True)


def local_name(node: str) -> str:
    return node.split(":", 1)[1] if ":" in node else node


def run(db_url: str) -> dict:
    eng = engine_for(db_url)
    run_id = os.environ.get("GITHUB_RUN_ID")
    with eng.begin() as conn:
        exp = conn.execute(text("""
          select id from public.oracle_v6_experiments
          where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1'
            and invalidated_at is null order by created_at desc,id desc limit 1
        """)).scalar_one()
        if run_id:
            evaluation_as_of = conn.execute(text("""
              select evaluation_as_of from public.oracle_v6_evaluation_runs
              where experiment_id=:e and external_run_id=cast(:r as text)
              order by evaluation_as_of desc,id desc limit 1
            """), {"e": exp, "r": run_id}).scalar_one_or_none()
        else:
            evaluation_as_of = conn.execute(text("""
              select evaluation_as_of from public.oracle_v6_evaluation_runs
              where experiment_id=:e order by evaluation_as_of desc,id desc limit 1
            """), {"e": exp}).scalar_one_or_none()
        if evaluation_as_of is None:
            raise RuntimeError("no evaluation clock")

        deps = conn.execute(text("""
          select trend_node,bottleneck_node
          from public.oracle_v6_structural_bottlenecks
          where experiment_id=:e and evaluation_as_of=:a
            and structural_status='STRUCTURAL_CANDIDATE'
          order by trend_node,bottleneck_node
        """), {"e": exp, "a": evaluation_as_of}).mappings().all()

        # Restrict to the investable universe as of the evaluation date.
        universe = set(conn.execute(text("select ticker from public.oracle_v6_universe_as_of(cast(:d as date))"),
                                    {"d": evaluation_as_of.date()}).scalars().all())
        evidence = conn.execute(text("""
          select id,ticker,evidence_key,excerpt,source_url,available_at
          from public.oracle_v4_sec_economic_evidence
          where available_at is not null and available_at<=:a
          order by available_at desc,id desc
        """), {"a": evaluation_as_of}).mappings().all()

        conn.execute(text("delete from public.oracle_v6_structural_company_exposure where experiment_id=:e and evaluation_as_of=:a"),
                     {"e": exp, "a": evaluation_as_of})
        rows = []
        seen = set()
        for dep in deps:
            name = local_name(str(dep["bottleneck_node"]))
            rule = RULES.get(name)
            if not rule:
                continue
            keys, pattern = rule
            rx = re.compile(pattern, re.I)
            for ev in evidence:
                ticker = str(ev["ticker"] or "")
                if ticker not in universe or str(ev["evidence_key"] or "") not in keys:
                    continue
                excerpt = str(ev["excerpt"] or "")
                if not rx.search(excerpt):
                    continue
                k = (str(dep["trend_node"]), str(dep["bottleneck_node"]), ticker, int(ev["id"]))
                if k in seen:
                    continue
                seen.add(k)
                rows.append({
                    "experiment_id": int(exp), "evaluation_as_of": evaluation_as_of,
                    "trend_node": str(dep["trend_node"]), "bottleneck_node": str(dep["bottleneck_node"]),
                    "ticker": ticker, "evidence_key": str(ev["evidence_key"]), "evidence_id": int(ev["id"]),
                    "evidence_available_at": ev["available_at"], "source_url": ev["source_url"],
                    "excerpt": excerpt, "mapping_rule": f"{name}:{','.join(sorted(keys))}:{pattern}",
                })
        if rows:
            conn.execute(text("""
              insert into public.oracle_v6_structural_company_exposure
              (experiment_id,evaluation_as_of,trend_node,bottleneck_node,ticker,exposure_status,
               evidence_key,evidence_id,evidence_available_at,source_url,excerpt,mapping_rule)
              values (:experiment_id,:evaluation_as_of,:trend_node,:bottleneck_node,:ticker,
               'STRUCTURAL_EXPOSURE_CANDIDATE',:evidence_key,:evidence_id,:evidence_available_at,
               :source_url,:excerpt,:mapping_rule)
              on conflict do nothing
            """), rows)
        stats = conn.execute(text("""
          select count(*) evidence_links,count(distinct ticker) tickers,
                 count(distinct bottleneck_node) bottlenecks,count(distinct trend_node) trends
          from public.oracle_v6_structural_company_exposure
          where experiment_id=:e and evaluation_as_of=:a
        """), {"e": exp, "a": evaluation_as_of}).mappings().one()
        summary = {"model_version": MODEL_VERSION, "evaluation_as_of": evaluation_as_of.isoformat(),
                   **{k:int(v or 0) for k,v in stats.items()}, "probabilities_written":0,
                   "state":"STRUCTURAL_EXPOSURE_CANDIDATES_AVAILABLE" if stats["evidence_links"] else "NO_STRUCTURAL_COMPANY_LINKS"}
        conn.execute(text("""
          update public.oracle_v6_experiments
          set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{structural_company_bridge}',cast(:s as jsonb),true)
          where id=:e
        """), {"s": json.dumps(summary,sort_keys=True), "e": exp})
    return {"ok": True, "experiment_id": int(exp), **summary}

if __name__ == '__main__':
    print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')), sort_keys=True))
