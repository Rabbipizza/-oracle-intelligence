#!/usr/bin/env python3
"""Materialize V6 financial PIT snapshots from raw SEC facts only.

No network access occurs here. Latest fact vintage available by evaluation time
wins. FCF requires CFO and capex on the same annual period. Position combines
cash/debt at a balance-sheet date with the latest canonical DEI shares fact
available by the same evaluation time; the shares fact may have a different
instant date and its provenance is retained explicitly.
"""
from __future__ import annotations
import json, os
from collections import defaultdict
from decimal import Decimal
from sqlalchemy import create_engine, text

FCF_MODEL="SEC_FCF_ANNUAL_V1"
POSITION_MODEL="SEC_POSITION_V1"
CFO={"netcashprovidedbyusedinoperatingactivities","netcashprovidedbyusedinoperatingactivitiescontinuingoperations"}
CAPEX={"paymentstoacquirepropertyplantandequipment","paymentsforadditionstopropertyplantandequipment"}
CASH_ORDER=["cashandcashequivalentsatcarryingvalue","cashcashequivalentsrestrictedcashandrestrictedcashequivalents"]
SHARES="entitycommonstocksharesoutstanding"
CURR_DEBT_ORDER=["longtermdebtcurrent","longtermdebtandfinanceleaseobligationscurrent","shorttermdebtcurrent"]
NONCURR_DEBT_ORDER=["longtermdebtnoncurrent","longtermdebtandfinanceleaseobligationsnoncurrent"]
SHORT_ORDER=["shorttermborrowings"]

def _engine(u):
    if u.startswith("postgres://"):u="postgresql+psycopg://"+u[len("postgres://"):]
    elif u.startswith("postgresql://"):u="postgresql+psycopg://"+u[len("postgresql://"):]
    else:raise ValueError("db_url must be PostgreSQL")
    return create_engine(u,pool_pre_ping=True)

def _latest_for(names, facts):
    for name in names:
        q=[f for f in facts if f["concept"].lower()==name]
        if q:return max(q,key=lambda x:(x["available_at"],x["filed_date"],x["id"]))
    return None

def run(db_url):
    engine=_engine(db_url); run_id=os.environ.get("GITHUB_RUN_ID")
    with engine.begin() as conn:
        exp=conn.execute(text("select id from public.oracle_v6_experiments where model_family='COUNT_NULL_MODEL' and model_version='FORMAL_COUNT_NULL_V1' and invalidated_at is null order by created_at desc,id desc limit 1")).scalar_one()
        if run_id:
            cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e and external_run_id=cast(:r as text) order by evaluation_as_of desc limit 1"),{"e":int(exp),"r":run_id}).scalar_one_or_none()
        else:cutoff=conn.execute(text("select evaluation_as_of from public.oracle_v6_evaluation_runs where experiment_id=:e order by evaluation_as_of desc limit 1"),{"e":int(exp)}).scalar_one_or_none()
        if cutoff is None:raise RuntimeError("no evaluation clock")
        tickers=[str(x) for x in conn.execute(text("select distinct ticker from public.oracle_v6_company_capture where model_version='COMPANY_CAPTURE_EVIDENCE_GATE_V1' and as_of=:c order by ticker"),{"c":cutoff}).scalars().all()]

        # FCF: latest available vintage per economic component and annual period.
        cf=conn.execute(text("select id,ticker,concept,period_start,period_end,filed_date,available_at,accession,form,value,source_url,availability_quality from public.oracle_v6_sec_cashflow_facts where ticker=any(:t) and available_at<=:c and form in ('10-K','10-K/A') and period_start is not null and (period_end-period_start) between 300 and 430 order by ticker,period_end,available_at,id"),{"t":tickers,"c":cutoff}).mappings().all()
        by_period=defaultdict(list)
        for r in cf:by_period[(str(r["ticker"]),r["period_end"])].append(dict(r))
        fcf_payload=[]
        for (ticker,end),facts in by_period.items():
            cfo_candidates=[f for f in facts if f["concept"].lower() in CFO]
            capex_candidates=[f for f in facts if f["concept"].lower() in CAPEX]
            if not cfo_candidates or not capex_candidates:continue
            cfo=max(cfo_candidates,key=lambda x:(x["available_at"],x["id"])); capex=max(capex_candidates,key=lambda x:(x["available_at"],x["id"]))
            if Decimal(str(capex["value"]))<0:continue
            fcf_payload.append({"ticker":ticker,"as_of":max(cfo["available_at"],capex["available_at"]),"end":end,"cfo":cfo["value"],"capex":capex["value"],"fcf":Decimal(str(cfo["value"]))-Decimal(str(capex["value"])),"sources":json.dumps([{"id":cfo["id"],"concept":cfo["concept"],"accession":cfo["accession"],"available_at":cfo["available_at"].isoformat(),"source_url":cfo["source_url"]},{"id":capex["id"],"concept":capex["concept"],"accession":capex["accession"],"available_at":capex["available_at"].isoformat(),"source_url":capex["source_url"]}],sort_keys=True)})
        conn.execute(text("delete from public.oracle_v6_fcf_snapshots where model_version=:m and ticker=any(:t)"),{"m":FCF_MODEL,"t":tickers})
        if fcf_payload:conn.execute(text("insert into public.oracle_v6_fcf_snapshots (ticker,as_of,fiscal_period_end,operating_cash_flow,capex,free_cash_flow,source_accessions,source_quality,model_version,metadata) values (:ticker,:as_of,:end,:cfo,:capex,:fcf,cast(:sources as jsonb),'SEC_PRIMARY_PIT',:m,jsonb_build_object('fcf_definition','CFO minus capex','vintage_policy','latest_available_by_evaluation'))"),[dict(x,m=FCF_MODEL) for x in fcf_payload])

        # Position facts. Cash/debt are grouped by balance date; shares are latest canonical DEI fact independently.
        pf=conn.execute(text("select id,ticker,taxonomy,concept,period_end,filed_date,available_at,accession,form,value,source_url,availability_quality from public.oracle_v6_sec_position_facts where ticker=any(:t) and available_at<=:c order by ticker,period_end,available_at,id"),{"t":tickers,"c":cutoff}).mappings().all()
        by_ticker=defaultdict(list)
        for r in pf:by_ticker[str(r["ticker"])].append(dict(r))
        pos_payload=[]
        for ticker,facts in by_ticker.items():
            share_candidates=[f for f in facts if f["taxonomy"].lower()=="dei" and f["concept"].lower()==SHARES and Decimal(str(f["value"]))>0]
            if not share_candidates:continue
            shares=max(share_candidates,key=lambda x:(x["available_at"],x["period_end"],x["id"]))
            periods=sorted({f["period_end"] for f in facts if f["concept"].lower()!=SHARES},reverse=True)
            selected=None
            for end in periods:
                fs=[f for f in facts if f["period_end"]==end]
                cash=_latest_for(CASH_ORDER,fs); dc=_latest_for(CURR_DEBT_ORDER,fs); dn=_latest_for(NONCURR_DEBT_ORDER,fs); sb=_latest_for(SHORT_ORDER,fs)
                debts=[x for x in (dc,dn,sb) if x is not None]
                if cash is not None and debts:
                    selected=(end,cash,debts);break
            if selected is None:continue
            end,cash,debts=selected; debt=sum((Decimal(str(x["value"])) for x in debts),Decimal("0"))
            if Decimal(str(cash["value"]))<0 or debt<0:continue
            comps=[cash,shares]+debts
            pos_payload.append({"ticker":ticker,"as_of":max(x["available_at"] for x in comps),"end":end,"shares":shares["value"],"cash":cash["value"],"debt":debt,"sources":json.dumps([{"id":x["id"],"taxonomy":x["taxonomy"],"concept":x["concept"],"period_end":x["period_end"].isoformat(),"accession":x["accession"],"available_at":x["available_at"].isoformat(),"source_url":x["source_url"]} for x in comps],sort_keys=True)})
        conn.execute(text("delete from public.oracle_v6_position_snapshots where model_version=:m and ticker=any(:t)"),{"m":POSITION_MODEL,"t":tickers})
        if pos_payload:conn.execute(text("insert into public.oracle_v6_position_snapshots (ticker,as_of,fiscal_period_end,shares_outstanding,cash,debt,source_components,source_quality,model_version,metadata) values (:ticker,:as_of,:end,:shares,:cash,:debt,cast(:sources as jsonb),'SEC_PRIMARY_PIT',:m,jsonb_build_object('shares_definition','dei.EntityCommonStockSharesOutstanding','shares_date_can_differ_from_balance_date',true,'vintage_policy','latest_available_by_evaluation'))"),[dict(x,m=POSITION_MODEL) for x in pos_payload])
        summary={"model_version":"SEC_MATERIALIZER_V1","evaluation_as_of":cutoff.isoformat(),"candidate_tickers":len(tickers),"fcf_snapshots":len(fcf_payload),"fcf_tickers":len({x['ticker'] for x in fcf_payload}),"position_snapshots":len(pos_payload),"position_tickers":len({x['ticker'] for x in pos_payload})}
        conn.execute(text("update public.oracle_v6_experiments set metrics=jsonb_set(coalesce(metrics,'{}'::jsonb),'{sec_materializer}',cast(:s as jsonb),true) where id=:e"),{"s":json.dumps(summary,sort_keys=True),"e":int(exp)})
    return {"ok":True,**summary}
def main():print(json.dumps(run(os.environ.get("ORACLE_SUPABASE_DB_URL","")),sort_keys=True))
if __name__=="__main__":main()
