#!/usr/bin/env python3
"""ORACLE V6 market-expectations prerequisite gate.

Audits point-in-time FCF availability and whether the deterministic reverse-DCF
expectation measurement exists. Reverse DCF is NOT an expectation gap by itself:
there is still no probability that forward fundamentals will exceed what the
market price implies until a calibrated forward-fundamentals model exists.
"""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, text

MODEL_VERSION="MARKET_EXPECTATIONS_GATE_V1"
CAPTURE_MODEL="COMPANY_CAPTURE_EVIDENCE_GATE_V1"
FCF_MODEL="SEC_FCF_ANNUAL_V1"
REVERSE_DCF_MODEL="REVERSE_DCF_IMPLIED_FCF_GROWTH_V1"

def _engine(db_url: str):
    if db_url.startswith('postgres://'): db_url='postgresql+psycopg://'+db_url[len('postgres://'):]
    elif db_url.startswith('postgresql://'): db_url='postgresql+psycopg://'+db_url[len('postgresql://'):]
    else: raise ValueError('db_url must be PostgreSQL')
    return create_engine(db_url,pool_pre_ping=True)

def run(db_url: str) -> dict:
    engine=_engine(db_url); run_id=os.environ.get('GITHUB_RUN_ID')
    with engine.begin() as conn:
        exp=conn.execute(text("select id,(metrics->>'decision_as_of')::timestamptz signal_available_at from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).mappings().one_or_none()
        if not exp: raise RuntimeError('latest PIT Discovery experiment unavailable')
        experiment_id=int(exp['id']); cutoff=None
        if run_id:
            cutoff=conn.execute(text('select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r'),{'e':experiment_id,'r':run_id}).scalar_one_or_none()
        if cutoff is None:
            cutoff=conn.execute(text('select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1'),{'e':experiment_id}).scalar_one_or_none()
        if cutoff is None: raise RuntimeError('no evaluation clock for market expectations')

        candidates=conn.execute(text('select count(*) n,count(distinct ticker) tickers from public.oracle_v6_company_capture where model_version=:m and as_of=:c'),{'m':CAPTURE_MODEL,'c':cutoff}).mappings().one()
        fcf=conn.execute(text("""
            select count(*) snapshots,count(distinct f.ticker) tickers
            from public.oracle_v6_fcf_snapshots f
            where f.model_version=:fm and f.as_of<=:c
              and exists(select 1 from public.oracle_v6_company_capture cc where cc.model_version=:cm and cc.as_of=:c and cc.ticker=f.ticker)
        """),{'fm':FCF_MODEL,'cm':CAPTURE_MODEL,'c':cutoff}).mappings().one()
        reverse_rows=conn.execute(text('select count(*) from public.oracle_v6_market_expectations where model_version=:m and as_of=:c'),{'m':REVERSE_DCF_MODEL,'c':cutoff}).scalar_one()

        if int(reverse_rows or 0)>0:
            state='REVERSE_DCF_AVAILABLE_NO_CALIBRATED_FORWARD_EXPECTATION_GAP'
        elif int(fcf['tickers'] or 0)>0:
            state='PIT_FCF_AVAILABLE_REVERSE_DCF_INCOMPLETE'
        else:
            state='NO_EXPECTATION_MODEL_MISSING_PIT_FCF_INPUTS'

        conn.execute(text('delete from public.oracle_v6_market_expectations where model_version=:m and as_of=:c'),{'m':MODEL_VERSION,'c':cutoff})
        summary={
          'model_version':MODEL_VERSION,
          'signal_available_at':exp['signal_available_at'].isoformat() if exp['signal_available_at'] else None,
          'evaluation_as_of':cutoff.isoformat(),
          'company_capture_candidate_pairs':int(candidates['n'] or 0),
          'company_capture_tickers':int(candidates['tickers'] or 0),
          'pit_fcf_snapshots_available':int(fcf['snapshots'] or 0),
          'pit_fcf_tickers_available':int(fcf['tickers'] or 0),
          'reverse_dcf_rows_written':int(reverse_rows or 0),
          'probabilities_written':0,
          'proxy_substitution_allowed':False,
          'expectation_gap_calibrated':False,
          'state':state,
        }
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{market_expectations_gate}',cast(:s as jsonb),true) where id=:i"),{'s':json.dumps(summary,sort_keys=True),'i':experiment_id})
    return {'ok':True,'experiment_id':experiment_id,**summary}

def main(): print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
if __name__=='__main__': main()
