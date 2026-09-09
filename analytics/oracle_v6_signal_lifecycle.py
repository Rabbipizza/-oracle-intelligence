#!/usr/bin/env python3
"""P0-7 temporal replication lifecycle for Discovery signals.

A BH-selected signal starts EPHEMERAL. A temporal window counts as a distinct
replication only when BOTH are true:
  * >= configured calendar days since the previous qualifying window; and
  * >= configured number and ratio of genuinely new source documents.

The first qualifying window establishes the base observation. Repeated runs of
an identical family fingerprint are idempotent and spend no replication credit.
All document novelty is computed in bulk, avoiding N+1 database queries.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from sqlalchemy import create_engine, text

CONFIG_VERSION="ONLINE_ALPHA_SPENDING_BH_V1"
MODEL_VERSION="TREND_PERSISTENCE_V1"


def _engine(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)


def run(db_url:str)->dict:
    with _engine(db_url).begin() as conn:
        cfg=conn.execute(text("select * from public.oracle_v6_sequential_fdr_config where config_version=:c and active=true"),{'c':CONFIG_VERSION}).mappings().one()
        budget=conn.execute(text("select * from public.oracle_v6_sequential_run_budget order by sequence_index desc limit 1")).mappings().one()
        exp=int(budget['experiment_id']); week=budget['test_week']; as_of=budget['decision_as_of']; fp=str(budget['family_fingerprint'])
        selected=conn.execute(text("""
          select hypothesis_key,raw_p_value,adjusted_p_value
          from public.oracle_v6_multiple_testing
          where experiment_id=:e and as_of=:a and method='BENJAMINI_HOCHBERG' and selected=true
          order by hypothesis_key
        """),{'e':exp,'a':as_of}).mappings().all()
        keys=[str(r['hypothesis_key']) for r in selected]
        if not keys:
            summary={'config_version':CONFIG_VERSION,'family_fingerprint':fp,'test_week':week.isoformat(),'lifecycle_counts':{},'semantic_bridge_policy':'ONLY_REPLICATED_OR_CANDIDATE'}
            conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{signal_lifecycle}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
            return {'ok':True,**summary}

        # Upsert current lifecycle shells in one batch.
        conn.execute(text("""
          insert into public.oracle_v6_signal_lifecycle
            (experiment_id,trend_key,lifecycle_state,first_seen_at,last_seen_at,qualifying_replications,
             replication_dates,alpha_trace,last_family_fingerprint,last_adjusted_p_value,last_raw_p_value)
          values(:e,:t,'EPHEMERAL_SIGNAL',:a,:a,0,'[]'::jsonb,'[]'::jsonb,:f,:q,:p)
          on conflict(experiment_id,trend_key) do update set
            last_seen_at=excluded.last_seen_at,last_adjusted_p_value=excluded.last_adjusted_p_value,
            last_raw_p_value=excluded.last_raw_p_value,updated_at=now()
        """),[{'e':exp,'t':str(r['hypothesis_key']),'a':as_of,'f':fp,'q':r['adjusted_p_value'],'p':r['raw_p_value']} for r in selected])

        life_rows=conn.execute(text("""
          select l.*,m.raw_p_value,m.adjusted_p_value,
                 exists(select 1 from public.oracle_v6_signal_lifecycle_observations o where o.lifecycle_id=l.id and o.family_fingerprint=:f) already_observed
          from public.oracle_v6_signal_lifecycle l
          join public.oracle_v6_multiple_testing m on m.experiment_id=l.experiment_id and m.hypothesis_key=l.trend_key and m.as_of=:a and m.method='BENJAMINI_HOCHBERG' and m.selected=true
          where l.experiment_id=:e
        """),{'e':exp,'a':as_of,'f':fp}).mappings().all()
        pending=[r for r in life_rows if not r['already_observed']]
        if not pending:
            counts=dict(conn.execute(text("select lifecycle_state,count(*) from public.oracle_v6_signal_lifecycle where experiment_id=:e group by lifecycle_state"),{'e':exp}).all())
            return {'ok':True,'config_version':CONFIG_VERSION,'family_fingerprint':fp,'test_week':week.isoformat(),'lifecycle_counts':counts,'idempotent_reuse':True,'semantic_bridge_policy':'ONLY_REPLICATED_OR_CANDIDATE'}

        pending_keys=[str(r['trend_key']).lower() for r in pending]
        current_docs=defaultdict(set)
        for r in conn.execute(text("""
          select lower(o.canonical_term) trend_key,o.document_id::text document_id
          from public.oracle_v4_retro_term_occurrences o
          join public.oracle_raw_documents d on d.id=o.document_id
          where lower(o.canonical_term)=any(:keys)
            and o.event_date between :w and (:w + interval '6 days')::date
            and d.fetched_at is not null
        """),{'keys':pending_keys,'w':week}).mappings():
            current_docs[str(r['trend_key'])].add(str(r['document_id']))

        prev_meta={}
        for r in conn.execute(text("""
          select distinct on (l.id) l.id lifecycle_id,lower(l.trend_key) trend_key,o.test_week
          from public.oracle_v6_signal_lifecycle l
          join public.oracle_v6_signal_lifecycle_observations o on o.lifecycle_id=l.id and o.qualifies_as_independent_replication=true
          where l.id=any(:ids)
          order by l.id,o.test_week desc,o.id desc
        """),{'ids':[int(r['id']) for r in pending]}).mappings():
            prev_meta[int(r['lifecycle_id'])]=(str(r['trend_key']),r['test_week'])

        prev_docs=defaultdict(set)
        if prev_meta:
            for r in conn.execute(text("""
              with prev as (
                select distinct on (l.id) l.id lifecycle_id,lower(l.trend_key) trend_key,o.test_week
                from public.oracle_v6_signal_lifecycle l
                join public.oracle_v6_signal_lifecycle_observations o on o.lifecycle_id=l.id and o.qualifies_as_independent_replication=true
                where l.id=any(:ids)
                order by l.id,o.test_week desc,o.id desc
              )
              select p.lifecycle_id,x.document_id::text document_id
              from prev p
              join public.oracle_v4_retro_term_occurrences x
                on lower(x.canonical_term)=p.trend_key
               and x.event_date between p.test_week and (p.test_week + interval '6 days')::date
            """),{'ids':list(prev_meta)}).mappings():
                prev_docs[int(r['lifecycle_id'])].add(str(r['document_id']))

        obs_payload=[]; update_payload=[]
        min_days=int(cfg['min_replication_days']); min_new=int(cfg['min_new_documents']); min_ratio=float(cfg['min_new_document_ratio'])
        rep_threshold=int(cfg['min_qualifying_replications']); cand_threshold=int(cfg['candidate_replications'])
        for r in pending:
            lid=int(r['id']); term=str(r['trend_key']); docs=current_docs.get(term.lower(),set())
            prev=prev_meta.get(lid)
            if prev is None:
                new_docs=len(docs); ratio=1.0 if docs else 0.0; days=None
                qualifies=(len(docs)>=min_new)
            else:
                _,pw=prev; prior=prev_docs.get(lid,set()); new=docs-prior
                new_docs=len(new); ratio=(new_docs/len(docs)) if docs else 0.0; days=(week-pw).days
                qualifies=(days>=min_days and new_docs>=min_new and ratio>=min_ratio)
            reps=int(r['qualifying_replications'])+(1 if qualifies else 0)
            state='CANDIDATE_FOR_SEMANTIC_BRIDGE' if reps>=cand_threshold else ('REPLICATED_SIGNAL' if reps>=rep_threshold else 'EPHEMERAL_SIGNAL')
            dates=list(r['replication_dates'] or []); trace=list(r['alpha_trace'] or [])
            if qualifies: dates.append(week.isoformat())
            trace.append({'family_fingerprint':fp,'test_week':week.isoformat(),'allocated_alpha':float(budget['allocated_alpha']),'cumulative_allocated_alpha':float(budget['cumulative_allocated_alpha']),'qualifies':bool(qualifies),'new_document_count':new_docs,'new_document_ratio':ratio})
            obs_payload.append({'id':lid,'f':fp,'w':week,'a':as_of,'p':r['raw_p_value'],'q':r['adjusted_p_value'],'alpha':budget['allocated_alpha'],'docs':len(docs),'newdocs':new_docs,'ratio':ratio,'days':days,'qual':qualifies})
            update_payload.append({'id':lid,'s':state,'a':as_of,'reps':reps,'dates':json.dumps(dates),'trace':json.dumps(trace),'f':fp,'q':r['adjusted_p_value'],'p':r['raw_p_value']})

        conn.execute(text("""
          insert into public.oracle_v6_signal_lifecycle_observations
            (lifecycle_id,family_fingerprint,test_week,decision_as_of,bh_selected,raw_p_value,adjusted_p_value,
             allocated_alpha,document_count,new_document_count,new_document_ratio,days_since_last_qualifying,qualifies_as_independent_replication)
          values(:id,:f,:w,:a,true,:p,:q,:alpha,:docs,:newdocs,:ratio,:days,:qual)
          on conflict(lifecycle_id,family_fingerprint) do nothing
        """),obs_payload)
        conn.execute(text("""
          update public.oracle_v6_signal_lifecycle set lifecycle_state=:s,last_seen_at=:a,qualifying_replications=:reps,
            replication_dates=cast(:dates as jsonb),alpha_trace=cast(:trace as jsonb),last_family_fingerprint=:f,
            last_adjusted_p_value=:q,last_raw_p_value=:p,updated_at=now() where id=:id
        """),update_payload)

        conn.execute(text("""
          update public.oracle_v6_trend_probabilities p set state=l.lifecycle_state
          from public.oracle_v6_signal_lifecycle l
          where p.experiment_id=l.experiment_id and p.trend_key=l.trend_key and p.experiment_id=:e and p.model_version=:m
        """),{'e':exp,'m':MODEL_VERSION})
        counts=dict(conn.execute(text("select lifecycle_state,count(*) from public.oracle_v6_signal_lifecycle where experiment_id=:e group by lifecycle_state"),{'e':exp}).all())
        summary={'config_version':CONFIG_VERSION,'family_fingerprint':fp,'test_week':week.isoformat(),'min_replication_days':min_days,'min_new_document_ratio':min_ratio,'min_new_documents':min_new,'replicated_threshold':rep_threshold,'candidate_threshold':cand_threshold,'lifecycle_counts':counts,'semantic_bridge_policy':'ONLY_REPLICATED_OR_CANDIDATE','processed_observations':len(obs_payload)}
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{signal_lifecycle}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,**summary}


if __name__=='__main__':
    print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
