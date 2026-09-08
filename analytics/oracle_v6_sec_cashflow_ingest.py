#!/usr/bin/env python3
"""ORACLE V6 SEC Companyfacts cash-flow PIT ingestion."""
from __future__ import annotations
import gzip,json,os,time,urllib.request,urllib.error
from datetime import date,datetime,time as dtime,timedelta,timezone
from decimal import Decimal
from sqlalchemy import create_engine,text
MODEL_VERSION="SEC_FCF_ANNUAL_V1"; CAPTURE_MODEL="COMPANY_CAPTURE_EVIDENCE_GATE_V1"
SEC_BASE="https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
USER_AGENT=os.environ.get("ORACLE_SEC_USER_AGENT","ORACLE-V6 research contact https://github.com/Rabbipizza/-oracle-intelligence")
CFO_TAGS=("NetCashProvidedByUsedInOperatingActivities","NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")
CAPEX_TAGS=("PaymentsToAcquirePropertyPlantAndEquipment","PaymentsForAdditionsToPropertyPlantAndEquipment")
WANTED_TAGS=CFO_TAGS+CAPEX_TAGS
def _engine(u):
    if u.startswith("postgres://"):u="postgresql+psycopg://"+u[len("postgres://"):]
    elif u.startswith("postgresql://"):u="postgresql+psycopg://"+u[len("postgresql://"):]
    else:raise ValueError("db_url must be PostgreSQL")
    return create_engine(u,pool_pre_ping=True)
def _d(v):return date.fromisoformat(v) if v else None
def _avail(f):return datetime.combine(f+timedelta(days=1),dtime.min,tzinfo=timezone.utc)
def _fetch(cik):
    req=urllib.request.Request(SEC_BASE.format(cik=str(cik).zfill(10)),headers={"User-Agent":USER_AGENT,"Accept-Encoding":"gzip, deflate","Accept":"application/json","Host":"data.sec.gov"})
    with urllib.request.urlopen(req,timeout=30) as resp:
        raw=resp.read()
        if resp.headers.get("Content-Encoding")=="gzip":raw=gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))
def _iter(ticker,cik,p):
    gaap=p.get("facts",{}).get("us-gaap",{}); url=SEC_BASE.format(cik=str(cik).zfill(10))
    for concept in WANTED_TAGS:
        node=gaap.get(concept)
        if not node:continue
        for x in node.get("units",{}).get("USD",[]):
            filed,end,start,val=_d(x.get("filed")),_d(x.get("end")),_d(x.get("start")),x.get("val"); form=str(x.get("form") or "")
            if filed is None or end is None or val is None or form not in {"10-K","10-K/A","10-Q","10-Q/A"}:continue
            yield {"ticker":ticker,"cik":str(cik).zfill(10),"concept":concept,"unit":"USD","period_start":start,"period_end":end,"filed_date":filed,"available_at":_avail(filed),"accession":x.get("accn"),"form":form,"fiscal_year":x.get("fy"),"fiscal_period":x.get("fp"),"frame":x.get("frame"),"value":Decimal(str(val)),"source_url":url,"availability_quality":"ESTIMATED_CONSERVATIVE_FROM_FILED_DATE","metadata":json.dumps({"taxonomy":"us-gaap","sec_entity_name":p.get("entityName"),"availability_rule":"filed_date_plus_one_day_00_00_utc"},sort_keys=True)}
def _materialize(conn,tickers,cutoff):
    if not tickers:return 0
    rows=conn.execute(text("""with eligible as (select f.*,case when f.concept=any(:cfo) then 'CFO' else 'CAPEX' end kind,row_number() over(partition by f.ticker,f.period_end,case when f.concept=any(:cfo) then 'CFO' else 'CAPEX' end order by case when f.form='10-K' then 0 else 1 end,f.available_at,f.id) rn from public.oracle_v6_sec_cashflow_facts f where f.ticker=any(:t) and f.available_at<=:cutoff and f.form in ('10-K','10-K/A') and f.period_start is not null and (f.period_end-f.period_start) between 300 and 430 and (f.concept=any(:cfo) or f.concept=any(:capex))),picked as (select * from eligible where rn=1) select c.ticker,c.period_end,c.value operating_cash_flow,x.value capex,c.value-x.value free_cash_flow,greatest(c.available_at,x.available_at) as_of,jsonb_build_array(jsonb_build_object('concept',c.concept,'accession',c.accession,'available_at',c.available_at),jsonb_build_object('concept',x.concept,'accession',x.accession,'available_at',x.available_at)) source_accessions from picked c join picked x on x.ticker=c.ticker and x.period_end=c.period_end where c.kind='CFO' and x.kind='CAPEX' and x.value>=0 order by c.ticker,c.period_end"""),{"t":tickers,"cutoff":cutoff,"cfo":list(CFO_TAGS),"capex":list(CAPEX_TAGS)}).mappings().all()
    conn.execute(text("delete from public.oracle_v6_fcf_snapshots where model_version=:m and ticker=any(:t)"),{"m":MODEL_VERSION,"t":tickers})
    payload=[]
    for r in rows:
        d=dict(r); d["source_accessions"]=json.dumps(d["source_accessions"],default=str,sort_keys=True); d["model_version"]=MODEL_VERSION; payload.append(d)
    if payload:conn.execute(text("insert into public.oracle_v6_fcf_snapshots (ticker,as_of,fiscal_period_end,operating_cash_flow,capex,free_cash_flow,source_accessions,source_quality,model_version,metadata) values (:ticker,:as_of,:period_end,:operating_cash_flow,:capex,:free_cash_flow,cast(:source_accessions as jsonb),'SEC_COMPANYFACTS_PIT_CONSERVATIVE',:model_version,jsonb_build_object('fcf_definition','operating_cash_flow_minus_capex','availability_quality','ESTIMATED_CONSERVATIVE_FROM_FILED_DATE'))"),payload)
    return len(payload)
def run(db_url):
    engine=_engine(db_url); run_id=os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp=conn.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one()
        if run_id:cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=cast(:r as text) order by evaluation_as_of desc limit 1"),{"e":int(exp),"r":run_id}).scalar_one_or_none()
        else:cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc limit 1"),{"e":int(exp)}).scalar_one_or_none()
        if cutoff is None:raise RuntimeError("no evaluation clock")
        targets=conn.execute(text("select distinct c.ticker,u.cik from public.oracle_v6_company_capture c join public.oracle_v5_universe u using(ticker) where c.model_version=:m and c.as_of=:c and u.cik is not null and btrim(u.cik)<>'' order by c.ticker"),{"m":CAPTURE_MODEL,"c":cutoff}).mappings().all()
    fetched=0;failed=[];inserted=0
    for t in targets:
        ticker,cik=str(t["ticker"]),str(t["cik"])
        try:
            facts=list(_iter(ticker,cik,_fetch(cik)))
            with engine.begin() as conn:
                if facts:
                    rs=conn.execute(text("insert into public.oracle_v6_sec_cashflow_facts (ticker,cik,concept,unit,period_start,period_end,filed_date,available_at,accession,form,fiscal_year,fiscal_period,frame,value,source_url,availability_quality,metadata) values (:ticker,:cik,:concept,:unit,:period_start,:period_end,:filed_date,:available_at,:accession,:form,:fiscal_year,:fiscal_period,:frame,:value,:source_url,:availability_quality,cast(:metadata as jsonb)) on conflict do nothing"),facts);inserted+=max(rs.rowcount or 0,0)
            fetched+=1
        except urllib.error.HTTPError as exc:failed.append({"ticker":ticker,"error":"HTTPError","status":exc.code,"retry_after":exc.headers.get("Retry-After")})
        except Exception as exc:failed.append({"ticker":ticker,"error":type(exc).__name__})
        time.sleep(.2)
    tickers=[str(t["ticker"]) for t in targets]
    with engine.begin() as conn:
        _materialize(conn,tickers,cutoff);cov=conn.execute(text("select count(*) snapshots,count(distinct ticker) tickers from public.oracle_v6_fcf_snapshots where model_version=:m and as_of<=:c and ticker=any(:t)"),{"m":MODEL_VERSION,"c":cutoff,"t":tickers}).mappings().one();summary={"model_version":MODEL_VERSION,"evaluation_as_of":cutoff.isoformat(),"target_tickers":len(targets),"issuers_fetched":fetched,"issuer_failures":failed,"raw_facts_inserted_this_run":inserted,"annual_fcf_snapshots":int(cov["snapshots"] or 0),"tickers_with_annual_fcf":int(cov["tickers"] or 0),"availability_quality":"ESTIMATED_CONSERVATIVE_FROM_FILED_DATE"};conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{sec_cashflow_pit}',cast(:s as jsonb),true) where id=:e"),{"s":json.dumps(summary,sort_keys=True),"e":int(exp)})
    return {"ok":True,**summary}
def main():print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL","")),sort_keys=True))
if __name__=="__main__":main()
