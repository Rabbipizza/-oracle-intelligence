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
        open_weights[p["ticker"]]=round(100*float(p.get("allocated_chf",0))/capital,2)

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
        "target_weight_pct":target,
        "portfolio_action":portfolio_action,
        "invalidation":ev.get("invalidation",[]) if ev else []
    }

# ORACLE V3 — Capital Competition Engine.
# Capital competes between eligible stocks, QQQ and cash.
# The allocator rewards economic proof + entry quality + QQQ-relative strength,
# penalizes volatility and drawdown, and gives incumbents a small hysteresis bonus.
q_m1=metric(q,21)
q_vol=realized_vol(q,21)
q_dd=max_drawdown(q,63)

def competition_score(sc, incumbent=False):
    structural=float(sc.get("structural_early_bird") or 0)
    entry=float(sc.get("entry_score") or 0)
    rel=float(sc.get("rel_qqq_1m_pct_points") or 0)
    vol=sc.get("volatility_21d_ann_pct")
    dd=sc.get("max_drawdown_63d_pct")
    # Conviction core: proof/structure + current entry quality.
    base=.50*structural + .50*entry
    # Relative edge: reward outperformance, penalize sustained underperformance.
    relative=clamp(rel*1.5,-15,15)
    # Risk penalty: only excess risk above a moderate equity baseline is punished.
    vol_penalty=0 if vol is None else max(0.0,vol-30.0)*0.18
    dd_penalty=0 if dd is None else max(0.0,abs(min(0.0,dd))-10.0)*0.45
    hysteresis=3.0 if incumbent else 0.0
    return round(clamp(base+relative-vol_penalty-dd_penalty+hysteresis),2)

for ticker,sc in scores.items():
    sc["capital_competition_score"]=competition_score(sc, float(sc.get("actual_weight_pct") or 0)>0)

# QQQ baseline score: liquid diversified default deployment vehicle.
# It gets no structural alpha premium, but avoids single-name concentration penalty.
qqq_score=60.0
if q_m1 is not None:
    qqq_score += clamp(q_m1*.8,-8,8)
if q_vol is not None:
    qqq_score -= max(0.0,q_vol-25.0)*0.12
if q_dd is not None:
    qqq_score -= max(0.0,abs(min(0.0,q_dd))-10.0)*0.30
qqq_score=round(clamp(qqq_score),2)

# Hard safety gate: a stock cannot compete if evidence is not PROVEN,
# drawdown is extreme, or relative weakness + weak Entry signals deterioration.
eligible=[]
for ticker,sc in scores.items():
    sig=(signals.get(ticker) or {}).get("signal")
    rel=sc.get("rel_qqq_1m_pct_points")
    entry=float(sc.get("entry_score") or 0)
    dd=sc.get("max_drawdown_63d_pct")
    hard_risk = (dd is not None and dd <= -35) or (rel is not None and rel <= -12 and entry < 45)
    if sig=="GREEN" and sc.get("evidence_status")=="PROVEN" and not hard_risk:
        eligible.append(ticker)

# Near-GREEN incumbents may remain in the competition, but only with proven evidence,
# Entry >=55, and no material relative weakness. This is the hysteresis / anti-churn rule.
for ticker,sc in scores.items():
    if ticker in eligible: continue
    act=float(sc.get("actual_weight_pct") or 0)
    if act<=0 or sc.get("evidence_status")!="PROVEN": continue
    entry=float(sc.get("entry_score") or 0)
    rel=sc.get("rel_qqq_1m_pct_points")
    if entry>=55 and (rel is None or rel>=-5):
        eligible.append(ticker)

# Candidate set always includes QQQ. Cash is a defensive reserve only if the whole
# opportunity set is weak or QQQ itself enters a severe risk regime.
candidate_scores={t:scores[t]["capital_competition_score"] for t in eligible}
candidate_scores["QQQ"]=qqq_score

qqq_severe_risk = (
    (q_m1 is not None and q_m1 <= -12) and
    (q_dd is not None and q_dd <= -15)
)

targets={}
cash_target=0.0

if not candidate_scores:
    cash_target=100.0
else:
    # Keep only candidates close enough to the best score to deserve capital.
    best=max(candidate_scores.values())
    active={k:v for k,v in candidate_scores.items() if v >= best-8.0}

    # If no stock beats QQQ by at least 4 score points, QQQ becomes the default allocation.
    stock_best=max([v for k,v in active.items() if k!="QQQ"], default=-1e9)
    if stock_best < qqq_score + 4.0:
        active={"QQQ":qqq_score}

    if qqq_severe_risk and set(active)=={"QQQ"}:
        cash_target=100.0
        active={}

    if active:
        # Softmax-style allocation by score; avoids binary all-in switches.
        exps={k:math.exp((v-best)/8.0) for k,v in active.items()}
        den=sum(exps.values()) or 1.0
        raw={k:100.0*exps[k]/den for k in active}

        # Single-name concentration guardrail:
        # 70% normal; up to 85% only for exceptional proven conviction.
        stock_keys=[k for k in raw if k!="QQQ"]
        for k in stock_keys:
            sc=scores[k]
            exceptional=(sc.get("structural_early_bird",0)>=95 and sc.get("entry_score",0)>=80 and sc.get("capital_competition_score",0)>=80)
            cap=85.0 if exceptional else 70.0
            if raw[k]>cap:
                excess=raw[k]-cap
                raw[k]=cap
                raw["QQQ"]=raw.get("QQQ",0)+excess

        # Round while preserving 100%.
        items=sorted(raw.items(),key=lambda kv:kv[1],reverse=True)
        running=0.0
        for i,(k,v) in enumerate(items):
            w=round(100.0-running,1) if i==len(items)-1 else round(v,1)
            running+=w
            targets[k]=w

if cash_target>0:
    targets["CASH_CHF"]=round(cash_target,1)

# Final portfolio actions derive from global TARGET vs ledger ACTUAL.
# QQQ/CASH may appear in TARGET even when not currently held.
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
        signals[ticker]["reason"] += f" Capital Competition: score {sc.get('capital_competition_score'):.1f}; ACTUAL {act:.1f}% -> TARGET {tgt:.1f}%."

benchmark_competition={
    "QQQ":{
        "score":qqq_score,
        "m1_pct":None if q_m1 is None else round(q_m1,2),
        "volatility_21d_ann_pct":None if q_vol is None else round(q_vol,2),
        "max_drawdown_63d_pct":None if q_dd is None else round(q_dd,2)
    },
    "cash_target_pct":round(cash_target,1)
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
    "method":"ORACLE_V3_CAPITAL_COMPETITION_ENGINE",
    "rule":"Capital competes among eligible PROVEN stocks, QQQ and cash. Allocation uses conviction, QQQ-relative strength, volatility, drawdown and incumbent hysteresis. Stocks must beat QQQ sufficiently to earn capital. No leverage; no real orders are executed.",
    "trends":trend_out,
    "signals":signals,
    "scores":scores,
    "target_allocation_pct":targets,
    "actual_holdings_pct":actual,
    "benchmark_competition":benchmark_competition
}
Path("decision-state.json").write_text(json.dumps(out,indent=2),encoding="utf-8")
print(json.dumps({"as_of":as_of,"green":[k for k,v in signals.items() if v["signal"]=="GREEN"],"targets":targets},indent=2))
