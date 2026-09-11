#!/usr/bin/env python3
"""Semantic bridge for corrected Discovery V2.

Fail-closed: only REPLICATED_SIGNAL or CANDIDATE_FOR_SEMANTIC_BRIDGE from
FORMAL_COUNT_NULL_V2_PRETEST_FAMILY can seed structural concepts. EPHEMERAL
signals are never promoted. Associations are descriptive, not causal or
predictive.
"""
from __future__ import annotations
import json, os
from collections import defaultdict
from sqlalchemy import create_engine, text

DISCOVERY_MODEL='FORMAL_COUNT_NULL_V2_PRETEST_FAMILY'
MODEL_VERSION='SEMANTIC_BRIDGE_V2'
ELIGIBLE=('REPLICATED_SIGNAL','CANDIDATE_FOR_SEMANTIC_BRIDGE')
STRUCT_TYPES=('TREND','TECHNOLOGY','PARADIGM','BOTTLENECK','NEED','RESOURCE')

def eng(url):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def _summary(conn,e,w,a,state,keys=0,edges=0,concepts=0,supported=0,hyp=0):
    s={'model_version':MODEL_VERSION,'discovery_model_version':DISCOVERY_MODEL,
       'eligible_lexical_signal_count':keys,'edges':edges,'canonical_concepts':concepts,
       'supported_descriptive':supported,'hypotheses':hyp,'predictive':0,'causal':0,
       'test_week':w.isoformat(),'decision_as_of':a.isoformat(),'state':state,
       'lifecycle_policy':'REPLICATED_SIGNAL_OR_CANDIDATE_ONLY'}
    conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{semantic_bridge_v2}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(s,sort_keys=True),'e':e})
    return s

def run(db_url):
    with eng(db_url).begin() as conn:
        exp=conn.execute(text("""select id,(metrics->>'test_week')::date test_week,(metrics->'fdr'->>'as_of')::timestamptz decision_as_of from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version=:v and invalidated_at is null and metrics ? 'fdr' order by created_at desc,id desc limit 1"""),{'v':DISCOVERY_MODEL}).mappings().one_or_none()
        if not exp or exp['decision_as_of'] is None: raise RuntimeError('corrected Discovery V2 experiment unavailable')
        eid=int(exp['id']); week=exp['test_week']; asof=exp['decision_as_of']
        keys=[str(x) for x in conn.execute(text("""select trend_key from public.oracle_v6_signal_lifecycle where experiment_id=:e and lifecycle_state=any(:states) order by trend_key"""),{'e':eid,'states':list(ELIGIBLE)}).scalars().all()]
        conn.execute(text("delete from public.oracle_v6_graph_edges where generated_by_model=:m"),{'m':MODEL_VERSION})
        if not keys:
            return {'ok':True,'experiment_id':eid,**_summary(conn,eid,week,asof,'NO_REPLICATED_SIGNALS')}

        # Eligible lexical documents at the decision clock.
        rows=conn.execute(text("""select lower(o.canonical_term) signal_key,o.document_id::text document_id,greatest(o.created_at,d.fetched_at) avail,coalesce(sf.independence_group,'unmapped:'||coalesce(src.source_type,'unknown')) grp from public.oracle_v4_retro_term_occurrences o join public.oracle_raw_documents d on d.id=o.document_id left join public.oracle_sources src on src.id=d.source_id left join public.oracle_source_family_map sm on sm.source_type=src.source_type left join public.oracle_source_families sf on sf.family=sm.family where lower(o.canonical_term)=any(:keys) and o.event_date between :w and (:w+interval '6 days')::date and o.created_at<=:a and d.fetched_at<=:a"""),{'keys':[k.lower() for k in keys],'w':week,'a':asof}).mappings().all()
        docs=defaultdict(set)
        for r in rows: docs[str(r['signal_key'])].add(str(r['document_id']))
        if not docs:
            return {'ok':True,'experiment_id':eid,**_summary(conn,eid,week,asof,'NO_PIT_DOCUMENTS_FOR_REPLICATED_SIGNALS',len(keys))}

        links=conn.execute(text("""select lower(o.canonical_term) signal_key,o.document_id::text document_id,s.signal_type,s.canonical_name,greatest(o.created_at,d.fetched_at,s.available_at) avail,coalesce(sf.independence_group,'unmapped:'||coalesce(src.source_type,'unknown')) grp from public.oracle_v4_retro_term_occurrences o join public.oracle_raw_documents d on d.id=o.document_id join public.oracle_structural_signals s on s.document_id=o.document_id left join public.oracle_sources src on src.id=d.source_id left join public.oracle_source_family_map sm on sm.source_type=src.source_type left join public.oracle_source_families sf on sf.family=sm.family where lower(o.canonical_term)=any(:keys) and o.event_date between :w and (:w+interval '6 days')::date and o.created_at<=:a and d.fetched_at<=:a and s.available_at<=:a and s.observed_at<=:a and s.signal_type=any(:types) and s.canonical_name is not null and btrim(s.canonical_name)<>''"""),{'keys':[k.lower() for k in keys],'w':week,'a':asof,'types':list(STRUCT_TYPES)}).mappings().all()
        grouped={}
        for r in links:
            k=(str(r['signal_key']),str(r['signal_type']),str(r['canonical_name']))
            g=grouped.setdefault(k,{'docs':set(),'groups':set(),'av':[]})
            g['docs'].add(str(r['document_id'])); g['groups'].add(str(r['grp'])); g['av'].append(r['avail'])
        payload=[]; supported=0; hyp=0
        for (sig,typ,name),g in grouped.items():
            den=len(docs.get(sig,set())); linked=len(g['docs'])
            if den<=0 or linked<=0: continue
            independent=len(g['groups']); status='SUPPORTED_DESCRIPTIVE' if independent>=2 else 'HYPOTHESIS'
            supported+=status=='SUPPORTED_DESCRIPTIVE'; hyp+=status=='HYPOTHESIS'
            stats={'experiment_id':eid,'decision_as_of':asof.isoformat(),'eligible_documents':den,'linked_documents':linked,'independence_groups':sorted(g['groups']),'predictive_claim':False,'causal_claim':False,'lifecycle_required':list(ELIGIBLE)}
            payload.append({'src':f'LEXICAL_SIGNAL:{sig}','dst':f'{typ}:{name}','vf':min(g['av']),'st':status,'post':(linked+1.0)/(den+2.0),'n':independent,'ids':json.dumps(sorted(g['docs'])[:50]),'vs':json.dumps(stats,sort_keys=True),'cut':asof})
        if payload:
            ins=text("""insert into public.oracle_v6_graph_edges(source_node,target_node,valid_from,valid_to,sign,mechanism,status,posterior_probability,independent_source_count,evidence_ids,validation_method,validation_stats,generated_by_model,evidence_cutoff_at) values(:src,:dst,:vf,null,1,'SAME_DOCUMENT_STRUCTURAL_COOCCURRENCE_AFTER_TEMPORAL_REPLICATION',:st,:post,:n,cast(:ids as jsonb),'PIT_REPLICATED_SIGNAL_SAME_DOCUMENT_BETA_BINOMIAL',cast(:vs as jsonb),:m,:cut)""")
            for p in payload: p['m']=MODEL_VERSION
            conn.execute(ins,payload)
        s=_summary(conn,eid,week,asof,'REPLICATED_SIGNALS_PROCESSED',len(keys),len(payload),len({p['dst'] for p in payload}),int(supported),int(hyp))
        return {'ok':True,'experiment_id':eid,**s}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
