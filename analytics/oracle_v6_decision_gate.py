#!/usr/bin/env python3
"""ORACLE V6 final investment decision gate.

WATCH is a research state, not an investment recommendation: it can be emitted when
structural/tension/capture evidence is sufficiently developed even while calibrated
return prerequisites remain incomplete. BUY/PILOT_BUY stay locked until all numeric
probability and OOS-return prerequisites are empirically validated.
"""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, text

MODEL_VERSION='DECISION_PREREQUISITE_GATE_V3'
CAPTURE_MODEL='COMPANY_CAPTURE_EVIDENCE_GATE_V1'

def _engine(db_url):
    if db_url.startswith('postgres://'): db_url='postgresql+psycopg://'+db_url[len('postgres://'):]
    elif db_url.startswith('postgresql://'): db_url='postgresql+psycopg://'+db_url[len('postgresql://'):]
    else: raise ValueError('db_url must be PostgreSQL')
    return create_engine(db_url,pool_pre_ping=True)

def run(db_url):
    run_id=os.environ.get('GITHUB_RUN_ID')
    with _engine(db_url).begin() as conn:
        exp=conn.execute(text("select id,(metrics->>'decision_as_of')::timestamptz signal_available_at,metrics from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).mappings().one_or_none()
        if not exp: raise RuntimeError('latest PIT experiment unavailable')
        experiment_id=int(exp['id']); metrics=exp['metrics'] or {}
        cutoff=None
        if run_id:
            cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r order by id desc limit 1"),{'e':experiment_id,'r':run_id}).scalar_one_or_none()
        if cutoff is None:
            cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1"),{'e':experiment_id}).scalar_one()

        tickers=[str(x) for x in conn.execute(text("select distinct ticker from public.oracle_v6_company_capture where model_version=:m and as_of=:c order by ticker"),{'m':CAPTURE_MODEL,'c':cutoff}).scalars().all()]
        capture_backed=set(str(x) for x in conn.execute(text("select distinct ticker from public.oracle_v6_economic_capture_evidence where evaluation_as_of=:c and evidence_status='CAPTURE_EVIDENCE_BACKED'"),{'c':cutoff}).scalars().all())
        tension_suppliers=set(str(x) for x in conn.execute(text("""
          select distinct x.ticker
          from public.oracle_v6_structural_company_exposure x
          join public.oracle_v6_structural_bottlenecks b
            on b.experiment_id=x.experiment_id and b.evaluation_as_of=x.evaluation_as_of
           and b.bottleneck_node=x.bottleneck_node
          where x.evaluation_as_of=:c and x.exposure_role='SUPPLIER_CANDIDATE'
            and b.structural_status='EVIDENCE_BACKED_TENSION'
        """),{'c':cutoff}).scalars().all())

        global_gaps=[]
        if conn.execute(text("select count(*) from public.oracle_v6_company_capture where model_version=:m and as_of=:c and capture_probability is not null"),{'m':CAPTURE_MODEL,'c':cutoff}).scalar_one()==0:
            global_gaps.append('UNCALIBRATED_ECONOMIC_CAPTURE')
        if conn.execute(text("select count(*) from public.oracle_v6_market_expectations where as_of=:c and p_fundamentals_exceed_expectations is not null"),{'c':cutoff}).scalar_one()==0:
            global_gaps.append('MISSING_CALIBRATED_EXPECTATION_GAP')
        if conn.execute(text("select count(*) from public.oracle_v6_bottleneck_forecasts where as_of<=:c"),{'c':cutoff}).scalar_one()==0:
            global_gaps.append('NO_VALIDATED_BOTTLENECK_FORECAST')
        demo=metrics.get('demographic_context') if isinstance(metrics,dict) else None
        if not demo or demo.get('state')!='DEMOGRAPHIC_CONTEXT_AVAILABLE':
            global_gaps.append('MISSING_DEMOGRAPHIC_CONTEXT')
        geo_count=conn.execute(text("select count(*) from public.oracle_v6_company_geographic_exposure where as_of<=:c and available_at<=:c"),{'c':cutoff}).scalar_one()
        if int(geo_count or 0)==0: global_gaps.append('DEMOGRAPHIC_COMPANY_EXPOSURE_UNCALIBRATED')
        global_gaps.append('NO_OOS_INCREMENTAL_RETURN_MODEL')
        global_gaps=sorted(set(global_gaps))

        # Remove older decision-gate versions at the same evaluation timestamp so
        # consumers see one canonical current decision row per ticker.
        conn.execute(text("delete from public.oracle_v6_decisions where as_of=:c and model_version like 'DECISION_PREREQUISITE_GATE_V%'"),{'c':cutoff})
        payload=[]
        for t in tickers:
            if t in capture_backed:
                decision='WATCH'
                rationale='CAPTURE_EVIDENCE_BACKED_BUT_NO_CALIBRATED_RETURN_EDGE'
            elif t in tension_suppliers:
                decision='WATCH'
                rationale='TENSION_BACKED_SUPPLIER_RESEARCH_CANDIDATE'
            else:
                decision='NO_ACTION'
                rationale='STRUCTURAL_EXPOSURE_ONLY_OR_INSUFFICIENT_EVIDENCE'
            uncertainty={
              'probabilities_calibrated':False,
              'expected_residual_return_calibrated':False,
              'watch_is_not_buy':True,
              'rationale':rationale,
              'signal_available_at':exp['signal_available_at'].isoformat() if exp['signal_available_at'] else None
            }
            payload.append({'ticker':t,'as_of':cutoff,'decision':decision,'uncertainty':json.dumps(uncertainty,sort_keys=True),'data_gaps':json.dumps(global_gaps),'invalidation_conditions':json.dumps([]),'model_version':MODEL_VERSION})
        if payload:
            conn.execute(text("insert into public.oracle_v6_decisions (ticker,as_of,decision,p_structural,p_bottleneck,p_economic_capture,p_fundamentals_exceed_expectations,expected_residual_return,uncertainty,invalidation_conditions,data_gaps,model_version) values (:ticker,:as_of,:decision,null,null,null,null,null,cast(:uncertainty as jsonb),cast(:invalidation_conditions as jsonb),cast(:data_gaps as jsonb),:model_version)"),payload)
        watches=sum(1 for p in payload if p['decision']=='WATCH')
        summary={
          'model_version':MODEL_VERSION,
          'signal_available_at':exp['signal_available_at'].isoformat() if exp['signal_available_at'] else None,
          'evaluation_as_of':cutoff.isoformat(),
          'candidate_tickers':len(tickers),'decision_rows_written':len(payload),
          'watch_rows':watches,'buy_rows':0,
          'decision':'WATCH' if watches else 'NO_ACTION',
          'data_gaps':global_gaps,
          'numeric_probabilities_written':0,'expected_returns_written':0,
          'watch_semantics':'RESEARCH_PRIORITY_NOT_INVESTMENT_RECOMMENDATION',
          'state':'PAPER_VALIDATION_WATCHLIST_ACTIVE' if watches else 'NO_ACTION_PREREQUISITES_INCOMPLETE'
        }
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{decision_gate}',cast(:s as jsonb),true) where id=:i"),{'s':json.dumps(summary,sort_keys=True),'i':experiment_id})
    return {'ok':True,'experiment_id':experiment_id,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
