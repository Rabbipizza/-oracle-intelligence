#!/usr/bin/env python3
"""ORACLE V6 Economic Capture calibration gate.

Descriptive capture evidence is not a probability. This gate measures whether
there are enough *historical, matured* SEC-evidence cases with subsequent FCF
outcomes to fit and validate a capture model. Until that sample exists, it writes
no capture probability and records a hard NO_CAPTURE_PROBABILITY state.
"""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, text

MODEL_VERSION='ECONOMIC_CAPTURE_CALIBRATION_GATE_V1'
MIN_OUTCOMES=100
MIN_TICKERS=20
MIN_YEARS=5


def eng(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)


def run(db_url:str)->dict:
    run_id=os.environ.get('GITHUB_RUN_ID')
    with eng(db_url).begin() as c:
        exp=int(c.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one())
        cutoff=None
        if run_id:
            cutoff=c.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r order by evaluation_as_of desc limit 1"),{'e':exp,'r':run_id}).scalar_one_or_none()
        if cutoff is None:
            cutoff=c.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1"),{'e':exp}).scalar_one()

        stats=c.execute(text("""
        with doc_flags as (
          select ticker, filing_date, document_id,
                 bool_or(evidence_key in ('DEMAND','ORDERS','BACKLOG')) as pull,
                 bool_or(evidence_key in ('CAPACITY','SUPPLY','CONSTRAINT','LEAD_TIME')) as ability,
                 bool_or(evidence_key='PRICE') as pricing
          from public.oracle_v4_sec_economic_evidence
          where filing_date is not null and ticker is not null
          group by ticker,filing_date,document_id
        ), event_dates as (
          select ticker, date_trunc('year',filing_date)::date as event_year,
                 count(distinct document_id) filter(where pull) as pull_docs,
                 count(distinct document_id) filter(where ability) as ability_docs,
                 count(distinct document_id) filter(where pricing) as pricing_docs
          from doc_flags
          where filing_date <= cast(:cutoff as date) - interval '30 months'
          group by ticker,date_trunc('year',filing_date)::date
          having count(distinct document_id)>=2
             and count(distinct document_id) filter(where pull)>=1
             and count(distinct document_id) filter(where ability)>=1
        ), matured as (
          select e.ticker,e.event_year,e.pricing_docs,
                 b.free_cash_flow base_fcf,f.free_cash_flow future_fcf
          from event_dates e
          join lateral (
             select free_cash_flow,fiscal_period_end
             from public.oracle_v6_fcf_snapshots
             where model_version='SEC_FCF_HISTORICAL_UNIVERSE_V1'
               and ticker=e.ticker and free_cash_flow>0
               and fiscal_period_end<=e.event_year+interval '12 months'
             order by fiscal_period_end desc limit 1
          ) b on true
          join lateral (
             select free_cash_flow,fiscal_period_end
             from public.oracle_v6_fcf_snapshots
             where model_version='SEC_FCF_HISTORICAL_UNIVERSE_V1'
               and ticker=e.ticker and free_cash_flow>0
               and fiscal_period_end between e.event_year+interval '24 months' and e.event_year+interval '42 months'
             order by abs(extract(epoch from (fiscal_period_end-(e.event_year+interval '36 months')))) limit 1
          ) f on true
        )
        select count(*)::int outcomes,
               count(distinct ticker)::int tickers,
               min(event_year) first_event,
               max(event_year) last_event,
               count(*) filter(where pricing_docs>0)::int pricing_cases
        from matured
        """),{'cutoff':cutoff}).mappings().one()
        outcomes=int(stats['outcomes'] or 0); tickers=int(stats['tickers'] or 0)
        years=0
        if stats['first_event'] and stats['last_event']:
            years=max(1,stats['last_event'].year-stats['first_event'].year+1)
        eligible=outcomes>=MIN_OUTCOMES and tickers>=MIN_TICKERS and years>=MIN_YEARS
        state='CAPTURE_MODEL_CALIBRATION_SAMPLE_READY' if eligible else 'NO_CAPTURE_PROBABILITY_INSUFFICIENT_HISTORICAL_OUTCOMES'
        summary={
          'model_version':MODEL_VERSION,'evaluation_as_of':cutoff.isoformat(),'state':state,
          'historical_matured_outcomes':outcomes,'historical_tickers':tickers,'historical_years':years,
          'pricing_cases':int(stats['pricing_cases'] or 0),'minimum_outcomes':MIN_OUTCOMES,
          'minimum_tickers':MIN_TICKERS,'minimum_years':MIN_YEARS,
          'capture_probability_allowed':False,
          'note':'Readiness gate only; a validated model is still required even after sample thresholds are met.'
        }
        c.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{economic_capture_calibration}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,'experiment_id':exp,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
