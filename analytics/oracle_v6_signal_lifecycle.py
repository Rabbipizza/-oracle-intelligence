#!/usr/bin/env python3
"""P0-7 temporal replication lifecycle for Discovery signals.

A BH-selected signal starts EPHEMERAL. A temporal window counts as a new
independent replication only when BOTH are true:
  1) at least MIN_REPLICATION_DAYS have elapsed since the previous qualifying
     window for that signal; and
  2) the current window contains at least MIN_NEW_DOCUMENTS documents not seen
     in the previous qualifying window AND their ratio is >= MIN_NEW_DOCUMENT_RATIO.

The first selected window establishes the base observation (replication count=1).
The second independent window promotes to REPLICATED_SIGNAL; the third promotes
to CANDIDATE_FOR_SEMANTIC_BRIDGE. Re-runs of the same family fingerprint are
idempotent and cannot manufacture replication by repeated peeking.
"""
from __future__ import annotations

import json
import os
from datetime import timedelta
from sqlalchemy import create_engine, text

CONFIG_VERSION = "ONLINE_ALPHA_SPENDING_BH_V1"
MODEL_VERSION = "TREND_PERSISTENCE_V1"


def _engine(db_url: str):
    if db_url.startswith('postgres://'):
        db_url='postgresql+psycopg://'+db_url[len('postgres://'):]
    elif db_url.startswith('postgresql://'):
        db_url='postgresql+psycopg://'+db_url[len('postgresql://'):]
    else:
        raise ValueError('PostgreSQL URL required')
    return create_engine(db_url,pool_pre_ping=True)


def _docs(conn, term: str, week):
    rows=conn.execute(text("""
      select distinct o.document_id::text
      from public.oracle_v4_retro_term_occurrences o
      join public.oracle_raw_documents d on d.id=o.document_id
      where lower(o.canonical_term)=lower(:term)
        and o.event_date between :w and (:w + interval '6 days')::date
        and d.fetched_at is not null
    """), {'term':term,'w':week}).scalars().all()
    return set(map(str,rows))


def run(db_url: str) -> dict:
    with _engine(db_url).begin() as conn:
        cfg=conn.execute(text("""select * from public.oracle_v6_sequential_fdr_config
                                 where config_version=:c and active=true"""),{'c':CONFIG_VERSION}).mappings().one()
        budget=conn.execute(text("""select * from public.oracle_v6_sequential_run_budget
                                    order by sequence_index desc limit 1""")).mappings().one()
        exp=int(budget['experiment_id']); week=budget['test_week']; as_of=budget['decision_as_of']; fp=str(budget['family_fingerprint'])
        selected=conn.execute(text("""
          select hypothesis_key,raw_p_value,adjusted_p_value
          from public.oracle_v6_multiple_testing
          where experiment_id=:e and as_of=:a and method='BENJAMINI_HOCHBERG' and selected=true
          order by hypothesis_key
        """),{'e':exp,'a':as_of}).mappings().all()

        promoted_rep=0; promoted_candidate=0; ephemeral=0
        for r in selected:
            term=str(r['hypothesis_key'])
            life=conn.execute(text("""select * from public.oracle_v6_signal_lifecycle
                                      where experiment_id=:e and trend_key=:t"""),{'e':exp,'t':term}).mappings().one_or_none()
            if life is None:
                life_id=conn.execute(text("""
                  insert into public.oracle_v6_signal_lifecycle
                    (experiment_id,trend_key,lifecycle_state,first_seen_at,last_seen_at,
                     qualifying_replications,replication_dates,alpha_trace,last_family_fingerprint,
                     last_adjusted_p_value,last_raw_p_value)
                  values(:e,:t,'EPHEMERAL_SIGNAL',:a,:a,0,'[]'::jsonb,'[]'::jsonb,:f,:q,:p)
                  returning id
                """),{'e':exp,'t':term,'a':as_of,'f':fp,'q':r['adjusted_p_value'],'p':r['raw_p_value']}).scalar_one()
                life=conn.execute(text("select * from public.oracle_v6_signal_lifecycle where id=:id"),{'id':life_id}).mappings().one()
            else:
                life_id=int(life['id'])

            # Exact same family already observed: idempotent, no replication credit.
            exists=conn.execute(text("""select 1 from public.oracle_v6_signal_lifecycle_observations
                                        where lifecycle_id=:id and family_fingerprint=:f"""),{'id':life_id,'f':fp}).scalar_one_or_none()
            if exists:
                continue

            current_docs=_docs(conn,term,week)
            prev=conn.execute(text("""
              select * from public.oracle_v6_signal_lifecycle_observations
              where lifecycle_id=:id and qualifies_as_independent_replication=true
              order by test_week desc,id desc limit 1
            """),{'id':life_id}).mappings().one_or_none()
            if prev is None:
                qualifies=True
                days=None
                new_docs=len(current_docs)
                ratio=1.0 if current_docs else 0.0
            else:
                prev_week=prev['test_week']
                prev_docs=_docs(conn,term,prev_week)
                new=current_docs-prev_docs
                new_docs=len(new)
                ratio=(new_docs/len(current_docs)) if current_docs else 0.0
                days=(week-prev_week).days
                qualifies=(days>=int(cfg['min_replication_days']) and
                           new_docs>=int(cfg['min_new_documents']) and
                           ratio>=float(cfg['min_new_document_ratio']))

            conn.execute(text("""
              insert into public.oracle_v6_signal_lifecycle_observations
                (lifecycle_id,family_fingerprint,test_week,decision_as_of,bh_selected,
                 raw_p_value,adjusted_p_value,allocated_alpha,document_count,new_document_count,
                 new_document_ratio,days_since_last_qualifying,qualifies_as_independent_replication)
              values(:id,:f,:w,:a,true,:p,:q,:alpha,:docs,:newdocs,:ratio,:days,:qual)
            """),{'id':life_id,'f':fp,'w':week,'a':as_of,'p':r['raw_p_value'],'q':r['adjusted_p_value'],
                    'alpha':budget['allocated_alpha'],'docs':len(current_docs),'newdocs':new_docs,'ratio':ratio,'days':days,'qual':qualifies})

            reps=int(life['qualifying_replications'])+(1 if qualifies else 0)
            if reps>=int(cfg['candidate_replications']): state='CANDIDATE_FOR_SEMANTIC_BRIDGE'
            elif reps>=int(cfg['min_qualifying_replications']): state='REPLICATED_SIGNAL'
            else: state='EPHEMERAL_SIGNAL'
            dates=list(life['replication_dates'] or [])
            if qualifies: dates.append(week.isoformat())
            trace=list(life['alpha_trace'] or [])
            trace.append({'family_fingerprint':fp,'test_week':week.isoformat(),'allocated_alpha':float(budget['allocated_alpha']),
                          'cumulative_allocated_alpha':float(budget['cumulative_allocated_alpha']),'qualifies':bool(qualifies)})
            conn.execute(text("""
              update public.oracle_v6_signal_lifecycle
              set lifecycle_state=:s,last_seen_at=:a,qualifying_replications=:r,
                  replication_dates=cast(:dates as jsonb),alpha_trace=cast(:trace as jsonb),
                  last_family_fingerprint=:f,last_adjusted_p_value=:q,last_raw_p_value=:p,updated_at=now()
              where id=:id
            """),{'s':state,'a':as_of,'r':reps,'dates':json.dumps(dates),'trace':json.dumps(trace),
                    'f':fp,'q':r['adjusted_p_value'],'p':r['raw_p_value'],'id':life_id})
            ephemeral+=int(state=='EPHEMERAL_SIGNAL'); promoted_rep+=int(state=='REPLICATED_SIGNAL'); promoted_candidate+=int(state=='CANDIDATE_FOR_SEMANTIC_BRIDGE')

        # Synchronize current trend materialization with lifecycle status.
        conn.execute(text("""
          update public.oracle_v6_trend_probabilities p
          set state=l.lifecycle_state
          from public.oracle_v6_signal_lifecycle l
          where p.experiment_id=l.experiment_id and p.trend_key=l.trend_key
            and p.experiment_id=:e and p.model_version=:m
        """),{'e':exp,'m':MODEL_VERSION})

        counts=dict(conn.execute(text("""select lifecycle_state,count(*) from public.oracle_v6_signal_lifecycle
                                        where experiment_id=:e group by lifecycle_state"""),{'e':exp}).all())
        summary={'config_version':CONFIG_VERSION,'family_fingerprint':fp,'test_week':week.isoformat(),
                 'min_replication_days':int(cfg['min_replication_days']),'min_new_document_ratio':float(cfg['min_new_document_ratio']),
                 'min_new_documents':int(cfg['min_new_documents']),'replicated_threshold':int(cfg['min_qualifying_replications']),
                 'candidate_threshold':int(cfg['candidate_replications']),'lifecycle_counts':counts,
                 'semantic_bridge_policy':'ONLY_REPLICATED_OR_CANDIDATE'}
        conn.execute(text("""update public.oracle_v6_experiments
          set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{signal_lifecycle}',cast(:s as jsonb),true)
          where id=:e"""),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,**summary}


if __name__=='__main__':
    print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
