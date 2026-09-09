#!/usr/bin/env python3
"""Materialize descriptive economic-capture evidence for tension-backed suppliers.

No capture probability or incremental revenue forecast is written. A supplier is
only marked CAPTURE_EVIDENCE_BACKED when independent PIT SEC filings show both
commercial pull (demand/orders/backlog) and ability/constraint evidence
(capacity/supply/constraint). Pricing evidence is recorded separately as a
stronger capture-quality signal, never synthesized into a probability here.
"""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, text

MODEL_VERSION='ECONOMIC_CAPTURE_EVIDENCE_V2'
PULL_KEYS={'DEMAND','ORDERS','BACKLOG'}
ABILITY_KEYS={'CAPACITY','SUPPLY','CONSTRAINT','LEAD_TIME'}
PRICING_KEYS={'PRICE'}
ALIASES={
 'Semiconductors':['semiconductor','chip'],
 'Grid Power Capacity':['grid','power capacity','power demand','electricity demand','electrical power','power distribution'],
 'High Bandwidth Memory':['high bandwidth memory','hbm'],
 'Advanced Semiconductor Packaging':['advanced packaging','wafer-level packaging','3d stacking'],
 'AI Accelerators':['ai accelerator','gpu','accelerator'],
 'Data Center Cooling':['data center cooling','cooling','thermal management','liquid cooling'],
 'High-Speed Networking':['high-speed networking','networking','network interface','switches','interconnect'],
}

def eng(url):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def local_name(node): return node.split(':',1)[1] if ':' in node else node

def run(db_url):
    run_id=os.environ.get('GITHUB_RUN_ID')
    with eng(db_url).begin() as conn:
        exp=int(conn.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one())
        cutoff=None
        if run_id:
            cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r order by evaluation_as_of desc limit 1"),{'e':exp,'r':run_id}).scalar_one_or_none()
        if cutoff is None:
            cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1"),{'e':exp}).scalar_one_or_none()
        if cutoff is None: raise RuntimeError('no evaluation clock')
        suppliers=conn.execute(text("select distinct s.bottleneck_node,x.ticker from public.oracle_v6_structural_bottlenecks s join public.oracle_v6_structural_company_exposure x on x.experiment_id=s.experiment_id and x.evaluation_as_of=s.evaluation_as_of and x.bottleneck_node=s.bottleneck_node and x.exposure_role='SUPPLIER_CANDIDATE' where s.experiment_id=:e and s.evaluation_as_of=:a and s.structural_status='EVIDENCE_BACKED_TENSION' order by s.bottleneck_node,x.ticker"),{'e':exp,'a':cutoff}).mappings().all()
        all_keys=sorted(PULL_KEYS|ABILITY_KEYS|PRICING_KEYS)
        raw=conn.execute(text("select id,document_id,ticker,evidence_key,excerpt,source_url,coalesce(available_at,known_at,created_at) available_at from public.oracle_v4_sec_economic_evidence where coalesce(available_at,known_at,created_at)<=:a and evidence_key=any(:keys) order by id"),{'a':cutoff,'keys':all_keys}).mappings().all()
        conn.execute(text("delete from public.oracle_v6_economic_capture_evidence where experiment_id=:e and evaluation_as_of=:a"),{'e':exp,'a':cutoff})
        payload=[]
        for s in suppliers:
            node=str(s['bottleneck_node']); ticker=str(s['ticker']); aliases=ALIASES.get(local_name(node),[local_name(node).lower()])
            ev=[]
            for r in raw:
                if str(r['ticker'])!=ticker: continue
                ex=str(r['excerpt'] or '').lower()
                if any(a.lower() in ex for a in aliases): ev.append(dict(r))
            docs={str(r['document_id']) for r in ev if r['document_id'] is not None}
            keys={str(r['evidence_key']) for r in ev}
            pull=bool(keys & PULL_KEYS); ability=bool(keys & ABILITY_KEYS); pricing=bool(keys & PRICING_KEYS)
            backed=len(docs)>=2 and pull and ability
            meta={'semantics':'descriptive_capture_evidence_not_probability','independent_documents':len(docs),'pull_evidence':pull,'ability_evidence':ability,'pricing_evidence':pricing,'probability_synthesized':False}
            payload.append({'experiment_id':exp,'evaluation_as_of':cutoff,'bottleneck_node':node,'ticker':ticker,'status':'CAPTURE_EVIDENCE_BACKED' if backed else 'CAPTURE_EVIDENCE_CANDIDATE','n':len(docs),'types':json.dumps(sorted(keys)),'ids':json.dumps([int(r['id']) for r in ev]),'pull':pull,'ability':ability,'pricing':pricing,'model':MODEL_VERSION,'meta':json.dumps(meta,sort_keys=True)})
        if payload:
            conn.execute(text("insert into public.oracle_v6_economic_capture_evidence (experiment_id,evaluation_as_of,bottleneck_node,ticker,evidence_status,independent_evidence_count,evidence_types,evidence_ids,supplier_role_confirmed,demand_backlog_evidence,capacity_evidence,pricing_power_evidence,model_version,metadata) values (:experiment_id,:evaluation_as_of,:bottleneck_node,:ticker,:status,:n,cast(:types as jsonb),cast(:ids as jsonb),true,:pull,:ability,:pricing,:model,cast(:meta as jsonb))"),payload)
        backed=sum(1 for p in payload if p['status']=='CAPTURE_EVIDENCE_BACKED')
        priced=sum(1 for p in payload if p['pricing'])
        summary={'model_version':MODEL_VERSION,'evaluation_as_of':cutoff.isoformat(),'tension_supplier_candidates':len(payload),'capture_evidence_backed':backed,'pricing_evidence_candidates':priced,'capture_probabilities_written':0,'pricing_power_probabilities_written':0,'state':'CAPTURE_EVIDENCE_AVAILABLE_UNCALIBRATED' if payload else 'NO_TENSION_SUPPLIER_CANDIDATES'}
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{economic_capture_evidence}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,'experiment_id':exp,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
