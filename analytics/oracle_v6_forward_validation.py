#!/usr/bin/env python3
"""ORACLE V6 live forward validation.

Records every production decision as an immutable timestamped signal and matures
3/6/12/24 month outcomes using only prices available after that signal. SPY is
stored as a transparent benchmark residual, NOT as the contractual factor baseline.
The full baseline remains blocked until PIT earnings-revision history exists.
"""
from __future__ import annotations
import json, os
from datetime import date
from sqlalchemy import create_engine, text
from dateutil.relativedelta import relativedelta

MODEL_VERSION='FORWARD_VALIDATION_V1'
HORIZONS=(3,6,12,24)
TCOST=0.002

def eng(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def month0(d): return date(d.year,d.month,1)

def run(db_url:str)->dict:
    with eng(db_url).begin() as c:
        latest=c.execute(text("select max(as_of) from public.oracle_v6_decisions")).scalar_one_or_none()
        if latest is None: raise RuntimeError('no V6 decisions')
        decisions=c.execute(text("select ticker,decision,data_gaps,uncertainty,model_version from public.oracle_v6_decisions where as_of=:a order by ticker"),{'a':latest}).mappings().all()
        capture={r['ticker']:dict(r) for r in c.execute(text("select ticker,evidence_status,independent_evidence_count,pricing_power_evidence,bottleneck_node from public.oracle_v6_economic_capture_evidence where evaluation_as_of=:a order by ticker"),{'a':latest}).mappings().all()}
        dcf={r['ticker']:dict(r) for r in c.execute(text("select ticker,implied_fcf_cagr_5y from public.oracle_v6_reverse_dcf where as_of=:a"),{'a':latest}).mappings().all()}
        fcast={r['ticker']:dict(r) for r in c.execute(text("select ticker,point_forecast,interval_low,interval_high from public.oracle_v6_fundamental_forecasts where as_of=:a"),{'a':latest}).mappings().all()}
        inserted=0
        for d in decisions:
            ticker=str(d['ticker'])
            px=c.execute(text("select price_month,coalesce(adjusted_close,close)::float8 p from public.oracle_v5_monthly_prices where ticker=:t and price_month<=cast(:a as date) and coalesce(adjusted_close,close)>0 order by price_month desc limit 1"),{'t':ticker,'a':latest}).mappings().one_or_none()
            cap=capture.get(ticker); rv=dcf.get(ticker); ff=fcast.get(ticker)
            payload={
              'decision_model':d['model_version'],'data_gaps':d['data_gaps'],'uncertainty':d['uncertainty'],
              'capture':cap,'reverse_dcf':rv,'fundamental_forecast':ff,
              'baseline_contract':'Momentum + Earnings Revisions + Valuation + Quality',
              'baseline_status':'MISSING_PIT_ANALYST_EARNINGS_REVISIONS',
              'benchmark_status':'SPY_ONLY_NOT_FACTOR_BASELINE'
            }
            row=c.execute(text("""
              insert into public.oracle_v6_forward_signals
                (ticker,as_of,decision,model_version,start_price_month,start_price,feature_payload)
              values (:t,:a,:d,:m,:pm,:p,cast(:f as jsonb))
              on conflict (ticker,as_of,model_version) do nothing returning id
            """),{'t':ticker,'a':latest,'d':d['decision'],'m':MODEL_VERSION,'pm':px['price_month'] if px else None,'p':px['p'] if px else None,'f':json.dumps(payload,default=str,sort_keys=True)}).scalar_one_or_none()
            if row is not None: inserted+=1
        # Ensure horizon shells exist for all signals.
        signals=c.execute(text("select id,ticker,as_of,start_price_month,start_price from public.oracle_v6_forward_signals where model_version=:m"),{'m':MODEL_VERSION}).mappings().all()
        for s in signals:
            base=month0(s['as_of'].date())
            for h in HORIZONS:
                target=base+relativedelta(months=h)
                c.execute(text("insert into public.oracle_v6_forward_outcomes(signal_id,horizon_months,target_month,transaction_cost,metadata) values (:id,:h,:tm,:tc,cast(:meta as jsonb)) on conflict(signal_id,horizon_months) do nothing"),{'id':s['id'],'h':h,'tm':target,'tc':TCOST,'meta':json.dumps({'benchmark':'SPY','benchmark_is_not_contractual_factor_baseline':True})})
        matured=0
        pending=c.execute(text("""
          select o.id,o.signal_id,o.horizon_months,o.target_month,s.ticker,s.start_price,s.start_price_month
          from public.oracle_v6_forward_outcomes o join public.oracle_v6_forward_signals s on s.id=o.signal_id
          where o.matured_at is null and o.target_month<=date_trunc('month',current_date)::date
          order by o.target_month,o.id
        """)).mappings().all()
        for o in pending:
            if not o['start_price'] or not o['start_price_month']: continue
            end=c.execute(text("select price_month,coalesce(adjusted_close,close)::float8 p from public.oracle_v5_monthly_prices where ticker=:t and price_month>=:tm and coalesce(adjusted_close,close)>0 order by price_month asc limit 1"),{'t':o['ticker'],'tm':o['target_month']}).mappings().one_or_none()
            sp0=c.execute(text("select coalesce(adjusted_close,close)::float8 p from public.oracle_v5_monthly_prices where ticker='SPY' and price_month<=:m and coalesce(adjusted_close,close)>0 order by price_month desc limit 1"),{'m':o['start_price_month']}).scalar_one_or_none()
            sp1=c.execute(text("select price_month,coalesce(adjusted_close,close)::float8 p from public.oracle_v5_monthly_prices where ticker='SPY' and price_month>=:tm and coalesce(adjusted_close,close)>0 order by price_month asc limit 1"),{'tm':o['target_month']}).mappings().one_or_none()
            if not end or not sp0 or not sp1: continue
            rr=float(end['p'])/float(o['start_price'])-1.0
            br=float(sp1['p'])/float(sp0)-1.0
            residual=rr-br
            c.execute(text("""update public.oracle_v6_forward_outcomes set end_price_month=:em,end_price=:ep,realized_return=:rr,benchmark_return=:br,residual_return=:res,residual_return_net=:net,matured_at=now() where id=:id and matured_at is null"""),{'em':end['price_month'],'ep':end['p'],'rr':rr,'br':br,'res':residual,'net':residual-TCOST,'id':o['id']})
            c.execute(text("""insert into public.oracle_v6_return_targets(ticker,as_of,horizon_months,realized_return,expected_factor_return,residual_return,transaction_cost,residual_return_net,factor_model_version) values (:t,:a,:h,:rr,:br,:res,:tc,:net,'SPY_BENCHMARK_ONLY_NOT_CONTRACTUAL_BASELINE') on conflict do nothing"""),{'t':o['ticker'],'a':o['start_price_month'],'h':o['horizon_months'],'rr':rr,'br':br,'res':residual,'tc':TCOST,'net':residual-TCOST})
            matured+=1
        stats=c.execute(text("select count(*)::int signals,count(*) filter(where decision='WATCH')::int watch_signals,count(*) filter(where decision in ('BUY_CANDIDATE','PILOT_BUY'))::int buy_signals from public.oracle_v6_forward_signals where model_version=:m"),{'m':MODEL_VERSION}).mappings().one()
        out=c.execute(text("select count(*)::int outcomes,count(*) filter(where matured_at is not null)::int matured from public.oracle_v6_forward_outcomes o join public.oracle_v6_forward_signals s on s.id=o.signal_id where s.model_version=:m"),{'m':MODEL_VERSION}).mappings().one()
        summary={'model_version':MODEL_VERSION,'latest_signal_as_of':latest.isoformat(),'signals_total':stats['signals'],'watch_signals':stats['watch_signals'],'buy_signals':stats['buy_signals'],'outcomes_total':out['outcomes'],'outcomes_matured':out['matured'],'new_signals':inserted,'new_outcomes_matured':matured,'contractual_baseline_status':'BLOCKED_MISSING_PIT_ANALYST_REVISIONS','spy_benchmark_only':True,'state':'FORWARD_VALIDATION_ACTIVE'}
        exp=c.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one()
        c.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{forward_validation}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
