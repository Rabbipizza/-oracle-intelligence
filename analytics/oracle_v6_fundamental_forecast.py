#!/usr/bin/env python3
"""ORACLE V6 PIT walk-forward 5y FCF forecast and expectation-gap calibration.

Scientific rules:
- historical features use only annual SEC FCF snapshots known at the forecast date;
- a historical training label is usable only after its 5y endpoint itself was available;
- model architecture/lambda are selected on pre-2020 development validation only;
- start dates >= 2020 are the untouched holdout for this model version;
- the model must beat a trailing-3y-growth baseline and pass predictive-interval
  calibration before p_exceed_implied is allowed to be non-NULL.
"""
from __future__ import annotations
import json, math, os
from dataclasses import dataclass
from datetime import date
from typing import Optional
import numpy as np
from scipy.stats import kstest
from sqlalchemy import create_engine, text

MODEL_VERSION='FCF5Y_RIDGE_PIT_V1'
HIST_MODEL='SEC_FCF_HISTORICAL_UNIVERSE_V1'
REVERSE_MODEL='REVERSE_DCF_IMPLIED_FCF_GROWTH_V1'
HOLDOUT_START_YEAR=2020
MIN_TRAIN=100
MIN_DEV=40
MIN_HOLDOUT=40
LAMBDAS=(0.1,1.0,10.0,100.0)

@dataclass
class Obs:
    ticker:str; period:date; known_at:object; fcf:float
@dataclass
class Sample:
    ticker:str; start:Obs; end:Obs; x:np.ndarray; y:float; baseline:float

def eng(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def years(a:date,b:date)->float: return (b-a).days/365.25

def near(seq:list[Obs],target:date,lo:float,hi:float,before=True)->Optional[Obs]:
    cand=[]
    for o in seq:
        dy=years(o.period,target) if before else years(target,o.period)
        if lo<=dy<=hi: cand.append((abs(dy-(lo+hi)/2),o))
    return min(cand,key=lambda z:z[0])[1] if cand else None

def feat_for(seq:list[Obs],cur:Obs)->Optional[np.ndarray]:
    if cur.fcf<=0:return None
    p1=near([o for o in seq if o.period<cur.period],cur.period,0.5,1.5,True)
    p3=near([o for o in seq if o.period<cur.period],cur.period,2.5,3.5,True)
    if not p1 or not p3 or p1.fcf<=0 or p3.fcf<=0:return None
    y1=years(p1.period,cur.period); y3=years(p3.period,cur.period)
    g1=math.log(cur.fcf/p1.fcf)/y1
    g3=math.log(cur.fcf/p3.fcf)/y3
    if not all(math.isfinite(v) for v in (g1,g3)):return None
    # log scale / momentum / acceleration / maturity proxy
    return np.array([math.log(cur.fcf),g1,g3,g1-g3,math.log1p(max(0,len([o for o in seq if o.period<=cur.period])-1))],dtype=float)

def make_samples(by:dict[str,list[Obs]])->list[Sample]:
    out=[]
    for ticker,seq in by.items():
        seq=sorted(seq,key=lambda o:o.period)
        for cur in seq:
            x=feat_for(seq,cur)
            if x is None:continue
            fut=[]
            for o in seq:
                dy=years(cur.period,o.period)
                if 4.5<=dy<=5.5 and o.fcf>0:fut.append((abs(dy-5),o,dy))
            if not fut:continue
            _,end,dy=min(fut,key=lambda z:z[0])
            y=math.log(end.fcf/cur.fcf)/dy
            if not math.isfinite(y):continue
            out.append(Sample(ticker,cur,end,x,y,float(x[2])))
    return out

def fit(train:list[Sample],lam:float):
    X=np.vstack([s.x for s in train]); y=np.array([s.y for s in train])
    mu=X.mean(0); sd=X.std(0); sd=np.where(sd<1e-9,1.0,sd)
    Z=(X-mu)/sd; Z=np.c_[np.ones(len(Z)),Z]
    I=np.eye(Z.shape[1]); I[0,0]=0
    beta=np.linalg.solve(Z.T@Z+lam*I,Z.T@y)
    return mu,sd,beta

def pred(model,x):
    mu,sd,beta=model; z=(x-mu)/sd
    return float(np.r_[1.0,z]@beta)

def walk(samples:list[Sample],eval_years:set[int],lam:float,train_start_limit:int):
    rows=[]
    evals=sorted([s for s in samples if s.start.period.year in eval_years],key=lambda s:s.start.known_at)
    for s in evals:
        # Labels become trainable only when the endpoint filing was available.
        tr=[t for t in samples if t.start.period.year<train_start_limit and t.end.known_at<=s.start.known_at]
        if len(tr)<MIN_TRAIN:continue
        m=fit(tr,lam); yhat=pred(m,s.x)
        rows.append((s,yhat,s.baseline,s.y-yhat))
    return rows

def metrics(rows):
    if not rows:return {'n':0}
    e=np.array([s.y-yh for s,yh,_,_ in rows]); eb=np.array([s.y-b for s,_,b,_ in rows])
    return {'n':len(rows),'mae':float(np.mean(np.abs(e))),'rmse':float(np.sqrt(np.mean(e*e))),
            'baseline_mae':float(np.mean(np.abs(eb))),'improvement_vs_baseline':float(1-np.mean(np.abs(e))/np.mean(np.abs(eb)))}

def empirical_tail(residuals:np.ndarray,threshold:float)->float:
    # smoothed empirical survival probability
    return float((np.sum(residuals>threshold)+1)/(len(residuals)+2))

def run(db_url:str):
    E=eng(db_url); run_id=os.environ.get('GITHUB_RUN_ID')
    with E.begin() as c:
        exp=c.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one()
        cutoff=None
        if run_id: cutoff=c.execute(text('select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r'),{'e':exp,'r':run_id}).scalar_one_or_none()
        if cutoff is None: cutoff=c.execute(text('select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1'),{'e':exp}).scalar_one()
        rows=c.execute(text("select ticker,fiscal_period_end,as_of,free_cash_flow::double precision fcf from public.oracle_v6_fcf_snapshots where model_version=:m and as_of<=:c order by ticker,fiscal_period_end"),{'m':HIST_MODEL,'c':cutoff}).mappings().all()
        rev=c.execute(text("select ticker,(implied_fundamentals->>'implied_constant_fcf_cagr_5y')::double precision implied from public.oracle_v6_market_expectations where model_version=:m and as_of=:c"),{'m':REVERSE_MODEL,'c':cutoff}).mappings().all()
    by={}
    for r in rows: by.setdefault(str(r['ticker']),[]).append(Obs(str(r['ticker']),r['fiscal_period_end'],r['as_of'],float(r['fcf'])))
    samples=make_samples(by)
    dev_years=set(range(2016,HOLDOUT_START_YEAR))
    # Lambda selection is development-only.
    candidates=[]
    for lam in LAMBDAS:
        rr=walk(samples,dev_years,lam,HOLDOUT_START_YEAR)
        mm=metrics(rr); candidates.append((mm.get('mae',float('inf')),lam,rr,mm))
    _,best_lam,dev_rows,dev_m=min(candidates,key=lambda z:z[0])
    dev_res=np.array([res for _,_,_,res in dev_rows]) if dev_rows else np.array([])
    q10,q90=(np.quantile(dev_res,[0.1,0.9]) if len(dev_res)>=MIN_DEV else (math.nan,math.nan))

    # Untouched holdout is inspected exactly once for this frozen model version.
    hold_years=set(range(HOLDOUT_START_YEAR,2027))
    hold_rows=walk(samples,hold_years,best_lam,HOLDOUT_START_YEAR)
    hold_m=metrics(hold_rows)
    if hold_rows and len(dev_res)>=MIN_DEV:
        herr=np.array([res for _,_,_,res in hold_rows])
        coverage=float(np.mean((herr>=q10)&(herr<=q90)))
        pits=np.array([(np.sum(dev_res<=r)+1)/(len(dev_res)+2) for r in herr])
        ks_p=float(kstest(pits,'uniform').pvalue) if len(pits)>=20 else 0.0
    else: coverage=0.0;ks_p=0.0

    calibrated=(dev_m.get('n',0)>=MIN_DEV and hold_m.get('n',0)>=MIN_HOLDOUT and
                hold_m.get('improvement_vs_baseline',-1)>0.0 and 0.65<=coverage<=0.95 and ks_p>=0.05)
    status='CALIBRATED_HOLDOUT_PASS' if calibrated else 'NO_EXPECTATION_GAP_CALIBRATION_FAILED_OR_INSUFFICIENT'

    # Production fit may use all matured outcomes after architecture is frozen.
    matured=[s for s in samples if s.end.known_at<=cutoff]
    model=fit(matured,best_lam) if len(matured)>=MIN_TRAIN else None
    oos_res=np.array([res for _,_,_,res in dev_rows+hold_rows]) if (dev_rows or hold_rows) else np.array([])
    payload=[]
    for r in rev:
        ticker=str(r['ticker']); seq=sorted(by.get(ticker,[]),key=lambda o:o.period)
        if not seq or model is None:continue
        cur=max([o for o in seq if o.known_at<=cutoff],key=lambda o:(o.period,o.known_at),default=None)
        if cur is None:continue
        x=feat_for(seq,cur)
        if x is None:continue
        yh=pred(model,x); pred_cagr=math.exp(yh)-1
        lower=math.exp(yh+(float(np.quantile(oos_res,0.1)) if len(oos_res) else 0))-1
        upper=math.exp(yh+(float(np.quantile(oos_res,0.9)) if len(oos_res) else 0))-1
        implied=float(r['implied']); threshold=math.log1p(implied)-yh if implied>-1 else float('inf')
        p=empirical_tail(oos_res,threshold) if calibrated and len(oos_res)>=MIN_HOLDOUT else None
        payload.append({'experiment_id':int(exp),'ticker':ticker,'as_of':cutoff,'pred_log':yh,'pred_cagr':pred_cagr,'lower':lower,'upper':upper,'implied':implied,'p':p,'status':status,'model':MODEL_VERSION,
                        'diag':json.dumps({'lambda':best_lam,'training_samples':len(matured),'dev':dev_m,'holdout':hold_m,'holdout_interval80_coverage':coverage,'holdout_pit_ks_p':ks_p,'residual_pool_n':len(oos_res)},sort_keys=True)})
    with E.begin() as c:
        c.execute(text('delete from public.oracle_v6_fundamental_forecasts where experiment_id=:e and as_of=:c and model_version=:m'),{'e':exp,'c':cutoff,'m':MODEL_VERSION})
        if payload:
            c.execute(text("insert into public.oracle_v6_fundamental_forecasts (experiment_id,ticker,as_of,horizon_years,predicted_log_fcf_growth,predicted_fcf_cagr,lower_fcf_cagr,upper_fcf_cagr,implied_market_fcf_cagr,p_exceed_implied,calibration_status,model_version,diagnostics) values (:experiment_id,:ticker,:as_of,5,:pred_log,:pred_cagr,:lower,:upper,:implied,:p,:status,:model,cast(:diag as jsonb))"),payload)
        summary={'model_version':MODEL_VERSION,'evaluation_as_of':cutoff.isoformat(),'historical_samples':len(samples),'matured_training_samples':len(matured),'best_lambda':best_lam,'development':dev_m,'holdout':hold_m,'holdout_interval80_coverage':coverage,'holdout_pit_ks_p':ks_p,'calibration_status':status,'current_forecasts':len(payload),'probabilities_written':sum(1 for x in payload if x['p'] is not None)}
        c.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{fundamental_forecast}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,'experiment_id':int(exp),**summary}
if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
