#!/usr/bin/env python3
"""ORACLE V6 structural bottleneck anticipation.

Necessary dependencies are inferred from trends already detected by ORACLE,
including native demographic trends. These are STRUCTURAL_CANDIDATE dependencies,
never scarcity probabilities; later evidence/calibration stages must validate them.
"""
from __future__ import annotations
import json, os, re
from sqlalchemy import create_engine, text

MODEL_VERSION = "STRUCTURAL_BOTTLENECK_V2"
RULES = [
    {
        "patterns": [r"artificial intelligence", r"ai infrastructure", r"data center", r"deep learning", r"machine learning"],
        "deps": [
            ("INFRASTRUCTURE:Grid Power Capacity", "ENERGY", "INFRASTRUCTURE_PREREQUISITE", "Large-scale compute requires reliable electrical power capacity."),
            ("COMPONENT:Power Transformers", "INFRASTRUCTURE", "PHYSICAL_INPUT", "New high-load compute facilities require grid interconnection and transformer capacity."),
            ("INFRASTRUCTURE:Data Center Cooling", "INFRASTRUCTURE", "INFRASTRUCTURE_PREREQUISITE", "Dense compute cannot operate continuously without thermal management."),
            ("COMPONENT:AI Accelerators", "COMPONENT", "TECHNICAL_PREREQUISITE", "Training and inference at scale require accelerator compute capacity."),
            ("COMPONENT:High Bandwidth Memory", "COMPONENT", "TECHNICAL_PREREQUISITE", "High-throughput accelerator workloads depend on memory bandwidth."),
            ("PROCESS:Advanced Semiconductor Packaging", "PROCESS", "CAPACITY_PREREQUISITE", "Leading accelerators depend on advanced packaging capacity."),
            ("INFRASTRUCTURE:High-Speed Networking", "INFRASTRUCTURE", "TECHNICAL_PREREQUISITE", "Distributed compute clusters depend on high-bandwidth interconnects."),
            ("RESOURCE:Copper", "RAW_MATERIAL", "PHYSICAL_INPUT", "Power distribution and data-center electrical infrastructure require substantial copper content."),
        ],
    },
    {
        "patterns": [r"physical ai", r"robot", r"autonomous system"],
        "deps": [
            ("COMPONENT:Semiconductors", "COMPONENT", "TECHNICAL_PREREQUISITE", "Autonomous machines require onboard compute and control semiconductors."),
            ("COMPONENT:Sensors", "COMPONENT", "TECHNICAL_PREREQUISITE", "Physical autonomy depends on perception and feedback sensors."),
            ("COMPONENT:Actuators and Motors", "COMPONENT", "PHYSICAL_INPUT", "Robotic motion requires actuators and motors."),
            ("RESOURCE:Rare Earth Magnets", "RAW_MATERIAL", "PHYSICAL_INPUT", "High-performance compact motors often depend on permanent magnets containing rare-earth materials."),
            ("COMPONENT:Power Electronics", "COMPONENT", "TECHNICAL_PREREQUISITE", "Electric actuation requires power conversion and control electronics."),
            ("COMPONENT:Batteries", "COMPONENT", "PHYSICAL_INPUT", "Mobile autonomous systems require onboard energy storage."),
        ],
    },
    {
        "patterns": [r"energy storage", r"battery"],
        "deps": [
            ("RESOURCE:Battery Materials", "RAW_MATERIAL", "PHYSICAL_INPUT", "Electrochemical storage requires active-material feedstocks whose exact mix depends on chemistry."),
            ("RESOURCE:Copper", "RAW_MATERIAL", "PHYSICAL_INPUT", "Battery systems and grid interconnection require conductive copper."),
            ("PROCESS:Cell Manufacturing Capacity", "CAPACITY", "CAPACITY_PREREQUISITE", "Storage deployment requires scalable cell manufacturing capacity."),
            ("INFRASTRUCTURE:Grid Interconnection", "INFRASTRUCTURE", "INFRASTRUCTURE_PREREQUISITE", "Grid-scale storage cannot monetize without interconnection capacity."),
        ],
    },
    {
        "patterns": [r"rare earth"],
        "deps": [
            ("PROCESS:Rare Earth Separation and Refining", "PROCESS", "CAPACITY_PREREQUISITE", "Mined rare-earth material requires separation and refining before high-value use."),
            ("PROCESS:Permanent Magnet Manufacturing", "PROCESS", "CAPACITY_PREREQUISITE", "Magnet applications require downstream alloying and magnet manufacturing capacity."),
        ],
    },
    {
        "patterns": [r"semiconductor", r"chip"],
        "deps": [
            ("TECHNOLOGY:Lithography Equipment", "TECHNOLOGY", "TECHNICAL_PREREQUISITE", "Advanced semiconductor manufacturing requires lithography capability."),
            ("PROCESS:Advanced Semiconductor Packaging", "PROCESS", "CAPACITY_PREREQUISITE", "Advanced chips increasingly require complex packaging and integration."),
            ("RESOURCE:Semiconductor Materials and Gases", "RAW_MATERIAL", "PHYSICAL_INPUT", "Wafer fabrication depends on specialty materials and process gases."),
        ],
    },
    # Demography is itself a trend family. These rules translate demographic
    # trajectories into economically necessary capacity/input candidates.
    {
        "patterns": [r"aging acceleration", r"working-age population contraction", r"low fertility"],
        "deps": [
            ("CAPACITY:Healthcare Delivery Capacity", "CAPACITY", "CAPACITY_PREREQUISITE", "An aging population raises recurring demand for healthcare delivery capacity."),
            ("CAPACITY:Care Workforce", "CAPACITY", "LABOR_PREREQUISITE", "Aging and labor-force contraction increase pressure on scarce care labor."),
            ("TECHNOLOGY:Industrial Automation", "TECHNOLOGY", "PRODUCTIVITY_PREREQUISITE", "A shrinking working-age population raises the structural need for automation and labor substitution."),
            ("TECHNOLOGY:Robotics", "TECHNOLOGY", "PRODUCTIVITY_PREREQUISITE", "Labor scarcity increases the economic value of robotic substitution and assistance."),
            ("COMPONENT:Medical Devices", "COMPONENT", "DEMAND_PREREQUISITE", "Older populations require more diagnostics, monitoring, intervention and chronic-care equipment."),
        ],
    },
    {
        "patterns": [r"urbanization expansion", r"population growth", r"youth bulge"],
        "deps": [
            ("INFRASTRUCTURE:Grid Power Capacity", "ENERGY", "INFRASTRUCTURE_PREREQUISITE", "Population concentration and growth require additional electricity generation and grid capacity."),
            ("COMPONENT:Power Transformers", "INFRASTRUCTURE", "PHYSICAL_INPUT", "Grid expansion requires transformer capacity."),
            ("RESOURCE:Copper", "RAW_MATERIAL", "PHYSICAL_INPUT", "Urban electrical, transport and building infrastructure requires substantial copper."),
            ("INFRASTRUCTURE:Water and Wastewater", "INFRASTRUCTURE", "INFRASTRUCTURE_PREREQUISITE", "Dense growing cities require expanded water and wastewater systems."),
            ("CAPACITY:Housing Construction", "CAPACITY", "CAPACITY_PREREQUISITE", "Population and household growth require additional housing supply."),
            ("INFRASTRUCTURE:Telecom Networks", "INFRASTRUCTURE", "INFRASTRUCTURE_PREREQUISITE", "Growing urban populations require communications capacity."),
        ],
    },
    {
        "patterns": [r"migration shift"],
        "deps": [
            ("CAPACITY:Housing Construction", "CAPACITY", "CAPACITY_PREREQUISITE", "Large migration flows can rapidly change local housing demand."),
            ("INFRASTRUCTURE:Grid Power Capacity", "ENERGY", "INFRASTRUCTURE_PREREQUISITE", "Population redistribution changes regional electricity demand and grid requirements."),
            ("INFRASTRUCTURE:Transport Capacity", "INFRASTRUCTURE", "INFRASTRUCTURE_PREREQUISITE", "Population redistribution can require transport expansion in destination regions."),
        ],
    },
]

def _engine(db_url: str):
    if db_url.startswith("postgres://"): db_url = "postgresql+psycopg://" + db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"): db_url = "postgresql+psycopg://" + db_url[len("postgresql://"):]
    else: raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url, pool_pre_ping=True)

def run(db_url: str) -> dict:
    engine = _engine(db_url); run_id = os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp = conn.execute(text("""select id,(metrics->>'decision_as_of')::timestamptz signal_available_at from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1""")).mappings().one()
        experiment_id=int(exp['id']); signal_at=exp['signal_available_at']
        eval_at=None
        if run_id: eval_at=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r"),{'e':experiment_id,'r':run_id}).scalar_one_or_none()
        if eval_at is None: eval_at=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1"),{'e':experiment_id}).scalar_one()
        concept_rows=conn.execute(text("""
          select distinct regexp_replace(target_node,'^[A-Z_]+:','','') concept, 'DISCOVERY' family
          from public.oracle_v6_graph_edges
          where evidence_cutoff_at=:signal_at and target_node ~ '^(TREND|PARADIGM|TECHNOLOGY|RESOURCE):'
          union
          select distinct trend_key,'CAPTURE' from public.oracle_v6_company_capture where as_of=:eval_at
          union
          select distinct trend_key,'DEMOGRAPHY' from public.oracle_v6_demographic_trends
          where experiment_id=:e and evaluation_as_of=:eval_at and status='STRUCTURAL_TREND_LIVE_CONTEXT'
        """),{'signal_at':signal_at,'eval_at':eval_at,'e':experiment_id}).mappings().all()
        rows=[]; seen=set(); demographic_count=0
        for cr in concept_rows:
            raw=str(cr['concept']).strip(); family=str(cr['family']); normalized=raw.lower()
            trend_node=raw if raw.startswith('DEMOGRAPHY:') else f"TREND:{raw}"
            if family=='DEMOGRAPHY': demographic_count+=1
            for rule in RULES:
                if not any(re.search(p, normalized, flags=re.I) for p in rule['patterns']): continue
                rule_id='|'.join(rule['patterns'])
                for bottleneck_node,category,dep_type,reason in rule['deps']:
                    key=(trend_node,bottleneck_node)
                    if key in seen: continue
                    seen.add(key)
                    rows.append({'experiment_id':experiment_id,'trend_node':trend_node,'bottleneck_node':bottleneck_node,'category':category,'dependency_type':dep_type,'necessity_reason':reason,'derivation_rule':rule_id,'signal_available_at':signal_at,'evaluation_as_of':eval_at,'metadata':json.dumps({'model_version':MODEL_VERSION,'semantics':'necessary_dependency_candidate_not_scarcity_claim','probability_synthesized':False,'source_concept':raw,'source_family':family},sort_keys=True)})
        conn.execute(text("delete from public.oracle_v6_structural_bottlenecks where experiment_id=:e and evaluation_as_of=:a"),{'e':experiment_id,'a':eval_at})
        if rows:
            conn.execute(text("""insert into public.oracle_v6_structural_bottlenecks (experiment_id,trend_node,bottleneck_node,category,dependency_type,structural_status,necessity_reason,derivation_rule,signal_available_at,evaluation_as_of,metadata) values (:experiment_id,:trend_node,:bottleneck_node,:category,:dependency_type,'STRUCTURAL_CANDIDATE',:necessity_reason,:derivation_rule,:signal_available_at,:evaluation_as_of,cast(:metadata as jsonb))"""),rows)
        by_category=dict(conn.execute(text("select category,count(*) from public.oracle_v6_structural_bottlenecks where experiment_id=:e and evaluation_as_of=:a group by category order by category"),{'e':experiment_id,'a':eval_at}).all())
        summary={'model_version':MODEL_VERSION,'evaluation_as_of':eval_at.isoformat(),'signal_available_at':signal_at.isoformat() if signal_at else None,'detected_concepts_considered':len(concept_rows),'demographic_trends_considered':demographic_count,'structural_candidates':len(rows),'by_category':by_category,'probabilities_written':0,'state':'STRUCTURAL_CANDIDATES_AVAILABLE' if rows else 'NO_STRUCTURAL_DEPENDENCY_RULE_MATCH'}
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{structural_bottlenecks}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':experiment_id})
    return {'ok':True,'experiment_id':experiment_id,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
