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
    # Position ceiling: base 10%, extendable to 15% only for exceptional conviction.
    # Exceptional = explicit PROVEN + Structural >=95 + Entry >=80.
    # This separates normal concentration control from a high-conviction override.
    normal_ceiling=10.0
    exceptional_ceiling=15.0 if (explicit_proven and structural>=95 and entry>=80) else normal_ceiling

    if explicit_proven and structural>=85 and entry>=60:
        signal="GREEN"
        target=min(exceptional_ceiling,max(4.0,round(4+(entry-60)*.25,1)))
        # A fresh-entry signal may raise the target, but never rewrites ACTUAL.
        if actual_weight>target:
            target=actual_weight
        reason=f"Fresh explicit economic proof; Structural {structural}/100; Entry {entry}/100."
    elif explicit_proven:
        signal="ORANGE"
        # Hybrid doctrine: an already validated, still-PROVEN holding is HOLD,
        # not an automatic liquidation merely because today's entry gate is weak.
        target=actual_weight if actual_weight>0 else 0.0
        if actual_weight>0:
            reason=f"Economic chain remains PROVEN; Entry {entry}/100 does not justify adding. Existing holding: HOLD at {actual_weight:.1f}%."
        else:
            reason=f"Economic chain freshly PROVEN; entry confirmation incomplete (Entry {entry}/100)."
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

    if target > actual_weight + 0.25:
        portfolio_action="INCREASE"
    elif target < actual_weight - 0.25:
        portfolio_action="REVIEW_REDUCE"
    elif actual_weight>0:
        portfolio_action="HOLD"
    else:
        portfolio_action="WAIT"

    # Opportunity-cost doctrine:
    # cash is not treated as neutral when a PROVEN holding is close to GREEN.
    # A near-green existing holding can receive a modest tactical target uplift
    # if Entry is within 5 points of GREEN and relative performance is not materially weak.
    if explicit_proven and actual_weight>0 and signal=="ORANGE":
        near_green = entry >= 55
        rel_ok = (rel is None or rel >= -5)
        if near_green and rel_ok:
            tactical_target=min(normal_ceiling, max(actual_weight, round(actual_weight + min(2.0,(entry-55)*0.4),1)))
            if tactical_target > target:
                target=tactical_target
                portfolio_action="INCREASE_TACTICAL"
                reason += f" Cash opportunity cost applies: near-GREEN holding; tactical target {target:.1f}%."

    # Risk/reduction gate: persistent relative weakness can override HOLD.
    # This does not trigger on one weak day; it requires a materially weak 1M relative move
    # or a broken explicit evidence state.
    if actual_weight>0:
        if not explicit_proven:
            target=0.0
            portfolio_action="REVIEW_EXIT"
            reason += " Existing holding no longer has explicit PROVEN evidence."
        elif rel is not None and rel <= -12 and entry < 45:
            target=max(0.0, round(actual_weight*0.5,1))
            portfolio_action="REVIEW_REDUCE"
            reason += f" Risk gate: 1M relative performance {rel:.1f} pts vs QQQ with weak Entry {entry:.1f}."

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
        "target_weight_pct":target,
        "portfolio_action":portfolio_action,
        "invalidation":ev.get("invalidation",[]) if ev else []
    }
    if target>0: targets[ticker]=target

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
    "method":"HYBRID_V1_EXPLICIT_EVIDENCE_PLUS_ENTRY",
    "rule":"GREEN requires explicit current economic evidence plus fresh entry confirmation. Holdings never create GREEN. No orders are executed.",
    "trends":trend_out,
    "signals":signals,
    "scores":scores,
    "target_allocation_pct":targets,
    "actual_holdings_pct":actual
}
Path("decision-state.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps({"as_of":as_of,"green":[k for k,v in signals.items() if v["signal"]=="GREEN"],"targets":targets},indent=2))
