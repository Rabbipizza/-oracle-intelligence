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

def realized_vol(rs, lookback=21):
    xs=[r.get("close") for r in rs[-(lookback+1):] if isinstance(r.get("close"),(int,float)) and r.get("close")>0]
    if len(xs)<3: return None
    rets=[math.log(xs[i]/xs[i-1]) for i in range(1,len(xs))]
    if len(rets)<2: return None
    mu=sum(rets)/len(rets)
    var=sum((x-mu)**2 for x in rets)/(len(rets)-1)
    return math.sqrt(var)*math.sqrt(252)*100.0

def max_drawdown(rs, lookback=63):
    xs=[r.get("close") for r in rs[-lookback:] if isinstance(r.get("close"),(int,float)) and r.get("close")>0]
    if len(xs)<2: return None
    peak=xs[0]; worst=0.0
    for x in xs:
        peak=max(peak,x)
        dd=(x/peak-1.0)*100.0
        worst=min(worst,dd)
    return worst

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
        t=p["ticker"]
        open_weights[t]=round(open_weights.get(t,0.0)+100*float(p.get("allocated_chf",0))/capital,2)
prior_targets=(prior.get("target_allocation_pct") or {})

signals={}
scores={}
targets={}
for ticker,meta in universe.items():
    ev=(evidence.get("companies",{}) or {}).get(ticker)
    r=rows(market,ticker)
    d1=metric(r,1); w1=metric(r,5); m1=metric(r,21)
    vol21=realized_vol(r,21); dd63=max_drawdown(r,63)
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
        "volatility_21d_ann_pct":None if vol21 is None else round(vol21,2),
        "max_drawdown_63d_pct":None if dd63 is None else round(dd63,2),
        "actual_weight_pct":actual_weight,
        "allocation_score":round(0.55*structural+0.45*entry,2),
        "hold_score":round(clamp(
            0.55*structural +
            0.25*entry +
            0.20*clamp(50 + (rel or 0)*2,0,100) -
            (0 if dd63 is None else max(0.0,abs(min(0.0,dd63))-15.0)*0.35),
            0,100
        ),2),
        "target_weight_pct":target,
        "portfolio_action":portfolio_action,
        "invalidation":ev.get("invalidation",[]) if ev else []
    }

# ORACLE V4 — Deploy → Compound → Rotate.
# Principle:
# 1) deploy capital into the best available opportunity set,
# 2) once invested, let positions compound,
# 3) rotate only when a challenger has a materially stronger acceleration edge,
#    or when the incumbent thesis/risk state is invalidated.
q_m1=metric(q,21)
q_vol=realized_vol(q,21)
q_dd=max_drawdown(q,63)

def competition_score(sc, incumbent=False):
    structural=float(sc.get("structural_early_bird") or 0)
    entry=float(sc.get("entry_score") or 0)
    rel=float(sc.get("rel_qqq_1m_pct_points") or 0)
    vol=sc.get("volatility_21d_ann_pct")
    dd=sc.get("max_drawdown_63d_pct")
    base=.50*structural + .50*entry
    relative=clamp(rel*1.5,-15,15)
    vol_penalty=0 if vol is None else max(0.0,vol-30.0)*0.18
    dd_penalty=0 if dd is None else max(0.0,abs(min(0.0,dd))-10.0)*0.45
    hysteresis=3.0 if incumbent else 0.0
    return round(clamp(base+relative-vol_penalty-dd_penalty+hysteresis),2)

for ticker,sc in scores.items():
    sc["capital_competition_score"]=competition_score(sc, float(sc.get("actual_weight_pct") or 0)>0)

qqq_score=60.0
if q_m1 is not None:
    qqq_score += clamp(q_m1*.8,-8,8)
if q_vol is not None:
    qqq_score -= max(0.0,q_vol-25.0)*0.12
if q_dd is not None:
    qqq_score -= max(0.0,abs(min(0.0,q_dd))-10.0)*0.30
qqq_score=round(clamp(qqq_score),2)

# Build eligible challenger set.
challengers=[]
for ticker,sc in scores.items():
    sig=(signals.get(ticker) or {}).get("signal")
    rel=sc.get("rel_qqq_1m_pct_points")
    entry=float(sc.get("entry_score") or 0)
    dd=sc.get("max_drawdown_63d_pct")
    prev_sig=((prior.get("signals",{}) or {}).get(ticker) or {}).get("signal")
    severe_dd=(dd is not None and dd <= -35)
    severe_relative=(rel is not None and rel <= -12 and entry < 45 and prev_sig!="GREEN")
    if sig=="GREEN" and sc.get("evidence_status")=="PROVEN" and not (severe_dd or severe_relative):
        if float(open_weights.get(ticker,0.0) or 0.0)==0.0:
            challengers.append(ticker)

# Incumbent positions are sticky: being ORANGE does not imply exit.
incumbents=[t for t,w in open_weights.items() if w>0 and t in scores]

# Determine best incumbent hold state and best challenger acceleration state.
best_inc=None
best_inc_hold=-1e9
for t in incumbents:
    sc=scores[t]
    if sc.get("evidence_status")!="PROVEN":
        continue
    hs=float(sc.get("hold_score") or 0)
    if hs>best_inc_hold:
        best_inc_hold=hs; best_inc=t

best_chal=None
best_chal_score=-1e9
for t in challengers:
    cs=float(scores[t].get("capital_competition_score") or 0)
    if cs>best_chal_score:
        best_chal_score=cs; best_chal=t

targets={}
rotation_decision={
    "mode":"COMPOUND",
    "best_incumbent":best_inc,
    "best_incumbent_hold_score":None if best_inc is None else round(best_inc_hold,2),
    "best_challenger":best_chal,
    "best_challenger_score":None if best_chal is None else round(best_chal_score,2),
    "rotation_edge":None,
    "reason":""
}

# Detect hard invalidations on incumbents.
invalid_incumbents=[]
for t in incumbents:
    sc=scores[t]
    rel=sc.get("rel_qqq_1m_pct_points")
    entry=float(sc.get("entry_score") or 0)
    dd=sc.get("max_drawdown_63d_pct")
    evidence_broken=sc.get("evidence_status")!="PROVEN"
    risk_broken=(dd is not None and dd<=-35) or (rel is not None and rel<=-15 and entry<40)
    if evidence_broken or risk_broken:
        invalid_incumbents.append(t)

# If capital is not yet substantially deployed, allocate fresh capital.
invested_pct=sum(open_weights.values())
initial_deployment = invested_pct < 50.0

if initial_deployment:
    rotation_decision["mode"]="DEPLOY"
    # Preserve valid incumbent positions. DEPLOY means allocate unused capital,
    # not reset the portfolio to zero.
    for t,w in open_weights.items():
        if t=="QQQ":
            targets[t]=float(w)
        elif t in scores and t not in invalid_incumbents:
            targets[t]=float(w)

    freed=sum(float(open_weights.get(t,0)) for t in invalid_incumbents)
    assigned=sum(targets.values())
    free_capital=round(max(0.0,100.0-assigned),1)

    # Prefer strongest GREEN challenger for the still-unallocated capital.
    if best_chal is not None and best_chal_score >= qqq_score + 4.0:
        sc=scores[best_chal]
        exceptional=(sc.get("structural_early_bird",0)>=95 and sc.get("entry_score",0)>=80 and sc.get("capital_competition_score",0)>=80)
        stock_cap=85.0 if exceptional else 70.0

        # Cap applies to total target weight in that stock, not just the new money.
        room=max(0.0, stock_cap-float(targets.get(best_chal,0.0)))
        add_stock=min(free_capital,room)
        if add_stock>0:
            targets[best_chal]=round(float(targets.get(best_chal,0.0))+add_stock,1)
        residual=round(free_capital-add_stock,1)

        if residual>0:
            targets["QQQ"]=round(float(targets.get("QQQ",0.0))+residual,1)

        rotation_decision["reason"]=f"Initial deployment: preserve valid incumbents and allocate unused capital toward {best_chal}; residual goes to QQQ."
    else:
        qqq_severe=(q_m1 is not None and q_m1<=-13 and q_dd is not None and q_dd<=-17)
        if qqq_severe:
            targets["CASH_CHF"]=round(float(targets.get("CASH_CHF",0.0))+free_capital,1)
            rotation_decision["reason"]="Initial deployment: preserve valid incumbents; unused capital remains cash because QQQ is in severe-risk regime."
        else:
            targets["QQQ"]=round(float(targets.get("QQQ",0.0))+free_capital,1)
            rotation_decision["reason"]="Initial deployment: preserve valid incumbents; unused capital defaults to QQQ because no challenger clears required edge."

else:
    # Preserve incumbents by default. QQQ is a valid portfolio holding even though
    # it is the benchmark rather than a research-universe company.
    for t,w in open_weights.items():
        if t=="QQQ":
            targets[t]=float(w)
        elif t in scores and t not in invalid_incumbents:
            targets[t]=float(w)

    # Exit invalid stock incumbents first. QQQ is governed by its own regime gate.
    freed=sum(float(open_weights.get(t,0)) for t in invalid_incumbents)

    # Rotation requires a challenger to beat incumbent HOLD by a material margin.
    # 12 points = deliberate switching threshold to avoid churn.
    rotation_threshold=12.0
    if best_chal is not None and best_inc is not None:
        rotation_edge=best_chal_score-best_inc_hold
        rotation_decision["rotation_edge"]=round(rotation_edge,2)
        if rotation_edge >= rotation_threshold:
            rotation_decision["mode"]="ROTATE"
            # Rotate only part of the incumbent first; preserve compounding if edge is modest.
            rotate_pct=min(25.0, max(10.0, round((rotation_edge-rotation_threshold)*2.0+10.0,1)))
            available=sum(targets.values())+freed
            rotate_pct=min(rotate_pct,available)
            # Reduce weakest incumbent holdings first.
            ordered=sorted([t for t in incumbents if t in targets], key=lambda t:scores[t].get("hold_score") or 0)
            remaining=rotate_pct
            for t in ordered:
                cut=min(targets[t],remaining)
                targets[t]=round(targets[t]-cut,1)
                remaining=round(remaining-cut,1)
                if remaining<=0: break
            targets[best_chal]=round(targets.get(best_chal,0)+rotate_pct,1)
            rotation_decision["reason"]=f"Rotate {rotate_pct:.1f}% toward {best_chal}: acceleration edge exceeds {rotation_threshold:.1f}-point hurdle."
        else:
            rotation_decision["reason"]=f"Compound incumbents: challenger edge {rotation_edge:.1f} < {rotation_threshold:.1f} rotation hurdle."
    elif best_chal is not None and best_inc is None:
        targets[best_chal]=round(targets.get(best_chal,0)+freed,1)
        rotation_decision["mode"]="ROTATE"
        rotation_decision["reason"]="No valid incumbent remains; redeploy freed capital to strongest qualifying challenger."
    elif freed>0:
        qqq_severe=(q_m1 is not None and q_m1<=-13 and q_dd is not None and q_dd<=-17)
        targets["CASH_CHF" if qqq_severe else "QQQ"]=round(freed,1)
        rotation_decision["mode"]="DEFENSIVE_REALLOCATE"
        rotation_decision["reason"]="Invalid incumbent capital reallocated defensively."

    # Unallocated capital should not sit idle by accident.
    assigned=sum(targets.values())
    residual=round(max(0.0,100.0-assigned),1)
    if residual>0:
        if best_chal is not None and best_chal_score>=qqq_score+4.0:
            targets[best_chal]=round(targets.get(best_chal,0)+residual,1)
        else:
            targets["QQQ"]=round(targets.get("QQQ",0)+residual,1)

# Normalize tiny rounding drift.
tot=sum(targets.values())
if targets and abs(tot-100.0)>0.05:
    k=max(targets,key=targets.get)
    targets[k]=round(targets[k]+(100.0-tot),1)

# Final portfolio actions.
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
        signals[ticker]["reason"] += f" Deploy→Compound→Rotate: HOLD {sc.get('hold_score'):.1f}; acceleration {sc.get('capital_competition_score'):.1f}; ACTUAL {act:.1f}% -> TARGET {tgt:.1f}%."

benchmark_competition={
    "QQQ":{
        "score":qqq_score,
        "m1_pct":None if q_m1 is None else round(q_m1,2),
        "volatility_21d_ann_pct":None if q_vol is None else round(q_vol,2),
        "max_drawdown_63d_pct":None if q_dd is None else round(q_dd,2)
    },
    "rotation":rotation_decision
}

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
    "method":"ORACLE_V4_DEPLOY_COMPOUND_ROTATE",
    "rule":"Deploy capital once into the best available opportunity set, then let incumbents compound. Rotate only when a challenger has a materially stronger acceleration edge than the incumbent HOLD state, or when the incumbent thesis/risk state is invalidated. No leverage; no real orders are executed.",
    "trends":trend_out,
    "signals":signals,
    "scores":scores,
    "target_allocation_pct":targets,
    "actual_holdings_pct":actual,
    "benchmark_competition":benchmark_competition
}
Path("decision-state.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps({"as_of":as_of,"green":[k for k,v in signals.items() if v["signal"]=="GREEN"],"targets":targets},indent=2))
