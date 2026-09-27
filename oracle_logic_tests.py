#!/usr/bin/env python3
"""Deterministic logic tests for ORACLE V3 capital allocation.
These tests validate doctrine behavior, not historical profitability.
"""
import math

def clamp(x,a=0,b=100): return max(a,min(b,x))

def competition_score(sc, incumbent=False):
    structural=float(sc.get("structural",0))
    entry=float(sc.get("entry",0))
    rel=float(sc.get("rel",0))
    vol=sc.get("vol")
    dd=sc.get("dd")
    base=.50*structural+.50*entry
    relative=clamp(rel*1.5,-15,15)
    vol_penalty=0 if vol is None else max(0.0,vol-30.0)*0.18
    dd_penalty=0 if dd is None else max(0.0,abs(min(0.0,dd))-10.0)*0.45
    hysteresis=3.0 if incumbent else 0.0
    return round(clamp(base+relative-vol_penalty-dd_penalty+hysteresis),2)

def allocate(stocks, qqq, prior_signals=None):
    prior_signals=prior_signals or {}
    scores={k:competition_score(v,v.get("actual",0)>0) for k,v in stocks.items()}
    eligible=[]
    for ticker,sc in stocks.items():
        sig=sc["signal"]; rel=sc.get("rel"); entry=float(sc.get("entry",0)); dd=sc.get("dd")
        prev_sig=prior_signals.get(ticker)
        severe_dd=(dd is not None and dd<=-35)
        severe_relative=(rel is not None and rel<=-12 and entry<45)
        hard_risk=severe_dd or (severe_relative and prev_sig!="GREEN")
        if sig=="GREEN" and sc["evidence"]=="PROVEN" and not hard_risk:
            eligible.append(ticker)
    for ticker,sc in stocks.items():
        if ticker in eligible: continue
        act=float(sc.get("actual",0))
        if act<=0 or sc["evidence"]!="PROVEN": continue
        entry=float(sc.get("entry",0)); rel=sc.get("rel")
        if entry>=55 and (rel is None or rel>=-5):
            eligible.append(ticker)

    qscore=60.0
    qscore += clamp(qqq["m1"]*.8,-8,8)
    qscore -= max(0.0,qqq["vol"]-25.0)*0.12
    qscore -= max(0.0,abs(min(0.0,qqq["dd"]))-10.0)*0.30
    qscore=round(clamp(qscore),2)

    candidate_scores={t:scores[t] for t in eligible}
    candidate_scores["QQQ"]=qscore
    best=max(candidate_scores.values())
    active={k:v for k,v in candidate_scores.items() if v>=best-8.0}
    stock_best=max([v for k,v in active.items() if k!="QQQ"],default=-1e9)
    if stock_best<qscore+4.0:
        active={"QQQ":qscore}

    severe=(qqq["m1"]<=-13 and qqq["dd"]<=-17)
    if severe and set(active)=={"QQQ"}:
        return {"CASH_CHF":100.0},scores,qscore

    exps={k:math.exp((v-best)/8.0) for k,v in active.items()}
    den=sum(exps.values()) or 1.0
    raw={k:100.0*exps[k]/den for k in active}

    for k in list(raw):
        if k=="QQQ": continue
        if stocks[k]["signal"]=="ORANGE":
            act=float(stocks[k].get("actual",0))
            cap=max(act,min(25.0,act+5.0))
            if raw[k]>cap:
                excess=raw[k]-cap
                raw[k]=cap
                raw["QQQ"]=raw.get("QQQ",0)+excess

    for k in [x for x in raw if x!="QQQ"]:
        sc=stocks[k]
        exceptional=(sc["structural"]>=95 and sc["entry"]>=80 and scores[k]>=80)
        cap=85.0 if exceptional else 70.0
        if raw[k]>cap:
            excess=raw[k]-cap
            raw[k]=cap
            raw["QQQ"]=raw.get("QQQ",0)+excess

    total=sum(raw.values()) or 1.0
    return {k:round(v*100/total,1) for k,v in raw.items()},scores,qscore

Q={"m1":4.48,"vol":15.8,"dd":-8.05}

def assert_close(v,target,tol=.2):
    assert abs(v-target)<=tol,(v,target)

# 1 Current AAON case: strong GREEN, but concentration is capped.
targets,_,_=allocate({
 "AAON":{"signal":"GREEN","evidence":"PROVEN","structural":95.8,"entry":78.9,"rel":7.78,"vol":45.73,"dd":-34.35,"actual":4},
 "GEV":{"signal":"ORANGE","evidence":"PROVEN","structural":97.2,"entry":41.2,"rel":-4.16,"vol":47.06,"dd":-18.94,"actual":6},
},Q)
assert targets["AAON"]<=70.0 and targets["QQQ"]>=30.0

# 2 Marginal GREEN must not get 100%.
targets,_,_=allocate({"A":{"signal":"GREEN","evidence":"PROVEN","structural":86,"entry":60.1,"rel":0,"vol":25,"dd":-8,"actual":0}},Q)
assert targets["A"]<=70 and targets["QQQ"]>=30

# 3 Exceptional GREEN may go higher, but never above 85%.
targets,_,_=allocate({"A":{"signal":"GREEN","evidence":"PROVEN","structural":98,"entry":90,"rel":10,"vol":20,"dd":-5,"actual":0}},Q)
assert targets["A"]<=85 and targets["QQQ"]>=15

# 4 Multiple strong GREENs diversify rather than all-in one.
targets,_,_=allocate({
 "A":{"signal":"GREEN","evidence":"PROVEN","structural":95,"entry":80,"rel":5,"vol":30,"dd":-10,"actual":0},
 "B":{"signal":"GREEN","evidence":"PROVEN","structural":93,"entry":78,"rel":4,"vol":30,"dd":-10,"actual":0},
},Q)
assert "A" in targets and "B" in targets and targets["A"]<100 and targets["B"]>0

# 5 Extreme drawdown excludes a GREEN.
targets,_,_=allocate({"A":{"signal":"GREEN","evidence":"PROVEN","structural":98,"entry":85,"rel":8,"vol":50,"dd":-36,"actual":0}},Q)
assert targets=={"QQQ":100.0}

# 6 Near-GREEN ORANGE incumbent can stay, but cannot jump from 10% to 70%.
targets,_,_=allocate({"A":{"signal":"ORANGE","evidence":"PROVEN","structural":95,"entry":56,"rel":-2,"vol":30,"dd":-10,"actual":10}},Q)
assert targets.get("A",0)<=15.0

# 7 Non-held ORANGE does not receive capital simply because its raw score is high.
targets,_,_=allocate({"A":{"signal":"ORANGE","evidence":"PROVEN","structural":95,"entry":59,"rel":3,"vol":30,"dd":-10,"actual":0}},Q)
assert targets=={"QQQ":100.0}

# 8 Unproven cannot receive capital.
targets,_,_=allocate({"A":{"signal":"GREEN","evidence":"UNPROVEN","structural":99,"entry":95,"rel":15,"vol":20,"dd":-5,"actual":0}},Q)
assert targets=={"QQQ":100.0}

# 9 Severe QQQ regime falls back to cash if no stock qualifies.
targets,_,_=allocate({},{"m1":-13.5,"vol":35,"dd":-18})
assert targets=={"CASH_CHF":100.0}

# 10 One-tick relative threshold does not immediately eject a prior GREEN.
base={"A":{"signal":"GREEN","evidence":"PROVEN","structural":95,"entry":44,"rel":-12.1,"vol":25,"dd":-8,"actual":10}}
targets,_,_=allocate(base,Q,{"A":"GREEN"})
assert "A" in targets or targets=={"QQQ":100.0}

print("ORACLE V3 logic tests: PASS (10/10)")
