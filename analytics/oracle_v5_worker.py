#!/usr/bin/env python3
"""ORACLE V5 external analytics worker.

Heavy walk-forward analytics run outside Supabase. The worker consumes paginated,
compact V5 datasets and writes a static JSON artifact for the investor cockpit.
No model weights are tuned after observing results in this script.
"""
from __future__ import annotations
import json, math, statistics, urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

EXPORT_URL = "https://ayjqeuljbznanmscpzlv.supabase.co/functions/v1/oracle-v5-analytics-export"
OUT = Path("data/v5_analytics.json")


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "ORACLE-V5-Analytics/1.1"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def get_all(kind: str, limit: int = 500) -> list[dict]:
    rows=[]; offset=0
    while True:
        p=get_json(f"{EXPORT_URL}?kind={kind}&offset={offset}&limit={limit}")
        if not p.get("ok"):
            raise RuntimeError(p.get("error", f"export {kind} failed"))
        batch=p.get("rows",[]); rows.extend(batch)
        nxt=p.get("next_offset")
        if nxt is None: break
        offset=int(nxt)
    return rows


def month_add(d: date, months: int) -> date:
    y=d.year+(d.month-1+months)//12; m=(d.month-1+months)%12+1
    return date(y,m,1)


def safe_float(x):
    try:
        v=float(x); return v if math.isfinite(v) else None
    except Exception: return None


def pct_rank(values, v):
    xs=sorted(x for x in values if x is not None and math.isfinite(x))
    if not xs or v is None or not math.isfinite(v): return 0.0
    return 100.0*sum(x<=v for x in xs)/len(xs)


def avg(xs): return statistics.fmean(xs) if xs else None
def med(xs): return statistics.median(xs) if xs else None

def trimmed90(xs):
    if not xs: return None
    ys=sorted(xs); k=max(0,int(len(ys)*0.05)); zs=ys[k:len(ys)-k] if len(ys)-2*k>0 else ys
    return avg(zs)


def model_scores(rows):
    accel=[safe_float(r.get("accel_ratio")) for r in rows]
    src=[safe_float(r.get("source_diversity")) for r in rows]
    sig=[safe_float(r.get("signal_diversity")) for r in rows]
    anc=[safe_float(r.get("anchored_docs")) for r in rows]
    qual=[safe_float(r.get("feature_quality")) for r in rows]
    out={k:[] for k in ["ACCEL_ONLY","ACCEL_EVIDENCE","EARLY_ACCEL","EARLY_QUALITY_MOMENTUM"]}
    for r in rows:
        a=pct_rank(accel,safe_float(r.get("accel_ratio"))); s=pct_rank(src,safe_float(r.get("source_diversity")))
        g=pct_rank(sig,safe_float(r.get("signal_diversity"))); h=pct_rank(anc,safe_float(r.get("anchored_docs")))
        q=pct_rank(qual,safe_float(r.get("feature_quality"))); r6=safe_float(r.get("prior_return_6m")); r12=safe_float(r.get("prior_return_12m"))
        evidence=0.55*a+0.15*s+0.15*g+0.15*h
        pen=0.0
        if r12 is not None and r12>60: pen+=min(35.0,(r12-60)*0.35)
        if r6 is not None and r6>40: pen+=min(20.0,(r6-40)*0.30)
        momentum=50.0
        if r6 is not None:
            if 0<=r6<=40: momentum=80.0
            elif -20<=r6<0: momentum=60.0
            elif 40<r6<=70: momentum=55.0
            elif r6>70: momentum=20.0
            else: momentum=30.0
        quality=0.45*a+0.20*s+0.10*g+0.10*h+0.10*q+0.05*momentum-pen
        out["ACCEL_ONLY"].append((a,r)); out["ACCEL_EVIDENCE"].append((evidence,r)); out["EARLY_ACCEL"].append((evidence-pen,r)); out["EARLY_QUALITY_MOMENTUM"].append((quality,r))
    return out


def build_prices(prices):
    m=defaultdict(dict)
    for p in prices:
        t=str(p.get("ticker") or "").upper(); d=(p.get("price_month") or "")[:10]
        px=safe_float(p.get("adjusted_close")) or safe_float(p.get("close"))
        if t and d and px and px>0: m[t][d]=px
    return m


def latest_before(pm,d):
    z=[(k,v) for k,v in pm.items() if k<d.isoformat()]; return max(z,default=(None,None),key=lambda x:x[0])

def latest_on_or_before(pm,d):
    z=[(k,v) for k,v in pm.items() if k<=d.isoformat()]; return max(z,default=(None,None),key=lambda x:x[0])

def outcome(price_map,ticker,as_of):
    pm=price_map.get(ticker.upper(),{}); _,entry=latest_before(pm,as_of); _,exit6=latest_on_or_before(pm,month_add(as_of,5))
    if not entry or not exit6: return None
    return 100.0*(exit6/entry-1.0)


def stats(picks):
    alphas=[p["alpha_6m"] for p in picks if p.get("alpha_6m") is not None]
    return {"n":len(alphas),"avg_alpha_6m":avg(alphas),"median_alpha_6m":med(alphas),"win_rate_vs_qqq":100.0*sum(a>0 for a in alphas)/len(alphas) if alphas else None,"trimmed_alpha_90pct":trimmed90(alphas),"best_alpha":max(alphas) if alphas else None,"worst_alpha":min(alphas) if alphas else None}

def regime(d):
    if d.year<=2021: return "2017_2021"
    if d.year<=2025: return "2022_2025"
    return "2026_FORWARD"


def main():
    meta=get_json(f"{EXPORT_URL}?kind=meta")
    if not meta.get("ok"): raise RuntimeError(meta.get("error","meta failed"))
    features=get_all("features"); prices=get_all("prices")
    strict=[r for r in features if (r.get("metadata") or {}).get("strict_price_pit") is True]
    if len(strict)!=len(features): raise RuntimeError(f"strict PIT gate failed: {len(strict)}/{len(features)}")
    by_date=defaultdict(list)
    for r in strict: by_date[r["as_of_date"]].append(r)
    price_map=build_prices(prices); picks_by_model=defaultdict(list)
    for ds,rows in sorted(by_date.items()):
        as_of=date.fromisoformat(ds[:10]); qqq=outcome(price_map,"QQQ",as_of)
        if qqq is None: continue
        for model,ranked in model_scores(rows).items():
            ranked.sort(key=lambda z:(-z[0],str(z[1].get("ticker"))))
            for rank,(score,r) in enumerate(ranked[:5],1):
                ticker=str(r.get("ticker") or "").upper(); ret=outcome(price_map,ticker,as_of)
                if ret is None: continue
                picks_by_model[model].append({"as_of_date":ds,"ticker":ticker,"rank":rank,"score":round(score,4),"return_6m":ret,"qqq_return_6m":qqq,"alpha_6m":ret-qqq,"regime":regime(as_of)})
    models={}
    for model,picks in picks_by_model.items():
        overall=stats(picks); regimes={rg:stats([p for p in picks if p["regime"]==rg]) for rg in ["2017_2021","2022_2025","2026_FORWARD"]}
        validated=(overall["n"]>=100 and (overall["median_alpha_6m"] or -999)>0 and (overall["win_rate_vs_qqq"] or 0)>55 and (overall["trimmed_alpha_90pct"] or -999)>0 and all(regimes[rg]["n"]<25 or (regimes[rg]["median_alpha_6m"] or -999)>0 for rg in ["2017_2021","2022_2025"]))
        models[model]={"status":"VALIDATED" if validated else "RESEARCH_ONLY","overall":overall,"regimes":regimes,"latest_picks":sorted(picks,key=lambda p:(p["as_of_date"],-p["rank"]),reverse=True)[:10]}
    result={"ok":True,"engine":"ORACLE_V5_EXTERNAL_WORKER_1_1","source_dataset_version":meta.get("dataset_version"),"source_generated_at":meta.get("generated_at"),"strict_pit":True,"counts":{"features":len(features),"prices":len(prices)},"methodology":{"top_n_per_quarter":5,"horizon_months":6,"benchmark":"QQQ","promotion_gate":"N>=100; median alpha>0; win-rate>55%; trimmed alpha>0; regime stability","weights_predefined":True,"fundamentals_in_model":False,"note":"SEC PIT fundamentals remain separate until historical coverage is sufficient."},"models":models}
    OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(result,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({m:models[m]["overall"] for m in models},indent=2))

if __name__=="__main__": main()
