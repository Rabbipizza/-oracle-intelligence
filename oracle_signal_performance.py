#!/usr/bin/env python3
"""Evaluate prospective ORACLE signal cohorts against QQQ.
No retrospective selection: cohorts are defined by the immutable signal ledger.
"""
import json, math
from pathlib import Path

def load(p,d=None):
    try:return json.loads(Path(p).read_text())
    except Exception:return {} if d is None else d

def rows(market,ticker):
    return sorted(((market.get("prices",{}).get(ticker) or {}).get("rows") or []),key=lambda x:x.get("date",""))

def px_on_or_after(rs,date):
    for r in rs:
        if r.get("date","")>=date:return r.get("close")
    return None

def latest(rs):
    return rs[-1].get("close") if rs else None

def ret(a,b):
    return None if not a or b is None else (b/a-1)*100

def main():
    ledger=load("data/signal-ledger.json",{"events":[]})
    market=load("data/market.json")
    q=rows(market,"QQQ"); qlast=latest(q)
    cohorts={"ALL_DETECTED":[],"TOP20":[],"ORANGE":[],"GREEN":[]}
    evaluated=[]
    for e in ledger.get("events",[]):
        t=e.get("ticker"); d=e.get("market_date"); sig=e.get("signal")
        rs=rows(market,t)
        p0=px_on_or_after(rs,d) if d else None
        p1=latest(rs)
        q0=px_on_or_after(q,d) if d else None
        r=ret(p0,p1); qr=ret(q0,qlast)
        alpha=None if r is None or qr is None else r-qr
        row={**e,"entry_price_evaluated":p0,"current_price":p1,"return_pct":r,"qqq_return_pct":qr,"alpha_pct_points":alpha}
        evaluated.append(row)
        if r is not None:
            cohorts["ALL_DETECTED"].append(row)
            if (e.get("company_rank") or 999)<=20: cohorts["TOP20"].append(row)
            if sig=="ORANGE": cohorts["ORANGE"].append(row)
            if sig=="GREEN": cohorts["GREEN"].append(row)
    summary={}
    for name,xs in cohorts.items():
        alphas=[x["alpha_pct_points"] for x in xs if x.get("alpha_pct_points") is not None]
        rets=[x["return_pct"] for x in xs if x.get("return_pct") is not None]
        qs=[x["qqq_return_pct"] for x in xs if x.get("qqq_return_pct") is not None]
        summary[name]={
            "n":len(xs),
            "equal_weight_return_pct":round(sum(rets)/len(rets),3) if rets else None,
            "matched_qqq_return_pct":round(sum(qs)/len(qs),3) if qs else None,
            "alpha_pct_points":round(sum(alphas)/len(alphas),3) if alphas else None,
            "hit_rate_vs_qqq_pct":round(sum(1 for a in alphas if a>0)/len(alphas)*100,2) if alphas else None
        }
    out={"method":"prospective first-observed cohorts; equal-weight security returns vs date-matched QQQ","cohorts":summary,"events":evaluated}
    Path("data/signal-performance.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
    print(json.dumps(summary))

if __name__=="__main__":
    main()
