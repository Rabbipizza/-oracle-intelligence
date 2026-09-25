#!/usr/bin/env python3
"""Recalculate ORACLE decision freshness from explicit evidence + latest market data.
Simulation/research only. Never sends orders.
"""
import json, math
from pathlib import Path
from datetime import datetime, timezone

def load(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {} if default is None else default

def pct(a,b):
    if a is None or b in (None,0): return None
    return (a/b-1.0)*100.0

def clamp(x,a=0,b=100):
    return max(a,min(b,x))

def rows(market,ticker):
    return sorted((market.get("prices",{}).get(ticker) or {}).get("rows",[]), key=lambda r:r.get("date",""))

def metric(rs,n):
    return pct(rs[-1]["close"],rs[-1-n]["close"]) if len(rs)>n else None

market=load("data/market.json")
research=load("research-universe.json")
evidence=load("economic-evidence.json")
prior=load("decision-state.json")
portfolio=load("portfolio.json")
q=rows(market,"QQQ")

fx=market.get("fx_usd_chf") or []
as_of=(fx[-1].get("date") if fx else None) or datetime.now(timezone.utc).date().isoformat()

# Build a lookup from research-universe.
universe={}
for trend_key,tr in research.get("trends",{}).items():
    for row in tr.get("companies",[]):
        ticker,name,role,proof=(row+[None,None,None,None])[:4]
        universe[ticker]={"trend":trend_key,"name":name,"role":role,"legacy_proof":proof}

# Include open holdings even if they are not yet in the research-universe.
for p in portfolio.get("positions",[]):
    if p.get("status")=="OPEN" and p.get("ticker") not in universe:
        ticker=p.get("ticker")
        ev=(evidence.get("companies",{}) or {}).get(ticker,{})
        universe[ticker]={
            "trend":ev.get("trend"),
            "name":ticker,
            "role":ev.get("role","Holding under review"),
            "legacy_proof":"UNPROVEN"
        }

# Trend market stats.
trend_stats={}
for trend_key,tr in research.get("trends",{}).items():
    vals=[]
    for row in tr.get("companies",[])[:20]:
        r=rows(market,row[0])
        x=metric(r,21)
        if x is not None: vals.append(x)
    trend_stats[trend_key]={
        "breadth":(100*sum(1 for x in vals if x>0)/len(vals)) if vals else None,
        "median_m1":sorted(vals)[len(vals)//2] if vals else None
    }

# ACTUAL weights are ledger facts, not recommendations.
capital=float(portfolio.get("initial_capital_chf",1000) or 1000)
open_weights={}
for p in portfolio.get("positions",[]):
    if p.get("status")=="OPEN":
        open_weights[p["ticker"]]=round(100*float(p.get("allocated_chf",0))/capital,2)

signals={}
scores={}
targets={}
for ticker,meta in universe.items():
    ev=(evidence.get("companies",{}) or {}).get(ticker)
    r=rows(market,ticker)
    d1=metric(r,1); w1=metric(r,5); m1=metric(r,21)
    qm1=metric(q,21)
    rel=(m1-qm1) if m1 is not None and qm1 is not None else None
    tstats=trend_stats.get(meta.get("trend"),{})
    breadth=tstats.get("breadth")
    trend_m1=tstats.get("median_m1")

    role_l=(meta.get("role") or "").lower()
    role_score=92 if "bottleneck" in role_l else 90 if "pick" in role_l else 88 if "direct" in role_l else 84 if "leader" in role_l else 70
    explicit_proven=bool(ev and ev.get("status")=="PROVEN")
    proof_score=100 if explicit_proven else 55 if "PARTIAL" in str(meta.get("legacy_proof")) else 35
    structural=round(.65*proof_score+.35*role_score,1)

    entry=50.0
    entry += clamp((rel or 0)*2,-20,20)
    entry += clamp((w1 or 0)*1.2,-12,12)
    entry += clamp((d1 or 0),-6,6)
    entry += clamp((((breadth or 50)-50)*.25),-10,10)
    entry += clamp(((trend_m1 or 0)*.35),-8,8)
    if m1 is not None and m1>30: entry-=8
    entry=round(clamp(entry),1)

    actual_weight=float(open_weights.get(ticker,0) or 0)
    if explicit_proven and structural>=85 and entry>=60:
        signal="GREEN"
        target=0.0
        reason=f"Fresh explicit economic proof; Structural {structural}/100; Entry {entry}/100."
    elif explicit_proven:
        signal="ORANGE"
        target=0.0
        reason=f"Economic chain remains PROVEN; entry confirmation incomplete (Entry {entry}/100)."
    else:
        legacy=(str(meta.get("legacy_proof") or "")).upper().strip()
        if legacy=="UNPROVEN" or not legacy:
            signal="RED"
            target=0.0
            reason="Evidence insufficient for a fresh entry state."
        elif legacy=="PROVEN" or legacy.startswith("PROVEN ") or "PARTIAL" in legacy:
            signal="ORANGE"
            target=0.0
            reason="Prior exposure label exists but has not been revalidated in the explicit evidence registry."
        else:
            signal="RED"
            target=0.0
            reason="Evidence insufficient for a fresh entry state."

    portfolio_action="WAIT"

    signals[ticker]={"signal":signal,"reason":reason,"portfolio_action":portfolio_action}
    scores[ticker]={
        "structural_early_bird":structural,
        "entry_score":entry,
        "trend":meta.get("trend"),
        "role":meta.get("role"),
        "evidence_status":ev.get("status") if ev else "UNREVALIDATED",
        "d1_pct":None if d1 is None else round(d1,2),
        "w1_pct":None if w1 is None else round(w1,2),
        "m1_pct":None if m1 is None else round(m1,2),
        "rel_qqq_1m_pct_points":None if rel is None else round(rel,2),
        "actual_weight_pct":actual_weight,
        "allocation_score":round(0.55*structural+0.45*entry,2),
        "target_weight_pct":target,
        "portfolio_action":portfolio_action,
        "invalidation":ev.get("invalidation",[]) if ev else []
    }

# Global capital allocator.
# Doctrine:
# - one eligible GREEN => 100% target to that GREEN;
# - multiple GREENs => 100% distributed by conviction score;
# - existing ORANGE/RED holdings => 0% when at least one GREEN exists;
# - if no GREEN exists, the best near-GREEN PROVEN candidate may be used as a tactical fallback;
# - otherwise stay in cash. No leverage.
eligible_greens=[]
for ticker,sc in scores.items():
    sig=(signals.get(ticker) or {}).get("signal")
    rel=sc.get("rel_qqq_1m_pct_points")
    entry=sc.get("entry_score") or 0
    # Hard risk exclusion for allocator eligibility.
    risk_ok = not (rel is not None and rel <= -12 and entry < 45)
    if sig=="GREEN" and sc.get("evidence_status")=="PROVEN" and risk_ok:
        eligible_greens.append(ticker)

targets={}
if len(eligible_greens)==1:
    targets[eligible_greens[0]]=100.0
elif len(eligible_greens)>1:
    raw={}
    for ticker in eligible_greens:
        q=max(1.0,(scores[ticker].get("allocation_score") or 0)-60.0)
        raw[ticker]=q*q
    den=sum(raw.values()) or 1.0
    running=0.0
    for i,ticker in enumerate(sorted(eligible_greens,key=lambda t:raw[t],reverse=True)):
        if i==len(eligible_greens)-1:
            w=round(100.0-running,1)
        else:
            w=round(100.0*raw[ticker]/den,1)
            running+=w
        targets[ticker]=w
else:
    # Opportunity-cost fallback: prefer the strongest nearly-GREEN PROVEN name to idle cash.
    near=[]
    for ticker,sc in scores.items():
        if sc.get("evidence_status")!="PROVEN": continue
        entry=sc.get("entry_score") or 0
        structural=sc.get("structural_early_bird") or 0
        rel=sc.get("rel_qqq_1m_pct_points")
        if structural>=85 and entry>=55 and (rel is None or rel>=-5):
            near.append(ticker)
    if near:
        best=max(near,key=lambda t:scores[t].get("allocation_score") or 0)
        targets[best]=100.0

# Final portfolio actions are derived from global TARGET vs ledger ACTUAL.
for ticker,sc in scores.items():
    tgt=float(targets.get(ticker,0.0))
    act=float(sc.get("actual_weight_pct") or 0.0)
    sc["target_weight_pct"]=tgt
    if tgt > act + 0.25:
        action="INCREASE"
    elif tgt < act - 0.25:
        action="EXIT_OR_REDUCE"
    elif act>0:
        action="HOLD"
    else:
        action="WAIT"
    sc["portfolio_action"]=action
    if ticker in signals:
        signals[ticker]["portfolio_action"]=action
        signals[ticker]["reason"] += f" Global allocator: ACTUAL {act:.1f}% -> TARGET {tgt:.1f}%."

# Preserve the structural trend ranking, but stamp the state as freshly recalculated.
trend_out={}
for key,tr in research.get("trends",{}).items():
    old=(prior.get("trends",{}) or {}).get(key,{})
    ts=trend_stats.get(key,{})
    trend_out[key]={
        "rank":old.get("rank"),
        "previous_rank":old.get("previous_rank"),
        "state":old.get("state","UNRANKED"),
        "summary":old.get("summary",""),
        "market_breadth_1m_pct":None if ts.get("breadth") is None else round(ts["breadth"],1),
        "market_median_1m_pct":None if ts.get("median_m1") is None else round(ts["median_m1"],2)
    }

actual=open_weights

out={
    "version":2,
    "as_of":as_of,
    "generated_at":datetime.now(timezone.utc).isoformat(),
    "method":"HYBRID_V2_FULL_CAPITAL_GREEN_ROTATION",
    "rule":"100% of deployable capital targets eligible GREEN signals; if one GREEN exists it receives 100%. Multiple GREENs share capital by conviction. ORANGE/RED are exited when GREEN alternatives exist. Near-GREEN PROVEN fallback is allowed only when no GREEN exists. No leverage; no real orders are executed.",
    "trends":trend_out,
    "signals":signals,
    "scores":scores,
    "target_allocation_pct":targets,
    "actual_holdings_pct":actual
}
Path("decision-state.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps({"as_of":as_of,"green":[k for k,v in signals.items() if v["signal"]=="GREEN"],"targets":targets},indent=2))
