#!/usr/bin/env python3
"""ORACLE V6 demographic trend detector.

Demography is treated as a native structural trend family, not merely macro context.
This stage detects slow-moving demographic trends from available country snapshots.
Current revised WDI history is LIVE CONTEXT ONLY; no historical alpha probability is
written until vintage-consistent demographic data is available.
"""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, text

MODEL_VERSION='DEMOGRAPHIC_TRENDS_V1'
CODES={
 'growth':'SP.POP.GROW','fertility':'SP.DYN.TFRT.IN','age65':'SP.POP.65UP.TO.ZS',
 'working':'SP.POP.1564.TO.ZS','youth':'SP.POP.0014.TO.ZS','urban':'SP.URB.TOTL.IN.ZS',
 'migration':'SM.POP.NETM','pop':'SP.POP.TOTL'
}

def eng(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def latest_before(rows,year):
    xs=[r for r in rows if r['observation_year']<=year]
    return float(xs[0]['value']) if xs and xs[0]['value'] is not None else None

def add(out,cc,key,direction,status,level,c5,c10,acc,persist,codes,meta):
    out.append({'cc':cc,'key':key,'direction':direction,'status':status,'level':level,'c5':c5,'c10':c10,'acc':acc,'persist':persist,'codes':json.dumps(codes),'meta':json.dumps(meta,sort_keys=True)})

def run(db_url:str)->dict:
    run_id=os.environ.get('GITHUB_RUN_ID')
    with eng(db_url).begin() as c:
        exp=int(c.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one())
        cutoff=None
        if run_id:
            cutoff=c.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r order by evaluation_as_of desc limit 1"),{'e':exp,'r':run_id}).scalar_one_or_none()
        if cutoff is None:
            cutoff=c.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1"),{'e':exp}).scalar_one()
        countries=[str(x) for x in c.execute(text("select country_code from public.oracle_v6_demographic_country_universe where enabled order by weight desc,country_code")).scalars().all()]
        c.execute(text("delete from public.oracle_v6_demographic_trends where experiment_id=:e and evaluation_as_of=:a and model_version=:m"),{'e':exp,'a':cutoff,'m':MODEL_VERSION})
        out=[]
        for cc in countries:
            rs=c.execute(text("select indicator_code,observation_year,value from public.oracle_v6_demographic_snapshots where country_code=:cc and available_at<=:a order by indicator_code,observation_year desc"),{'cc':cc,'a':cutoff}).mappings().all()
            if not rs: continue
            by={}
            for r in rs: by.setdefault(str(r['indicator_code']),[]).append(r)
            years=[r['observation_year'] for r in rs if r['observation_year'] is not None]
            if not years: continue
            y=max(years)
            def metric(code):
                arr=by.get(code,[])
                cur=latest_before(arr,y); v5=latest_before(arr,y-5); v10=latest_before(arr,y-10)
                c5=None if cur is None or v5 is None else cur-v5
                c10=None if cur is None or v10 is None else cur-v10
                acc=None if c5 is None or c10 is None else c5-(c10-c5)
                return cur,c5,c10,acc
            growth,g5,g10,gacc=metric(CODES['growth']); fert,f5,f10,facc=metric(CODES['fertility']); age65,a5,a10,aacc=metric(CODES['age65']); working,w5,w10,wacc=metric(CODES['working']); youth,y5,y10,yacc=metric(CODES['youth']); urban,u5,u10,uacc=metric(CODES['urban']); pop,p5,p10,pacc=metric(CODES['pop'])
            mig,m5,m10,macc=metric(CODES['migration'])
            meta={'semantics':'native_demographic_trend_not_probability','historical_pit_backtest_allowed':False,'source_vintage':'CURRENT_REVISED_WDI','latest_observation_year':y}
            # Thresholds identify structural state/trajectory only; they are not alpha probabilities.
            if age65 is not None and ((a10 is not None and a10>=3.0) or age65>=20):
                add(out,cc,'DEMOGRAPHY:Aging Acceleration','UP','STRUCTURAL_TREND_LIVE_CONTEXT',age65,a5,a10,aacc,10,[CODES['age65']],meta)
            if working is not None and w10 is not None and w10<=-1.5:
                add(out,cc,'DEMOGRAPHY:Working-Age Population Contraction','DOWN','STRUCTURAL_TREND_LIVE_CONTEXT',working,w5,w10,wacc,10,[CODES['working']],meta)
            if fert is not None and fert<1.6:
                add(out,cc,'DEMOGRAPHY:Low Fertility','DOWN','STRUCTURAL_TREND_LIVE_CONTEXT',fert,f5,f10,facc,10,[CODES['fertility']],meta)
            if urban is not None and u10 is not None and u10>=3.0:
                add(out,cc,'DEMOGRAPHY:Urbanization Expansion','UP','STRUCTURAL_TREND_LIVE_CONTEXT',urban,u5,u10,uacc,10,[CODES['urban']],meta)
            if growth is not None and growth>=0.75:
                add(out,cc,'DEMOGRAPHY:Population Growth','UP','STRUCTURAL_TREND_LIVE_CONTEXT',growth,g5,g10,gacc,5,[CODES['growth'],CODES['pop']],meta)
            if growth is not None and growth<0:
                add(out,cc,'DEMOGRAPHY:Population Contraction','DOWN','STRUCTURAL_TREND_LIVE_CONTEXT',growth,g5,g10,gacc,5,[CODES['growth'],CODES['pop']],meta)
            if youth is not None and youth>=25 and growth is not None and growth>0.5:
                add(out,cc,'DEMOGRAPHY:Youth Bulge','UP','STRUCTURAL_TREND_LIVE_CONTEXT',youth,y5,y10,yacc,10,[CODES['youth'],CODES['growth']],meta)
            if mig is not None and m10 is not None and abs(m10)>0:
                direction='UP' if (m5 or 0)>0 else 'DOWN'
                add(out,cc,'DEMOGRAPHY:Migration Shift',direction,'STRUCTURAL_TREND_LIVE_CONTEXT',mig,m5,m10,macc,5,[CODES['migration']],meta)
        if out:
            c.execute(text("""insert into public.oracle_v6_demographic_trends
              (experiment_id,evaluation_as_of,country_code,trend_key,trend_family,direction,status,level_value,change_5y,change_10y,acceleration,persistence_years,evidence_codes,model_version,metadata)
              values (:e,:a,:cc,:key,'DEMOGRAPHY',:direction,:status,:level,:c5,:c10,:acc,:persist,cast(:codes as jsonb),:m,cast(:meta as jsonb))"""),[dict(r,e=exp,a=cutoff,m=MODEL_VERSION) for r in out])
        summary={'model_version':MODEL_VERSION,'evaluation_as_of':cutoff.isoformat(),'countries_considered':len(countries),'demographic_trends_written':len(out),'trend_family':'DEMOGRAPHY','historical_pit_backtest_allowed':False,'state':'DEMOGRAPHIC_TRENDS_AVAILABLE' if out else 'NO_DEMOGRAPHIC_TRENDS_AVAILABLE'}
        c.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{demographic_trends}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,'experiment_id':exp,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
