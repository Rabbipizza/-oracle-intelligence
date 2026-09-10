#!/usr/bin/env python3
"""Evidence-backed bottleneck tension with explicit P0-9 PIT clock mode.

LIVE behavior is unchanged. simulated_historical is fail-closed: nodes must be
supplied by the historical reconstruction at T; present-day structural nodes
are never reused. Evidence counts are rebuilt after filtering on
available_at_simulated <= T and are persisted only to the simulated table.
"""
from __future__ import annotations
import json, os, re
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy import create_engine, text

MODEL_VERSION="BOTTLENECK_TENSION_EVIDENCE_V2"
CLASSIFIER_VERSION="TENSION_CONTEXT_RULES_V2"
MIN_ISSUERS=2; MIN_EVIDENCE_ROWS=2
TENSION_KEYS={"CONSTRAINT","CAPACITY","BACKLOG","SUPPLY","ORDERS","DEMAND","SHORTAGE","LEAD_TIME","SCARCITY","ALLOCATION","PRICE"}
HARD_KEYS={"CONSTRAINT","CAPACITY","BACKLOG","SUPPLY","SHORTAGE","LEAD_TIME","SCARCITY","ALLOCATION"}
ALIASES={
 "Semiconductors":["semiconductor","chip"],"Grid Power Capacity":["grid","power capacity","power demand","electricity demand"],
 "High Bandwidth Memory":["high bandwidth memory","hbm"],"Advanced Semiconductor Packaging":["advanced packaging","wafer-level packaging","3d stacking"],
 "AI Accelerators":["ai accelerator","gpu","accelerator"],"Data Center Cooling":["data center cooling","cooling","thermal management","liquid cooling"],
 "High-Speed Networking":["high-speed networking","networking","network interface","switches","interconnect"],
}
REAL_PATTERNS=[r"is experiencing a period of supply constraints",r"shortages or delays in shipments",r"memory supply constraints and related price increases",r"has resulted in global supply constraints",r"constrained supply, extended lead times, and increasing costs",r"longer lead times for certain components",r"required to continue operating as energy-only resources under doe emergency orders",r"backlog for utility.{0,160}up 49%",r"pharmaceuticals face unique regulatory, technology and capacity constraints",r"lead time needed to identify and qualify a new supplier is typically lengthy",r"supply-demand imbalances.{0,160}advanced semiconductors",r"supply chain constraints and disruptions have in the past, and may in the future, increase costs"]
RESOLUTION_PATTERNS=[r"successfully mitigated",r"no longer constrained",r"constraints (?:were|have been) resolved",r"secured supply",r"manage our supply chain challenges through",r"unlocking capacity constraints"]
REAL_RX=[re.compile(p,re.I|re.S) for p in REAL_PATTERNS]; RESOLVED_RX=[re.compile(p,re.I|re.S) for p in RESOLUTION_PATTERNS]

def is_real_tension(excerpt:str)->bool:
    text=excerpt or ""
    return not any(rx.search(text) for rx in RESOLVED_RX) and any(rx.search(text) for rx in REAL_RX)

def eng(url):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def local_name(node:str)->str: return node.split(':',1)[1] if ':' in node else node

def _evaluate(conn,nodes,cutoff,mode):
    clock="available_at_simulated" if mode=="simulated_historical" else "coalesce(available_at,known_at,created_at)"
    evidence=conn.execute(text(f"select id,ticker,evidence_key,excerpt,source_url,{clock} effective_available_at from public.oracle_v4_sec_economic_evidence where {clock}<=:a and evidence_key=any(:keys) order by id"),{'a':cutoff,'keys':sorted(TENSION_KEYS)}).mappings().all()
    grouped=defaultdict(list); rejected=0
    for node in nodes:
        aliases=ALIASES.get(local_name(node),[local_name(node).lower()])
        for ev in evidence:
            ex=str(ev['excerpt'] or '')
            if not any(a.lower() in ex.lower() for a in aliases): continue
            if not is_real_tension(ex): rejected+=1; continue
            grouped[node].append(dict(ev))
    upgraded=[]
    for node,rows in grouped.items():
        issuers=sorted({str(r['ticker']) for r in rows if r['ticker']}); keys=sorted({str(r['evidence_key']) for r in rows}); hard=[r for r in rows if str(r['evidence_key']) in HARD_KEYS]
        if len(issuers)<MIN_ISSUERS or len(rows)<MIN_EVIDENCE_ROWS or not hard: continue
        upgraded.append({'bottleneck_node':node,'issuers':issuers,'evidence_ids':[int(r['id']) for r in rows],'evidence_count':len(rows),'evidence_types':keys,'hard_tension_count':len(hard)})
    return upgraded,rejected

def run(db_url:str,mode:str|None=None)->dict:
    mode=mode or os.environ.get('ORACLE_V6_PIT_MODE','live')
    if mode not in ('live','simulated_historical'): raise ValueError('invalid PIT mode')
    run_id=os.environ.get('GITHUB_RUN_ID')
    with eng(db_url).begin() as conn:
        if mode=='simulated_historical':
            raw_nodes=os.environ.get('ORACLE_V6_SIMULATED_BOTTLENECK_NODES','')
            raw_cutoff=os.environ.get('ORACLE_V6_SIMULATED_AS_OF','')
            if not raw_nodes or not raw_cutoff: raise RuntimeError('simulated_historical requires historically reconstructed nodes and ORACLE_V6_SIMULATED_AS_OF')
            nodes=list(json.loads(raw_nodes)); cutoff=datetime.fromisoformat(raw_cutoff.replace('Z','+00:00'))
            if cutoff.tzinfo is None: cutoff=cutoff.replace(tzinfo=timezone.utc)
            upgraded,rejected=_evaluate(conn,nodes,cutoff,mode)
            recon=os.environ.get('ORACLE_V6_RECONSTRUCTION_RUN','P0_9_MANUAL')
            conn.execute(text('delete from public.oracle_v6_simulated_tension_snapshots where reconstruction_run=:r and evaluation_date=:d'),{'r':recon,'d':cutoff.date()})
            for u in upgraded:
                conn.execute(text("""insert into public.oracle_v6_simulated_tension_snapshots(reconstruction_run,evaluation_date,bottleneck_node,issuer_count,evidence_count,hard_tension_count,evidence_ids,issuers,evidence_types,model_version) values(:r,:d,:b,:i,:e,:h,cast(:ids as jsonb),cast(:issuers as jsonb),cast(:types as jsonb),:m)"""),{'r':recon,'d':cutoff.date(),'b':u['bottleneck_node'],'i':len(u['issuers']),'e':u['evidence_count'],'h':u['hard_tension_count'],'ids':json.dumps(u['evidence_ids']),'issuers':json.dumps(u['issuers']),'types':json.dumps(u['evidence_types']),'m':MODEL_VERSION})
            return {'ok':True,'clock_mode':mode,'evaluation_as_of':cutoff.isoformat(),'upgraded_bottlenecks':len(upgraded),'upgraded':upgraded,'context_rejections':rejected,'live_tables_mutated':False}

        exp=int(conn.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one())
        q="select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e "+("and external_run_id=cast(:r as text) " if run_id else "")+"order by evaluation_as_of desc,id desc limit 1"; p={'e':exp}; p.update({'r':run_id} if run_id else {})
        cutoff=conn.execute(text(q),p).scalar_one_or_none()
        if cutoff is None: raise RuntimeError('no evaluation clock')
        nodes=[str(x) for x in conn.execute(text("select distinct bottleneck_node from public.oracle_v6_structural_bottlenecks where experiment_id=:e and evaluation_as_of=:a order by 1"),{'e':exp,'a':cutoff}).scalars().all()]
        upgraded,rejected=_evaluate(conn,nodes,cutoff,mode)
        conn.execute(text("update public.oracle_v6_structural_bottlenecks set structural_status='STRUCTURAL_CANDIDATE',forecast_probability=null where experiment_id=:e and evaluation_as_of=:a and structural_status='EVIDENCE_BACKED_TENSION'"),{'e':exp,'a':cutoff})
        for u in upgraded:
            meta={'tension_model_version':MODEL_VERSION,'classifier_version':CLASSIFIER_VERSION,'semantics':'independent_pit_sec_contextual_tension_evidence_not_probability','issuer_count':len(u['issuers']),'issuers':u['issuers'],'evidence_count':u['evidence_count'],'evidence_types':u['evidence_types'],'hard_tension_count':u['hard_tension_count'],'minimum_issuers':MIN_ISSUERS,'minimum_evidence_rows':MIN_EVIDENCE_ROWS,'probability_synthesized':False}
            conn.execute(text("update public.oracle_v6_structural_bottlenecks set structural_status='EVIDENCE_BACKED_TENSION',independent_source_count=:n,evidence_ids=cast(:ids as jsonb),metadata=coalesce(metadata,'{}'::jsonb)||cast(:m as jsonb),forecast_probability=null where experiment_id=:e and evaluation_as_of=:a and bottleneck_node=:b"),{'n':len(u['issuers']),'ids':json.dumps(u['evidence_ids']),'m':json.dumps(meta,sort_keys=True),'e':exp,'a':cutoff,'b':u['bottleneck_node']})
        suppliers=conn.execute(text("select distinct s.bottleneck_node,x.ticker from public.oracle_v6_structural_bottlenecks s join public.oracle_v6_structural_company_exposure x on x.experiment_id=s.experiment_id and x.evaluation_as_of=s.evaluation_as_of and x.bottleneck_node=s.bottleneck_node and x.exposure_role='SUPPLIER_CANDIDATE' where s.experiment_id=:e and s.evaluation_as_of=:a and s.structural_status='EVIDENCE_BACKED_TENSION' order by s.bottleneck_node,x.ticker"),{'e':exp,'a':cutoff}).mappings().all()
        by_b=defaultdict(list)
        for r in suppliers: by_b[str(r['bottleneck_node'])].append(str(r['ticker']))
        summary={'model_version':MODEL_VERSION,'classifier_version':CLASSIFIER_VERSION,'clock_mode':'live','evaluation_as_of':cutoff.isoformat(),'upgraded_bottlenecks':len(upgraded),'upgraded':upgraded,'context_rejections':rejected,'tension_supplier_tickers':sorted({t for ts in by_b.values() for t in ts}),'suppliers_by_bottleneck':dict(by_b),'probabilities_written':0,'state':'EVIDENCE_BACKED_TENSION_AVAILABLE' if upgraded else 'NO_EVIDENCE_BACKED_TENSION'}
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{bottleneck_tension}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,'experiment_id':exp,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
