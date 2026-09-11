#!/usr/bin/env python3
"""ORACLE V6 live formal nulls V2.

Fixes the live conditional-selection bug: the hypothesis family is frozen from
the 104 PRE-TEST weeks only. Test-week N(t) never determines membership.
Applies a pre-test persistence gate (>=3 docs in >=2 weeks) and a conservative
semantic boilerplate gate before formal null fitting. Statistical model fitting
itself is unchanged from FORMAL_COUNT_NULL_V1.
"""
from __future__ import annotations
import json, os, re
from collections import defaultdict
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine, text
from oracle_v6_formal_nulls import _fit_count_null, WINDOW_WEEKS

MODEL_VERSION='FORMAL_COUNT_NULL_V2_PRETEST_FAMILY'
MIN_TRAIN_DOCS=3
MIN_TRAIN_WEEKS_ACTIVE=2
ACADEMIC_GENERIC=set('''abstract academic analysis analytical application applications approach approaches assessment benchmark benchmarks case cases challenge challenges comparison comparisons comprehensive conclusion conclusions dataset datasets empirical evaluation evaluations evidence experiment experiments experimental framework frameworks general generalized heterogeneity heterogeneous improvement improvements investigation investigations literature method methods methodology modern novel objective objectives overview paper papers performance perspective perspectives practical proposed qualitative quantitative result results review reviews retrospective robust robustness sample samples simulation simulations spike statistical strategy strategies study studies survey surveys systematic technique techniques test tests theoretical theory validation validations'''.split())
AMBIGUOUS_UNIGRAM=set('''advanced architecture capacity computing control design development digital efficient energy future generation global growth hardware intelligent market memory network networks optimization platform power process production scale scaling software solution solutions system systems technology technologies training transformation use value virtual'''.split())

def engine(url):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def eligible_key(k:str)->bool:
    toks=[x.lower() for x in re.findall(r"[A-Za-z0-9+#.]+",k or '') if len(x)>2]
    if not toks: return False
    if len(toks)==1 and toks[0] in ACADEMIC_GENERIC|AMBIGUOUS_UNIGRAM: return False
    informative=[x for x in toks if x not in ACADEMIC_GENERIC]
    if not informative: return False
    if len(toks)>1 and all(x in AMBIGUOUS_UNIGRAM for x in informative): return False
    return True

def run(db_url):
    with engine(db_url).begin() as conn:
        test_week=conn.execute(text('select max(week_start) from public.oracle_v4_term_history_weekly')).scalar_one()
        if isinstance(test_week,datetime): test_week=test_week.date()
        if test_week is None: raise RuntimeError('term history empty')
        last_event_date=conn.execute(text('select max(last_event_date) from public.oracle_v4_term_history_weekly where week_start=:w'),{'w':test_week}).scalar_one()
        if last_event_date is None: raise RuntimeError('test-week last_event_date unavailable')
        decision_as_of=conn.execute(text("""select max(greatest(o.created_at,d.fetched_at)) from public.oracle_v4_retro_term_occurrences o join public.oracle_raw_documents d on d.id=o.document_id where o.event_date between :w and :e"""),{'w':test_week,'e':last_event_date}).scalar_one()
        if decision_as_of is None: raise RuntimeError('cannot establish KNOWN decision_as_of')
        train_start=test_week-timedelta(weeks=WINDOW_WEEKS); train_end=test_week-timedelta(weeks=1)
        rows=conn.execute(text("""
          select d.term_id,d.term_key,h.week_start,h.event_count
          from public.oracle_v4_term_history_weekly h
          join public.oracle_v4_term_dictionary d on d.term_id=h.term_id
          where h.week_start>=:s and h.week_start<:w
          order by d.term_id,h.week_start
        """),{'s':train_start,'w':test_week}).mappings().all()
        by=defaultdict(dict); keys={}
        for r in rows:
            tid=int(r['term_id']); keys[tid]=str(r['term_key']); by[tid][r['week_start']]=int(r['event_count'])
        observed_rows=conn.execute(text("""select term_id,event_count from public.oracle_v4_term_history_weekly where week_start=:w"""),{'w':test_week}).mappings().all()
        observed={int(r['term_id']):int(r['event_count']) for r in observed_rows}
        weeks=[train_start+timedelta(weeks=i) for i in range(WINDOW_WEEKS)]
        payload=[]; fam=defaultdict(int); excluded_sem=0; excluded_support=0
        for tid in sorted(by):
            key=keys[tid]
            if not eligible_key(key): excluded_sem+=1; continue
            train=[by[tid].get(w,0) for w in weeks]
            if sum(train)<MIN_TRAIN_DOCS or sum(1 for x in train if x>0)<MIN_TRAIN_WEEKS_ACTIVE:
                excluded_support+=1; continue
            obs=observed.get(tid,0); fit=_fit_count_null(train,obs); fam[fit.family]+=1
            diagnostics={**fit.diagnostics,'availability_quality':'KNOWN','decision_as_of':decision_as_of.isoformat(),'test_week':test_week.isoformat(),'family_rule':'PRETEST_ONLY_MIN3_DOCS_MIN2_WEEKS_SEMANTIC','family_membership_depends_on_test_observation':False,'semantic_gate':True,'pretest_persistence_gate':True}
            payload.append({'signal_key':key,'as_of':decision_as_of,'null_family':fit.family,'observed_value':float(obs),'expected_value':fit.expected,'dispersion':fit.dispersion,'surprise_z':fit.z_score,'p_value':fit.p_value,'model_version':MODEL_VERSION,'training_window':json.dumps({'weeks':WINDOW_WEEKS,'train_start':train_start.isoformat(),'train_end':train_end.isoformat(),'test_week':test_week.isoformat(),'decision_as_of':decision_as_of.isoformat(),'family_rule':'PRETEST_ONLY_MIN3_DOCS_MIN2_WEEKS_SEMANTIC'},sort_keys=True),'diagnostics':json.dumps(diagnostics,sort_keys=True)})
        if not payload: raise RuntimeError('pre-test family empty')
        experiment_key=f'v6_formal_count_null_v2_{test_week.isoformat()}'
        spec=json.dumps({'window_weeks':WINDOW_WEEKS,'family_membership':'pretest_only','min_train_docs':MIN_TRAIN_DOCS,'min_active_weeks':MIN_TRAIN_WEEKS_ACTIVE,'semantic_gate':True,'test_week':test_week.isoformat()},sort_keys=True)
        exp=conn.execute(text("""insert into public.oracle_v6_experiments(experiment_key,model_family,model_version,target_name,train_start,train_end,test_start,test_end,holdout,specification,metrics) values(:k,'COUNT_NULL_MODEL',:v,'weekly_term_event_count',:s,:e,:w,:w,false,cast(:spec as jsonb),'{}'::jsonb) on conflict(experiment_key) do update set model_version=excluded.model_version,specification=excluded.specification,invalidated_at=null,invalidation_reason=null returning id"""),{'k':experiment_key,'v':MODEL_VERSION,'s':train_start,'e':train_end,'w':test_week,'spec':spec}).scalar_one()
        conn.execute(text("delete from public.oracle_v6_signal_null_models where model_version=:v and training_window->>'test_week'=:w"),{'v':MODEL_VERSION,'w':test_week.isoformat()})
        ins=text("""insert into public.oracle_v6_signal_null_models(signal_key,as_of,null_family,observed_value,expected_value,dispersion,surprise_z,p_value,model_version,training_window,diagnostics) values(:signal_key,:as_of,:null_family,:observed_value,:expected_value,:dispersion,:surprise_z,:p_value,:model_version,cast(:training_window as jsonb),cast(:diagnostics as jsonb))""")
        for i in range(0,len(payload),500): conn.execute(ins,payload[i:i+500])
        ps=sorted(float(x['p_value']) for x in payload)
        metrics={'rows':len(payload),'family_counts':dict(fam),'min_p_value':ps[0],'median_p_value':ps[len(ps)//2],'formal_p_value':True,'test_week':test_week.isoformat(),'decision_as_of':decision_as_of.isoformat(),'family_membership_depends_on_test_observation':False,'excluded_semantic':excluded_sem,'excluded_support':excluded_support}
        conn.execute(text("update public.oracle_v6_experiments set metrics=cast(:m as jsonb) where id=:e"),{'m':json.dumps(metrics,sort_keys=True),'e':exp})
    return {'ok':True,'experiment_id':int(exp),'model_version':MODEL_VERSION,'test_week':test_week.isoformat(),'decision_as_of':decision_as_of.isoformat(),'rows':len(payload),'families':dict(fam),'excluded_semantic':excluded_sem,'excluded_support':excluded_support,'conditional_selection_guard':True}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
