#!/usr/bin/env python3
"""ORACLE POWER 10 v1 — prospective ignition/portfolio research engine.
Research/simulation only. Never sends orders. No look-ahead: uses only current cockpit + first-observed ledger.
"""
import json, math, pathlib
from datetime import datetime, timezone

ROOT=pathlib.Path(__file__).parent
DATA=ROOT/"data"
CAPITAL=50000.0
MAX_POSITION=0.15
MAX_DEPLOYED=0.60

def load(name, default):
    p=DATA/name
    return json.loads(p.read_text()) if p.exists() else default

def clamp(x,a=0,b=100): return max(a,min(b,x))

cockpit=load("cockpit.json",{})
ledger=load("signal-ledger.json",{"events":[]})
state=load("power10-state.json",{"version":1,"initial_capital_chf":CAPITAL,"cash_chf":CAPITAL,"positions":[],"decisions":[]})

trends={t.get("label"):t for t in cockpit.get("trends",[])}
first_seen={}
for e in ledger.get("events",[]):
    k=e.get("ticker")
    if k and (k not in first_seen or e.get("observed_at","")<first_seen[k].get("observed_at","")): first_seen[k]=e

candidates=[]
for trend in cockpit.get("trends",[]):
    m=trend.get("market") or {}
    breadth=float(m.get("breadth_positive_1m_pct") or 0)
    trend_m1=float(m.get("median_1m_pct") or 0)
    for c in trend.get("companies",[]):
        ticker=c.get("ticker")
        proof=c.get("proof","UNPROVEN")
        if proof=="UNPROVEN": continue
        m1=float(c.get("m1") or 0)
        rel=float(c.get("rel_m1_qqq") or 0)
        signal=c.get("signal","RED")
        role=(c.get("role") or "").lower()
        proof_score=100 if proof=="PROVEN" else 65
        role_score=95 if ("bottleneck" in role or "pick" in role) else 80 if ("direct" in role or "leader" in role) else 60
        structural=clamp(.60*proof_score+.40*role_score)
        # v1 ignition: confirmation, not prediction. Thresholds are frozen before prospective test.
        ignition=clamp(50 + 2.0*rel + .30*(breadth-50) + 1.0*trend_m1)
        early=70 if ticker in first_seen else 45
        power=round(.45*structural+.35*ignition+.20*early,1)
        status="POWER" if power>=78 and ignition>=60 and proof=="PROVEN" else "ARMED" if power>=68 else "WATCH"
        target=round(MAX_POSITION*CAPITAL,2) if status=="POWER" else 0
        candidates.append({"ticker":ticker,"trend":trend.get("label"),"role":c.get("role"),"proof":proof,"signal":signal,
          "structural_score":round(structural,1),"early_bird_score":early,"ignition_score":round(ignition,1),
          "power_score":power,"status":status,"target_cap_chf":target,"m1_pct":m1,"relative_qqq_1m_pct_points":rel,
          "breadth_1m_pct":breadth,"first_observed_at":(first_seen.get(ticker) or {}).get("observed_at")})
candidates.sort(key=lambda x:x["power_score"],reverse=True)
# Risk budget: at most 60% deployed, max 15% per position; this file only recommends simulation targets.
remaining=MAX_DEPLOYED*CAPITAL
for c in candidates:
    if c["target_cap_chf"]:
        alloc=min(c["target_cap_chf"],remaining); c["target_cap_chf"]=alloc; remaining-=alloc
    if remaining<=0: c["target_cap_chf"]=0

out={"version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"PROSPECTIVE_SIMULATION_ONLY",
 "initial_capital_chf":CAPITAL,"objective":{"milestone_pct":10,"next_high_water_mark_chf":55000},
 "risk":{"max_position_pct":15,"max_deployed_pct":60,"forced_take_profit":False,
 "rule":"+10% is a portfolio milestone, not a guaranteed take-profit. Exit on invalidation/trailing/time-stop to be validated prospectively."},
 "method":{"frozen_v1":True,"note":"Scores are hypotheses to validate prospectively; no probability of +10% is claimed until enough forward observations exist."},
 "candidates":candidates[:30],"portfolio_state":state}
(DATA/"power10.json").write_text(json.dumps(out,indent=2,ensure_ascii=False))
print(json.dumps({"generated":str(DATA/"power10.json"),"top":candidates[:5]},indent=2))
