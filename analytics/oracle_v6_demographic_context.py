#!/usr/bin/env python3
"""ORACLE V6 demographic structural context.

Demography is a slow structural driver, not a short-term alpha signal. This stage
builds descriptive country regimes and transmission hypotheses from the latest
available demographic snapshots. Current World Bank WDI history is revised data,
so these features are LIVE CONTEXT ONLY and are forbidden from historical PIT
backtests until vintage-consistent sources are added.
"""
from __future__ import annotations
import json, os
from collections import defaultdict
from sqlalchemy import create_engine, text

MODEL_VERSION='DEMOGRAPHIC_STRUCTURAL_CONTEXT_V1'
IND={
 'pop':'SP.POP.TOTL','growth':'SP.POP.GROW','fertility':'SP.DYN.TFRT.IN','age65':'SP.POP.65UP.TO.ZS',
 'working':'SP.POP.1564.TO.ZS','youth':'SP.POP.0014.TO.ZS','urban':'SP.URB.TOTL.IN.ZS','migration':'SM.POP.NETM',
 'life':'SP.DYN.LE00.IN','olddep':'SP.POP.DPND.OL'
}

def eng(url:str):
    if url.startswith('postgres://'): url='postgresql+psycopg://'+url[len('postgres://'):]
    elif url.startswith('postgresql://'): url='postgresql+psycopg://'+url[len('postgresql://'):]
    else: raise ValueError('PostgreSQL URL required')
    return create_engine(url,pool_pre_ping=True)

def clamp(x,lo=-3.0,hi=3.0): return max(lo,min(hi,x))
def val(d,k,default=None):
    x=d.get(k)
    return default if x is None else float(x)

def regime(growth,fertility,age65,working_delta,migration_per_1000):
    if age65 is not None and age65>=20 and (working_delta is not None and working_delta<=-1.0):
        return 'AGING_WORKFORCE_CONTRACTION'
    if fertility is not None and fertility<1.6 and migration_per_1000 is not None and migration_per_1000>2:
        return 'LOW_FERTILITY_MIGRATION_SUPPORTED'
    if growth is not None and growth>=1.0 and fertility is not None and fertility>=2.1:
        return 'YOUNG_DEMOGRAPHIC_EXPANSION'
    if growth is not None and growth>=0.5:
        return 'DEMOGRAPHIC_EXPANSION'
    if growth is not None and growth<0:
        return 'POPULATION_CONTRACTION'
    return 'MATURE_STABLE_OR_MIXED'

def run(db_url:str)->dict:
    run_id=os.environ.get('GITHUB_RUN_ID')
    with eng(db_url).begin() as c:
        exp=int(c.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one())
        cutoff=None
        if run_id:
            cutoff=c.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=:r order by evaluation_as_of desc limit 1"),{'e':exp,'r':run_id}).scalar_one_or_none()
        if cutoff is None:
            cutoff=c.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc,id desc limit 1"),{'e':exp}).scalar_one_or_none()
        if cutoff is None: raise RuntimeError('no evaluation clock')
        countries=[str(x) for x in c.execute(text("select country_code from public.oracle_v6_demographic_country_universe where enabled order by weight desc,country_code")).scalars().all()]
        c.execute(text("delete from public.oracle_v6_demographic_regimes where evaluation_as_of=:a and model_version=:m"),{'a':cutoff,'m':MODEL_VERSION})
        c.execute(text("delete from public.oracle_v6_demographic_transmission where evaluation_as_of=:a and model_version=:m"),{'a':cutoff,'m':MODEL_VERSION})
        regime_rows=[]; trans_rows=[]; covered=0
        for cc in countries:
            rows=c.execute(text("""
              select indicator_code,observation_year,value,available_at,metadata
              from public.oracle_v6_demographic_snapshots
              where country_code=:cc and available_at<=:a
              order by indicator_code,observation_year desc,available_at desc
            """),{'cc':cc,'a':cutoff}).mappings().all()
            by=defaultdict(list)
            for r in rows: by[str(r['indicator_code'])].append(r)
            latest={k:(v[0] if v else None) for k,v in by.items()}
            if not latest.get(IND['growth']): continue
            covered+=1
            obs={key:(float(latest[code]['value']) if latest.get(code) and latest[code]['value'] is not None else None) for key,code in IND.items()}
            years=[r['observation_year'] for r in rows if r['observation_year'] is not None]
            maxyr=max(years) if years else None
            def near(code,target):
                rr=[x for x in by.get(code,[]) if x['observation_year']<=target]
                return float(rr[0]['value']) if rr and rr[0]['value'] is not None else None
            working_delta=None; age65_delta=None; urban_delta=None
            if maxyr:
                w0=near(IND['working'],maxyr-10); a0=near(IND['age65'],maxyr-10); u0=near(IND['urban'],maxyr-10)
                if obs['working'] is not None and w0 is not None: working_delta=obs['working']-w0
                if obs['age65'] is not None and a0 is not None: age65_delta=obs['age65']-a0
                if obs['urban'] is not None and u0 is not None: urban_delta=obs['urban']-u0
            migration_per_1000=None
            if obs['migration'] is not None and obs['pop'] not in (None,0): migration_per_1000=obs['migration']/obs['pop']*1000.0
            demand_score=clamp((obs['growth'] or 0)*0.9 + (urban_delta or 0)*0.15 + (migration_per_1000 or 0)*0.08)
            labor_score=clamp((working_delta or 0)*0.35 + (migration_per_1000 or 0)*0.12 + ((obs['fertility'] or 1.8)-1.8)*0.25)
            aging_score=clamp(((obs['age65'] or 12)-12)*0.10 + ((obs['olddep'] or 18)-18)*0.06 + (age65_delta or 0)*0.20)
            rg=regime(obs['growth'],obs['fertility'],obs['age65'],working_delta,migration_per_1000)
            meta={'semantics':'descriptive_structural_context_not_probability','point_in_time_backtest_allowed':False,'source_vintage':'CURRENT_REVISED_WDI','latest_observation_year':maxyr,'working_age_10y_delta_pp':working_delta,'age65_10y_delta_pp':age65_delta,'urbanization_10y_delta_pp':urban_delta,'net_migration_per_1000':migration_per_1000}
            regime_rows.append({'a':cutoff,'cc':cc,'regime':rg,'pg':obs['growth'],'fert':obs['fertility'],'a65':obs['age65'],'wa':obs['working'],'y':obs['youth'],'u':obs['urban'],'mig':obs['migration'],'life':obs['life'],'old':obs['olddep'],'wam':working_delta,'dds':demand_score,'lss':labor_score,'aps':aging_score,'m':MODEL_VERSION,'meta':json.dumps(meta,sort_keys=True)})
            def add(channel,target,direction,score):
                trans_rows.append({'a':cutoff,'cc':cc,'ch':channel,'target':target,'dir':direction,'status':'STRUCTURAL_HYPOTHESIS_UNCALIBRATED','score':score,'m':MODEL_VERSION,'meta':json.dumps({'not_probability':True,'not_trade_signal':True,'requires_company_geographic_exposure':True},sort_keys=True)})
            if aging_score>=0.8:
                for t in ['Healthcare','Medtech','Longevity','Senior Housing','Industrial Automation','Robotics']: add('AGING',t,'TAILWIND',aging_score)
            if working_delta is not None and working_delta<=-1.0:
                for t in ['Industrial Automation','Robotics','AI Software','Labor Productivity']: add('WORKING_AGE_CONTRACTION',t,'TAILWIND',abs(working_delta))
            if urban_delta is not None and urban_delta>=2.0:
                for t in ['Grid Infrastructure','Housing Construction','Transport Infrastructure','Data Centers','Utilities']: add('URBANIZATION',t,'TAILWIND',urban_delta)
            if demand_score>=0.7:
                for t in ['Housing','Consumer Demand','Electricity Demand','Telecom Infrastructure']: add('POPULATION_DEMAND',t,'TAILWIND',demand_score)
            if obs['fertility'] is not None and obs['fertility']<1.6:
                for t in ['Automation','Healthcare','Pensions and Insurance']: add('LOW_FERTILITY',t,'STRUCTURAL_SHIFT',1.6-obs['fertility'])
        if regime_rows:
            c.execute(text("""insert into public.oracle_v6_demographic_regimes
            (evaluation_as_of,country_code,regime,population_growth,fertility,age_65_plus_pct,working_age_pct,youth_pct,urbanization_pct,net_migration,life_expectancy,old_age_dependency,working_age_momentum,demographic_demand_score,labor_supply_score,aging_pressure_score,model_version,metadata)
            values (:a,:cc,:regime,:pg,:fert,:a65,:wa,:y,:u,:mig,:life,:old,:wam,:dds,:lss,:aps,:m,cast(:meta as jsonb))"""),regime_rows)
        if trans_rows:
            c.execute(text("""insert into public.oracle_v6_demographic_transmission
            (evaluation_as_of,country_code,channel,target_concept,direction,evidence_status,score,model_version,metadata)
            values (:a,:cc,:ch,:target,:dir,:status,:score,:m,cast(:meta as jsonb)) on conflict do nothing"""),trans_rows)
        summary={'model_version':MODEL_VERSION,'evaluation_as_of':cutoff.isoformat(),'countries_requested':len(countries),'countries_covered':covered,'regimes_written':len(regime_rows),'transmission_hypotheses':len(trans_rows),'historical_pit_backtest_allowed':False,'state':'DEMOGRAPHIC_CONTEXT_AVAILABLE' if covered else 'NO_DEMOGRAPHIC_CONTEXT'}
        c.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{demographic_context}',cast(:s as jsonb),true) where id=:e"),{'s':json.dumps(summary,sort_keys=True),'e':exp})
    return {'ok':True,'experiment_id':exp,**summary}

if __name__=='__main__': print(json.dumps(run(os.environ.get('ORACLE_SUPABASE_DB_URL','')),sort_keys=True))
