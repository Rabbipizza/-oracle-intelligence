#!/usr/bin/env python3
"""ORACLE V6 SEC Companyfacts PIT position ingestion.

Fetches only currently investable company-capture candidates. It preserves raw
SEC facts for shares, cash and debt, then materializes a position snapshot only
when all required components can be supported at a common fiscal period end.
No proxy from narrative evidence is allowed.
"""
from __future__ import annotations
import json, os, time, urllib.request, urllib.error
from collections import defaultdict
from datetime import date, datetime, time as dtime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import create_engine, text
MODEL_VERSION="SEC_POSITION_V1"; CAPTURE_MODEL="COMPANY_CAPTURE_EVIDENCE_GATE_V1"
SEC_BASE="https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
USER_AGENT=os.environ.get("ORACLE_SEC_USER_AGENT","ORACLE-V6 research contact https://github.com/Rabbipizza/-oracle-intelligence")
CASH_TAGS=(("us-gaap","CashAndCashEquivalentsAtCarryingValue"),("us-gaap","CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"))
SHARES_TAGS=(("dei","EntityCommonStockSharesOutstanding"),)
CURRENT_DEBT_TAGS=(("us-gaap","LongTermDebtCurrent"),("us-gaap","LongTermDebtAndFinanceLeaseObligationsCurrent"),("us-gaap","ShortTermDebtCurrent"))
NONCURRENT_DEBT_TAGS=(("us-gaap","LongTermDebtNoncurrent"),("us-gaap","LongTermDebtAndFinanceLeaseObligationsNoncurrent"))
SHORT_BORROWING_TAGS=(("us-gaap","ShortTermBorrowings"),)
ALL_TAGS=CASH_TAGS+SHARES_TAGS+CURRENT_DEBT_TAGS+NONCURRENT_DEBT_TAGS+SHORT_BORROWING_TAGS
def _engine(db_url):
    if db_url.startswith("postgres://"): db_url="postgresql+psycopg://"+db_url[len("postgres://"):]
    elif db_url.startswith("postgresql://"): db_url="postgresql+psycopg://"+db_url[len("postgresql://"):]
    else: raise ValueError("db_url must be PostgreSQL")
    return create_engine(db_url,pool_pre_ping=True)
def _parse_date(v): return date.fromisoformat(v) if v else None
def _availability_from_filed(filed): return datetime.combine(filed+timedelta(days=1),dtime.min,tzinfo=timezone.utc)
def _fetch_companyfacts(cik):
    req=urllib.request.Request(SEC_BASE.format(cik=str(cik).zfill(10)),headers={"User-Agent":USER_AGENT,"Accept-Encoding":"gzip, deflate","Accept":"application/json","Host":"data.sec.gov"})
    with urllib.request.urlopen(req,timeout=30) as resp:
        raw=resp.read()
        if resp.headers.get("Content-Encoding")=="gzip":
            import gzip; raw=gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))
def _expected_unit(taxonomy,concept): return "shares" if (taxonomy,concept) in SHARES_TAGS else "USD"
def _iter_rows(ticker,cik,payload):
    source_url=SEC_BASE.format(cik=str(cik).zfill(10))
    for taxonomy,concept in ALL_TAGS:
        node=payload.get("facts",{}).get(taxonomy,{}).get(concept)
        if not node: continue
        unit=_expected_unit(taxonomy,concept)
        for item in node.get("units",{}).get(unit,[]):
            filed,end,val=_parse_date(item.get("filed")),_parse_date(item.get("end")),item.get("val"); form=str(item.get("form") or "")
            if filed is None or end is None or val is None or form not in {"10-K","10-K/A","10-Q","10-Q/A"}: continue
            yield {"ticker":ticker,"cik":str(cik).zfill(10),"taxonomy":taxonomy,"concept":concept,"unit":unit,"period_end":end,"filed_date":filed,"available_at":_availability_from_filed(filed),"accession":item.get("accn"),"form":form,"fiscal_year":item.get("fy"),"fiscal_period":item.get("fp"),"value":Decimal(str(val)),"source_url":source_url,"availability_quality":"ESTIMATED_CONSERVATIVE_FROM_FILED_DATE","metadata":json.dumps({"sec_entity_name":payload.get("entityName"),"availability_rule":"filed_date_plus_one_day_00_00_utc"},sort_keys=True)}
def _component(tags,facts):
    for taxonomy,concept in tags:
        e=[f for f in facts if f["taxonomy"]==taxonomy and f["concept"]==concept]
        if e:return sorted(e,key=lambda r:(r["available_at"],r["filed_date"]))[0]
    return None
def _materialize(conn,tickers,cutoff):
    if not tickers:return 0
    rows=conn.execute(text("select ticker,taxonomy,concept,unit,period_end,filed_date,available_at,accession,form,fiscal_year,fiscal_period,value,source_url from public.oracle_v6_sec_position_facts where ticker=any(:tickers) and available_at<=:cutoff order by ticker,period_end,available_at,id"),{"tickers":tickers,"cutoff":cutoff}).mappings().all(); by_period=defaultdict(list)
    for r in rows:by_period[(str(r["ticker"]),r["period_end"])].append(dict(r))
    snapshots=[]
    for (ticker,period_end),facts in by_period.items():
        cash=_component(CASH_TAGS,facts); shares=_component(SHARES_TAGS,facts); dc=_component(CURRENT_DEBT_TAGS,facts); dn=_component(NONCURRENT_DEBT_TAGS,facts); sb=_component(SHORT_BORROWING_TAGS,facts)
        if cash is None or shares is None:continue
        debt_parts=[x for x in (dc,dn,sb) if x is not None]
        if not debt_parts:continue
        debt=sum((Decimal(str(x["value"])) for x in debt_parts),Decimal("0")); comps=[cash,shares]+debt_parts
        snapshots.append({"ticker":ticker,"as_of":max(x["available_at"] for x in comps),"period_end":period_end,"shares":Decimal(str(shares["value"])),"cash":Decimal(str(cash["value"])),"debt":debt,"source_components":json.dumps([{"taxonomy":x["taxonomy"],"concept":x["concept"],"accession":x["accession"],"available_at":x["available_at"].isoformat()} for x in comps],sort_keys=True)})
    conn.execute(text("delete from public.oracle_v6_position_snapshots where model_version=:m and ticker=any(:t)"),{"m":MODEL_VERSION,"t":tickers})
    if snapshots:conn.execute(text("insert into public.oracle_v6_position_snapshots (ticker,as_of,fiscal_period_end,shares_outstanding,cash,debt,source_components,source_quality,model_version,metadata) values (:ticker,:as_of,:period_end,:shares,:cash,:debt,cast(:source_components as jsonb),'SEC_COMPANYFACTS_PIT_CONSERVATIVE',:model,jsonb_build_object('availability_quality','ESTIMATED_CONSERVATIVE_FROM_FILED_DATE','shares_definition','dei.EntityCommonStockSharesOutstanding only'))"),[dict(s,model=MODEL_VERSION) for s in snapshots])
    return len(snapshots)
def run(db_url):
    engine=_engine(db_url); run_id=os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp=conn.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one()
        if run_id:
            cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:exp and external_run_id=cast(:run_id as text) order by evaluation_as_of desc,id desc limit 1"),{"exp":int(exp),"run_id":run_id}).scalar_one_or_none()
        else: cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:exp order by evaluation_as_of desc,id desc limit 1"),{"exp":int(exp)}).scalar_one_or_none()
        if cutoff is None:raise RuntimeError("no evaluation clock")
        targets=conn.execute(text("select distinct c.ticker,u.cik from public.oracle_v6_company_capture c join public.oracle_v5_universe u on u.ticker=c.ticker where c.model_version=:m and c.as_of=:c and u.cik is not null and btrim(u.cik)<>'' order by c.ticker"),{"m":CAPTURE_MODEL,"c":cutoff}).mappings().all()
    fetched=0; failed=[]; inserted=0
    for t in targets:
        ticker,cik=str(t["ticker"]),str(t["cik"])
        try:
            facts=list(_iter_rows(ticker,cik,_fetch_companyfacts(cik)))
            with engine.begin() as conn:
                if facts:
                    result=conn.execute(text("insert into public.oracle_v6_sec_position_facts (ticker,cik,taxonomy,concept,unit,period_end,filed_date,available_at,accession,form,fiscal_year,fiscal_period,value,source_url,availability_quality,metadata) values (:ticker,:cik,:taxonomy,:concept,:unit,:period_end,:filed_date,:available_at,:accession,:form,:fiscal_year,:fiscal_period,:value,:source_url,:availability_quality,cast(:metadata as jsonb)) on conflict do nothing"),facts); inserted+=max(result.rowcount or 0,0)
            fetched+=1
        except urllib.error.HTTPError as exc: failed.append({"ticker":ticker,"error":"HTTPError","status":exc.code,"retry_after":exc.headers.get("Retry-After")})
        except Exception as exc: failed.append({"ticker":ticker,"error":type(exc).__name__})
        time.sleep(.2)
    tickers=[str(t["ticker"]) for t in targets]
    with engine.begin() as conn:
        _materialize(conn,tickers,cutoff); cov=conn.execute(text("select count(*) snapshots,count(distinct ticker) tickers from public.oracle_v6_position_snapshots where model_version=:m and as_of<=:c and ticker=any(:t)"),{"m":MODEL_VERSION,"c":cutoff,"t":tickers}).mappings().one()
        summary={"model_version":MODEL_VERSION,"evaluation_as_of":cutoff.isoformat(),"target_tickers":len(targets),"issuers_fetched":fetched,"issuer_failures":failed,"raw_position_facts_inserted_this_run":inserted,"position_snapshots":int(cov["snapshots"] or 0),"tickers_with_position":int(cov["tickers"] or 0),"availability_quality":"ESTIMATED_CONSERVATIVE_FROM_FILED_DATE"}
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{sec_position_pit}',cast(:s as jsonb),true) where id=:e"),{"s":json.dumps(summary,sort_keys=True),"e":int(exp)})
    return {"ok":True,**summary}
def main():print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL","")),sort_keys=True))
if __name__=="__main__":main()
